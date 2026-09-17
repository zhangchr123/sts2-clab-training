"""Replay the fixed public encounter-damage prior over frozen natural runs.

The damage catalog is fitted only by its separately audited grouped split.  This
replay measures fixed-weight additivity and behavior; it never selects weights
from run outcomes and never authorizes deployment.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
import json
import math
from pathlib import Path
import statistics

from decision_data import DataContractError
import encounter_damage_features
import full_route_features
from run_metadata import file_evidence


def require(condition, message):
    if not condition:
        raise DataContractError(message)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def completed_states(path):
    return {
        row["decision_id"]: row["state"]
        for row in read_jsonl(path)
        if row.get("record_type") == "decision_completed"
    }


def greedy_ids(rows):
    best = max(row["score"] for row in rows)
    return sorted(row["candidate_id"] for row in rows
                  if math.isclose(row["score"], best, rel_tol=0.0, abs_tol=1e-12))


def mean(values):
    return statistics.fmean(values) if values else None


def _average_summary(ids, summaries, key):
    values = [summaries[candidate_id][key] for candidate_id in ids
              if summaries[candidate_id]["path_available"]]
    return mean(values)


def replay(run_root, prefixes, expected_runs, catalog_path):
    run_root = Path(run_root).resolve()
    catalog_path = Path(catalog_path).resolve()
    require(run_root.is_dir(), "Run root is missing")
    catalog = read_json(catalog_path)
    encounter_damage_features.validate_catalog(catalog)
    run_dirs = []
    excluded_runs = []
    for directory in sorted(run_root.iterdir()):
        if not directory.is_dir() or not any(directory.name.startswith(p) for p in prefixes):
            continue
        status_path = directory / "status.json"
        decisions_path = directory / "decisions.jsonl"
        policy_path = directory / "policy.jsonl"
        if not (status_path.is_file() and decisions_path.is_file() and policy_path.is_file()):
            excluded_runs.append({"run_id": directory.name, "reason": "incomplete_evidence"})
            continue
        status = read_json(status_path)
        if status.get("status") != "finished" or status.get("error") is not None:
            excluded_runs.append({
                "run_id": directory.name,
                "reason": "not_clean_terminal",
                "status": status.get("status"),
                "error_present": status.get("error") is not None,
            })
            continue
        run_dirs.append(directory)
    require(len(run_dirs) == expected_runs,
            f"Expected {expected_runs} frozen runs, found {len(run_dirs)}")

    source_files = []
    adjustments = []
    availability = Counter()
    by_act = defaultdict(lambda: Counter(decisions=0, changed=0, lower_q75_stop=0))
    by_hp = defaultdict(lambda: Counter(decisions=0, changed=0, lower_q75_stop=0))
    missing_before = Counter()
    missing_after = Counter()
    changed_examples = []
    decisions = candidate_rows = exact_additivity = 0
    lower_q75 = equal_q75 = higher_q75 = unknown_direction = 0

    for directory in run_dirs:
        decisions_path = directory / "decisions.jsonl"
        policy_path = directory / "policy.jsonl"
        states = completed_states(decisions_path)
        policies = read_jsonl(policy_path)
        require(len(states) == len(policies), f"Decision/policy count differs: {directory}")
        source_files.extend((file_evidence(decisions_path), file_evidence(policy_path)))
        for recorded in policies:
            if recorded.get("map_observation") is None:
                continue
            decision_id = recorded.get("decision_id")
            state = states.get(decision_id)
            require(isinstance(state, dict) and state.get("decision") == "map_select",
                    f"Map policy row has no matching map state: {decision_id}")
            recorded_parent = recorded.get("scoring")
            require(isinstance(recorded_parent, dict) and recorded_parent.get("scores"),
                    f"Map parent scoring is absent: {decision_id}")
            full_input = full_route_features.policy_input(state, recorded["map_observation"])
            parent = full_route_features.adjust(state, recorded_parent, full_input)
            damage_input = encounter_damage_features.policy_input(
                state, recorded["map_observation"], catalog
            )
            candidate = encounter_damage_features.adjust(state, parent, damage_input)
            parent_rows = {row["candidate_id"]: row for row in parent["scores"]}
            candidate_by_id = {row["candidate_id"]: row for row in candidate["scores"]}
            require(parent_rows.keys() == candidate_by_id.keys(),
                    f"Encounter-damage candidate set differs: {decision_id}")
            decision_exact = True
            for candidate_id, row in candidate_by_id.items():
                before = parent_rows[candidate_id]
                adjustment = row["encounter_damage_adjustment"]
                adjustments.append(adjustment)
                missing_before.update(before.get("missing") or [])
                missing_after.update(row.get("missing") or [])
                decision_exact &= math.isclose(
                    row["score"], before["score"] + adjustment,
                    rel_tol=0.0, abs_tol=1e-12,
                )
                candidate_rows += 1
            require(decision_exact, f"Encounter-damage adjustment is not additive: {decision_id}")
            exact_additivity += 1

            parent_greedy = greedy_ids(parent["scores"])
            candidate_greedy = greedy_ids(candidate["scores"])
            changed = parent_greedy != candidate_greedy
            summaries = {row["candidate_id"]: row["summary"]
                         for row in damage_input["per_candidate"]}
            parent_q75 = _average_summary(
                parent_greedy, summaries, "damage_q75_to_stop_min"
            )
            candidate_q75 = _average_summary(
                candidate_greedy, summaries, "damage_q75_to_stop_min"
            )
            if changed and parent_q75 is not None and candidate_q75 is not None:
                if candidate_q75 < parent_q75 - 1e-12:
                    lower_q75 += 1
                    direction = "lower"
                elif candidate_q75 > parent_q75 + 1e-12:
                    higher_q75 += 1
                    direction = "higher"
                else:
                    equal_q75 += 1
                    direction = "equal"
            elif changed:
                unknown_direction += 1
                direction = "unavailable"
            else:
                direction = "unchanged"
            act = state["context"]["act"]
            hp_ratio = state["player"]["hp"] / state["player"]["max_hp"]
            hp_bucket = ("low_0_33" if hp_ratio <= 1 / 3 else
                         "mid_33_66" if hp_ratio <= 2 / 3 else "high_66_100")
            by_act[str(act)]["decisions"] += 1
            by_act[str(act)]["changed"] += int(changed)
            by_act[str(act)]["lower_q75_stop"] += int(direction == "lower")
            by_hp[hp_bucket]["decisions"] += 1
            by_hp[hp_bucket]["changed"] += int(changed)
            by_hp[hp_bucket]["lower_q75_stop"] += int(direction == "lower")
            availability[damage_input["status"]] += 1
            if changed and len(changed_examples) < 100:
                changed_examples.append({
                    "run_id": directory.name,
                    "decision_id": decision_id,
                    "act": act,
                    "hp_ratio": hp_ratio,
                    "parent_greedy": parent_greedy,
                    "candidate_greedy": candidate_greedy,
                    "q75_stop_direction": direction,
                    "parent_q75_to_stop_min": parent_q75,
                    "candidate_q75_to_stop_min": candidate_q75,
                    "parent_scores": {key: parent_rows[key]["score"] for key in parent_rows},
                    "candidate_scores": {
                        key: candidate_by_id[key]["score"] for key in candidate_by_id
                    },
                    "summaries": summaries,
                })
            decisions += 1

    require(decisions > 0 and exact_additivity == decisions, "No exact map replay evidence")
    total_changed = sum(value["changed"] for value in by_act.values())
    cap = encounter_damage_features.CONTRACT["candidate_adjustment_abs_cap"]
    cap_hits = sum(math.isclose(abs(value), cap, rel_tol=0.0, abs_tol=1e-12)
                   for value in adjustments)
    result = {
        "schema_version": "encounter-damage-fixed-prior-offline-replay-v1",
        "passed": True,
        "interpretation": {
            "purpose": "descriptive fixed-prior additivity and behavior audit",
            "catalog_fitted_from_grouped_train_validation_natural_combat_damage": True,
            "catalog_test_used_for_parameter_selection": False,
            "policy_parameters_fitted": False,
            "natural_outcomes_used_for_policy_weight_selection": False,
            "win_rate_claim_permitted": False,
            "automatic_deployment": False,
        },
        "contract": copy.deepcopy(encounter_damage_features.CONTRACT),
        "parameters": copy.deepcopy(encounter_damage_features.PRIOR),
        "catalog": file_evidence(catalog_path),
        "catalog_holdout": {
            "overall": copy.deepcopy(catalog["held_out_test"]),
            "act3_boss": copy.deepcopy(catalog["held_out_test_by_cell"].get("act3:Boss")),
            "act3_elite": copy.deepcopy(catalog["held_out_test_by_cell"].get("act3:Elite")),
        },
        "selection": {
            "run_prefixes": list(prefixes),
            "runs": len(run_dirs),
            "run_ids": [directory.name for directory in run_dirs],
            "excluded_runs": excluded_runs,
        },
        "counts": {
            "map_decisions": decisions,
            "candidate_rows": candidate_rows,
            "exact_additivity_decisions": exact_additivity,
            "greedy_set_changed_from_full_route_parent": total_changed,
            "availability": dict(availability),
        },
        "adjustments": {
            "minimum": min(adjustments),
            "maximum": max(adjustments),
            "mean": mean(adjustments),
            "median": statistics.median(adjustments),
            "mean_absolute": mean([abs(value) for value in adjustments]),
            "cap_hits": cap_hits,
            "cap_hit_fraction": cap_hits / len(adjustments),
            "within_declared_cap": all(abs(value) <= cap for value in adjustments),
        },
        "switch_direction": {
            "lower_q75_damage_to_stop": lower_q75,
            "equal_q75_damage_to_stop": equal_q75,
            "higher_q75_damage_to_stop": higher_q75,
            "unavailable": unknown_direction,
        },
        "strata": {
            "act": {key: dict(value) for key, value in sorted(by_act.items())},
            "hp_ratio": {key: dict(value) for key, value in sorted(by_hp.items())},
        },
        "missing_signal": {
            "encounter_damage_before": missing_before["encounter_damage_distribution"],
            "encounter_damage_after": missing_after["encounter_damage_distribution"],
            "unknown_room_before": missing_before["unknown_room_outcomes"],
            "unknown_room_after": missing_after["unknown_room_outcomes"],
        },
        "changed_examples": changed_examples,
        "sources": {
            "decision_and_policy_files": source_files,
            "full_route_feature_source": file_evidence(
                Path(full_route_features.__file__).resolve()
            ),
            "encounter_damage_feature_source": file_evidence(
                Path(encounter_damage_features.__file__).resolve()
            ),
            "catalog_trainer_source": file_evidence(
                Path(__import__("train_encounter_damage_catalog").__file__).resolve()
            ),
            "replay_source": file_evidence(Path(__file__).resolve()),
        },
    }
    return result


def write_new(path, value):
    path = Path(path).resolve()
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


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
    write_new(args.output, result)
    print(json.dumps(
        {key: result[key] for key in (
            "passed", "catalog_holdout", "counts", "adjustments",
            "switch_direction", "strata", "missing_signal",
        )},
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
