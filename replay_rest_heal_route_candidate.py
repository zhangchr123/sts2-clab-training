"""Replay fixed exact-heal route-risk utility over frozen natural rests."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
import json
import math
from pathlib import Path
import statistics

from decision_data import DataContractError, enumerate_candidates
import encounter_damage_features
import rest_heal_route_features
from run_metadata import file_evidence


def require(condition, message):
    if not condition:
        raise DataContractError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def greedy_ids(rows):
    best = max(row["score"] for row in rows)
    return sorted(row["candidate_id"] for row in rows
                  if math.isclose(row["score"], best, rel_tol=0.0, abs_tol=1e-12))


def option_by_candidate(state):
    return {
        candidate["candidate_id"]: str(candidate["evidence"].get(
            "option_id", candidate["evidence"].get("name", "")
        )).upper()
        for candidate in enumerate_candidates(state)["candidates"]
    }


def replay(run_root, prefixes, expected_runs, catalog_path):
    run_root = Path(run_root).resolve()
    catalog_path = Path(catalog_path).resolve()
    catalog = read(catalog_path)
    encounter_damage_features.validate_catalog(catalog)
    run_dirs, excluded = [], []
    for directory in sorted(run_root.iterdir()):
        if not directory.is_dir() or not any(directory.name.startswith(p) for p in prefixes):
            continue
        paths = [directory / name for name in
                 ("status.json", "decisions.jsonl", "policy.jsonl")]
        if not all(path.is_file() for path in paths):
            excluded.append({"run_id": directory.name, "reason": "incomplete_evidence"})
            continue
        status = read(paths[0])
        if status.get("status") != "finished" or status.get("error") is not None:
            excluded.append({"run_id": directory.name, "reason": "not_clean_terminal",
                             "status": status.get("status"),
                             "error_present": status.get("error") is not None})
            continue
        run_dirs.append(directory)
    require(len(run_dirs) == expected_runs,
            f"Expected {expected_runs} clean runs, found {len(run_dirs)}")

    sources, examples = [], []
    decisions = rows_count = exact = changed = covered = 0
    adjustments = []
    switch = Counter()
    by_act = defaultdict(lambda: Counter(decisions=0, changed=0))
    missing_before, missing_after = Counter(), Counter()
    for directory in run_dirs:
        decision_path = directory / "decisions.jsonl"
        policy_path = directory / "policy.jsonl"
        decision_rows = [row for row in read_jsonl(decision_path)
                         if row.get("record_type") == "decision_completed"]
        policy_rows = read_jsonl(policy_path)
        require(len(decision_rows) == len(policy_rows)
                and all(left["decision_id"] == right["decision_id"]
                        for left, right in zip(decision_rows, policy_rows)),
                f"Policy/state sequence differs: {directory}")
        sources.extend((file_evidence(decision_path), file_evidence(policy_path)))
        last_map = None
        for decision, recorded in zip(decision_rows, policy_rows):
            state = decision["state"]
            if recorded.get("map_observation") is not None:
                last_map = {
                    "state": state,
                    "observation": recorded["map_observation"],
                    "request": recorded["request"],
                }
            if state.get("decision") != "rest_site":
                continue
            require(last_map is not None, "Rest replay lacks prior public map")
            context = rest_heal_route_features.make_context(
                last_map["state"], last_map["observation"],
                last_map["request"], catalog,
            )
            require(context is not None, "Rest replay context is unavailable")
            parent = recorded.get("scoring") or {}
            candidate = rest_heal_route_features.adjust(state, parent, context)
            parent_rows = {row["candidate_id"]: row for row in parent["scores"]}
            candidate_rows = {row["candidate_id"]: row
                              for row in candidate["scores"]}
            require(parent_rows.keys() == candidate_rows.keys(),
                    f"Rest candidates differ: {decision['decision_id']}")
            decision_exact = True
            for candidate_id, row in candidate_rows.items():
                before = parent_rows[candidate_id]
                adjustment = row["rest_heal_route_adjustment"]
                decision_exact &= math.isclose(
                    row["score"], before["score"] + adjustment,
                    rel_tol=0.0, abs_tol=1e-12,
                )
                adjustments.append(adjustment)
                missing_before.update(before.get("missing") or [])
                missing_after.update(row.get("missing") or [])
                covered += int(row["rest_heal_route_detail"]["applied"])
                rows_count += 1
            require(decision_exact,
                    f"Rest adjustment is not additive: {decision['decision_id']}")
            exact += 1
            parent_greedy = greedy_ids(parent["scores"])
            candidate_greedy = greedy_ids(candidate["scores"])
            did_change = parent_greedy != candidate_greedy
            changed += int(did_change)
            identities = option_by_candidate(state)
            parent_options = sorted(identities[candidate_id]
                                    for candidate_id in parent_greedy)
            candidate_options = sorted(identities[candidate_id]
                                       for candidate_id in candidate_greedy)
            if did_change:
                direction = "_to_".join(("+".join(parent_options),
                                          "+".join(candidate_options)))
                switch[direction] += 1
            act = str((state.get("context") or {}).get("act"))
            by_act[act]["decisions"] += 1
            by_act[act]["changed"] += int(did_change)
            if did_change and len(examples) < 100:
                examples.append({
                    "run_id": directory.name,
                    "decision_id": decision["decision_id"],
                    "act": act,
                    "floor": (state.get("context") or {}).get("floor"),
                    "hp": (state.get("player") or {}).get("hp"),
                    "max_hp": (state.get("player") or {}).get("max_hp"),
                    "parent_greedy": parent_options,
                    "candidate_greedy": candidate_options,
                    "parent_scores": {identities[key]: parent_rows[key]["score"]
                                      for key in parent_rows},
                    "candidate_scores": {identities[key]: candidate_rows[key]["score"]
                                         for key in candidate_rows},
                    "adjustments": {identities[key]: candidate_rows[key][
                        "rest_heal_route_adjustment"] for key in candidate_rows},
                    "heal_projection": next(
                        row["rest_heal_route_detail"]["heal_projection"]
                        for row in candidate_rows.values()
                        if row["rest_heal_route_detail"]["applied"]
                    ),
                    "route": copy.deepcopy(context["route"]),
                })
            decisions += 1
    require(decisions > 0 and exact == decisions,
            "No exact rest replay evidence")
    cap = rest_heal_route_features.CONTRACT["candidate_adjustment_abs_cap"]
    cap_hits = sum(math.isclose(abs(value), cap, rel_tol=0.0, abs_tol=1e-12)
                   for value in adjustments)
    return {
        "schema_version": "rest-heal-route-fixed-prior-offline-replay-v1",
        "passed": True,
        "interpretation": {
            "purpose": "exact public heal and downstream route-risk additivity audit",
            "policy_weights_fitted": False,
            "natural_outcomes_used_for_weight_selection": False,
            "win_rate_claim_permitted": False,
            "automatic_deployment": False,
        },
        "contract": copy.deepcopy(rest_heal_route_features.CONTRACT),
        "parameters": copy.deepcopy(rest_heal_route_features.PRIOR),
        "catalog": file_evidence(catalog_path),
        "selection": {
            "run_prefixes": list(prefixes),
            "runs": len(run_dirs),
            "run_ids": [directory.name for directory in run_dirs],
            "excluded_runs": excluded,
        },
        "counts": {
            "rest_decisions": decisions,
            "candidate_rows": rows_count,
            "exact_additivity_decisions": exact,
            "covered_heal_rows": covered,
            "greedy_set_changed": changed,
        },
        "adjustments": {
            "minimum": min(adjustments),
            "maximum": max(adjustments),
            "mean": statistics.fmean(adjustments),
            "median": statistics.median(adjustments),
            "mean_absolute": statistics.fmean(abs(value) for value in adjustments),
            "cap_hits": cap_hits,
            "cap_hit_fraction": cap_hits / len(adjustments),
            "within_declared_cap": all(abs(value) <= cap for value in adjustments),
        },
        "switch_direction": dict(switch),
        "strata": {
            "act": {key: dict(value) for key, value in sorted(by_act.items())},
        },
        "missing_signal": {
            "actual_rest_heal_amount_before": missing_before[
                "actual_rest_heal_amount"
            ],
            "actual_rest_heal_amount_after": missing_after[
                "actual_rest_heal_amount"
            ],
            "future_route_damage_before": missing_before[
                "future_route_damage_distribution"
            ],
            "future_route_damage_after": missing_after[
                "future_route_damage_distribution"
            ],
            "unknown_room_outcomes_after": missing_after[
                "unknown_room_outcomes"
            ],
        },
        "changed_examples": examples,
        "sources": {
            "decision_and_policy_files": sources,
            "feature_source": file_evidence(
                Path(rest_heal_route_features.__file__).resolve()
            ),
            "relic_table": file_evidence(
                rest_heal_route_features.RELIC_TABLE_PATH
            ),
            "catalog": file_evidence(catalog_path),
            "replay_source": file_evidence(Path(__file__).resolve()),
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--run-prefix", action="append", required=True)
    parser.add_argument("--expected-runs", type=int, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = replay(
        args.run_root, args.run_prefix, args.expected_runs, args.catalog
    )
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({key: result[key] for key in (
        "passed", "counts", "adjustments", "switch_direction", "strata",
        "missing_signal",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
