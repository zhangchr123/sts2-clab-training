"""Replay fixed current reward semantics over frozen clean natural runs."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
import json
import math
from pathlib import Path
import statistics

from decision_data import DataContractError
import reward_mechanism_features
from run_metadata import file_evidence


def require(condition, message):
    if not condition:
        raise DataContractError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def completed_states(path):
    return {row["decision_id"]: row["state"] for row in read_jsonl(path)
            if row.get("record_type") == "decision_completed"}


def greedy_ids(rows):
    best = max(row["score"] for row in rows)
    return sorted(row["candidate_id"] for row in rows
                  if math.isclose(row["score"], best, rel_tol=0.0, abs_tol=1e-12))


def mean(values):
    return statistics.fmean(values) if values else None


def replay(run_root, prefixes, expected_runs):
    run_root = Path(run_root).resolve()
    run_dirs, excluded = [], []
    for directory in sorted(run_root.iterdir()):
        if not directory.is_dir() or not any(directory.name.startswith(p) for p in prefixes):
            continue
        status_path = directory / "status.json"
        decisions_path = directory / "decisions.jsonl"
        policy_path = directory / "policy.jsonl"
        if not all(path.is_file() for path in (status_path, decisions_path, policy_path)):
            excluded.append({"run_id": directory.name, "reason": "incomplete_evidence"})
            continue
        status = read(status_path)
        if status.get("status") != "finished" or status.get("error") is not None:
            excluded.append({"run_id": directory.name, "reason": "not_clean_terminal",
                             "status": status.get("status"),
                             "error_present": status.get("error") is not None})
            continue
        run_dirs.append(directory)
    require(len(run_dirs) == expected_runs,
            f"Expected {expected_runs} clean runs, found {len(run_dirs)}")

    sources = []
    decisions = rows_count = exact = changed = covered_rows = 0
    adjustments = []
    switch = Counter()
    by_act = defaultdict(lambda: Counter(decisions=0, changed=0))
    by_deck = defaultdict(lambda: Counter(decisions=0, changed=0))
    covered_cards = Counter()
    missing_before = Counter()
    missing_after = Counter()
    examples = []
    for directory in run_dirs:
        decision_path = directory / "decisions.jsonl"
        policy_path = directory / "policy.jsonl"
        states = completed_states(decision_path)
        policies = read_jsonl(policy_path)
        require(len(states) == len(policies), f"Policy/state count differs: {directory}")
        sources.extend((file_evidence(decision_path), file_evidence(policy_path)))
        for recorded in policies:
            scoring = recorded.get("scoring") or {}
            score_rows = scoring.get("scores") or []
            if not any((row.get("request") or {}).get("action") == "select_card_reward"
                       for row in score_rows):
                continue
            decision_id = recorded["decision_id"]
            state = states.get(decision_id)
            require(isinstance(state, dict) and state.get("decision") == "card_reward",
                    f"Reward state differs: {decision_id}")
            candidate = reward_mechanism_features.adjust(state, scoring)
            parent_by_id = {row["candidate_id"]: row for row in score_rows}
            candidate_by_id = {row["candidate_id"]: row for row in candidate["scores"]}
            require(parent_by_id.keys() == candidate_by_id.keys(),
                    f"Reward candidates differ: {decision_id}")
            decision_exact = True
            for candidate_id, row in candidate_by_id.items():
                parent = parent_by_id[candidate_id]
                adjustment = row["reward_mechanism_adjustment"]
                decision_exact &= math.isclose(
                    row["score"], parent["score"] + adjustment,
                    rel_tol=0.0, abs_tol=1e-12,
                )
                adjustments.append(adjustment)
                missing_before.update(parent.get("missing") or [])
                missing_after.update(row.get("missing") or [])
                detail = row["reward_mechanism_detail"]
                covered_rows += int(detail["applied"])
                covered_cards.update(detail["covered_cards"])
                rows_count += 1
            require(decision_exact, f"Reward adjustment is not additive: {decision_id}")
            exact += 1
            parent_greedy = greedy_ids(score_rows)
            candidate_greedy = greedy_ids(candidate["scores"])
            did_change = parent_greedy != candidate_greedy
            changed += int(did_change)
            parent_skip = all(parent_by_id[cid].get("is_skip") for cid in parent_greedy)
            candidate_skip = all(candidate_by_id[cid].get("is_skip") for cid in candidate_greedy)
            if did_change:
                if parent_skip and not candidate_skip:
                    direction = "skip_to_take"
                elif not parent_skip and candidate_skip:
                    direction = "take_to_skip"
                else:
                    direction = "card_to_card"
                switch[direction] += 1
            act = str((state.get("context") or {}).get("act"))
            deck_size = (state.get("player") or {}).get("deck_size")
            if not isinstance(deck_size, int):
                deck_size = len((state.get("player") or {}).get("deck") or [])
            deck_bucket = "at_most_25" if deck_size <= 25 else "26_to_36" if deck_size <= 36 else "over_36"
            by_act[act]["decisions"] += 1
            by_act[act]["changed"] += int(did_change)
            by_deck[deck_bucket]["decisions"] += 1
            by_deck[deck_bucket]["changed"] += int(did_change)
            if did_change and len(examples) < 150:
                examples.append({
                    "run_id": directory.name,
                    "decision_id": decision_id,
                    "act": act,
                    "floor": (state.get("context") or {}).get("floor"),
                    "deck_size": deck_size,
                    "direction": direction,
                    "parent_greedy": parent_greedy,
                    "candidate_greedy": candidate_greedy,
                    "parent_scores": {cid: row["score"] for cid, row in parent_by_id.items()},
                    "candidate_scores": {cid: row["score"] for cid, row in candidate_by_id.items()},
                    "covered_cards": {cid: candidate_by_id[cid]["reward_mechanism_detail"]["covered_cards"]
                                      for cid in candidate_by_id},
                    "adjustments": {cid: candidate_by_id[cid]["reward_mechanism_adjustment"]
                                    for cid in candidate_by_id},
                })
            decisions += 1
    require(decisions > 0 and exact == decisions, "No exact reward replay evidence")
    cap = reward_mechanism_features.FEATURE_CONTRACT["candidate_adjustment_abs_cap"]
    cap_hits = sum(math.isclose(abs(value), cap, rel_tol=0.0, abs_tol=1e-12)
                   for value in adjustments)
    return {
        "schema_version": "reward-mechanism-fixed-prior-offline-replay-v1",
        "passed": True,
        "interpretation": {
            "purpose": "fixed current-engine reward semantic additivity and behavior audit",
            "policy_weights_fitted": False,
            "natural_outcomes_used_for_weight_selection": False,
            "win_rate_claim_permitted": False,
            "automatic_deployment": False,
        },
        "contract": copy.deepcopy(reward_mechanism_features.FEATURE_CONTRACT),
        "parameters": copy.deepcopy(reward_mechanism_features.PRIOR),
        "selection": {
            "run_prefixes": list(prefixes), "runs": len(run_dirs),
            "run_ids": [directory.name for directory in run_dirs],
            "excluded_runs": excluded,
        },
        "counts": {
            "reward_decisions": decisions, "candidate_rows": rows_count,
            "exact_additivity_decisions": exact,
            "covered_candidate_rows": covered_rows,
            "greedy_set_changed": changed,
        },
        "adjustments": {
            "minimum": min(adjustments), "maximum": max(adjustments),
            "mean": mean(adjustments), "median": statistics.median(adjustments),
            "mean_absolute": mean([abs(value) for value in adjustments]),
            "cap_hits": cap_hits, "cap_hit_fraction": cap_hits / len(adjustments),
            "within_declared_cap": all(abs(value) <= cap for value in adjustments),
        },
        "switch_direction": dict(switch),
        "strata": {
            "act": {key: dict(value) for key, value in sorted(by_act.items())},
            "deck_size": {key: dict(value) for key, value in sorted(by_deck.items())},
        },
        "covered_cards": dict(covered_cards.most_common()),
        "missing_signal": {
            "mechanism_coverage_before": missing_before["mechanism_coverage"],
            "mechanism_coverage_after": missing_after["mechanism_coverage"],
            "current_card_stats_before": missing_before["current_card_stats"],
            "current_card_stats_after": missing_after["current_card_stats"],
            "cards_effect_semantics_before": missing_before["cards_effect_semantics"],
            "cards_effect_semantics_after": missing_after["cards_effect_semantics"],
            "energy_effect_semantics_before": missing_before["energy_effect_semantics"],
            "energy_effect_semantics_after": missing_after["energy_effect_semantics"],
        },
        "changed_examples": examples,
        "sources": {
            "decision_and_policy_files": sources,
            "facts_source": file_evidence(Path(__import__("reward_mechanism_facts").__file__).resolve()),
            "feature_source": file_evidence(Path(reward_mechanism_features.__file__).resolve()),
            "card_table": file_evidence(Path(__import__("reward_mechanism_facts").CATALOG_PATH).resolve()),
            "replay_source": file_evidence(Path(__file__).resolve()),
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--run-prefix", action="append", required=True)
    parser.add_argument("--expected-runs", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = replay(args.run_root, args.run_prefix, args.expected_runs)
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                                     allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in (
        "passed", "counts", "adjustments", "switch_direction", "strata",
        "covered_cards", "missing_signal",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
