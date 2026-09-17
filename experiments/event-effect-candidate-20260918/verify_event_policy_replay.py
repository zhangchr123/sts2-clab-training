"""Recompute recorded event states through the assembled parent and candidate policies."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from event_effect_features import CONTRACT
from event_effect_policy import EventEffectPolicy, VERSION
from persistent_acquisition_policy import PersistentAcquisitionPolicy


def require(condition, message):
    if not condition:
        raise ValueError(message)


def jsonl_map(path, execution=False):
    result = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        key = row.get("decision_id")
        if key and (key not in result or execution and "execution" in row):
            result[key] = row
    return result


def greedy(rows):
    best = max(row["score"] for row in rows)
    return {row["candidate_id"] for row in rows if abs(row["score"] - best) <= 1e-12}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--outputs", type=Path, required=True)
    parser.add_argument("--audits", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    parent_artifact = json.loads(args.parent.read_text(encoding="utf-8"))
    candidate_artifact = json.loads(args.candidate.read_text(encoding="utf-8"))
    settings = parent_artifact["solver_requested_config"]
    require(candidate_artifact["solver_requested_config"] == settings, "Solver config differs")
    runs = set()
    for root in args.audits:
        for path in root.rglob("*-audit.json"):
            audit = json.loads(path.read_text(encoding="utf-8"))
            run_id = (audit.get("job") or {}).get("name") or audit.get("run_id")
            if audit.get("integration_passed") and run_id:
                runs.add(run_id)
    decisions = 0
    changed = 0
    reduced_ties = 0
    exact_parent_additivity = 0
    digests = {}
    for run_id in sorted(runs):
        folder = args.outputs / run_id
        if not (folder / "decisions.jsonl").is_file() or not (folder / "policy.jsonl").is_file():
            continue
        states = jsonl_map(folder / "decisions.jsonl", execution=True)
        policies = jsonl_map(folder / "policy.jsonl")
        parent = PersistentAcquisitionPolicy(args.parent, solver_config=settings, seed=run_id, epsilon=0.0)
        candidate = EventEffectPolicy(args.candidate, solver_config=settings, seed=run_id, epsilon=0.0)
        for decision_id, recorded in policies.items():
            state = states[decision_id]["state"]
            if state.get("decision") != "event_choice":
                continue
            requests = [row["request"] for row in recorded["scoring"]["scores"]]
            before = parent.score_requests(state, requests)
            after = candidate.score_requests(state, requests)
            require(after["policy_id"] == VERSION, "Candidate scoring id differs")
            require(after["event_effect_contract"] == CONTRACT, "Event contract differs")
            by_before = {row["candidate_id"]: row for row in before["scores"]}
            for row in after["scores"]:
                base = by_before[row["candidate_id"]]
                require(row["request"] == base["request"], "Candidate request differs")
                require(abs(row["score"] - row["event_effect_adjustment"] - base["score"]) <= 1e-10,
                        "Event score is not exactly additive")
                detail = row["event_effect_detail"]
                if detail.get("applied"):
                    require(detail["natural_outcomes_used"] is False,
                            "Event scorer claims natural outcome use")
                else:
                    require(detail.get("reason") == "not_event_choice",
                            "Non-event candidate has unexplained event adjustment")
            old_greedy, new_greedy = greedy(before["scores"]), greedy(after["scores"])
            decisions += 1
            changed += old_greedy != new_greedy
            reduced_ties += len(new_greedy) < len(old_greedy)
            exact_parent_additivity += 1
            digest_payload = [
                {
                    "candidate_id": row["candidate_id"],
                    "score": row["score"],
                    "adjustment": row["event_effect_adjustment"],
                    "features": row["event_effect_features"],
                }
                for row in after["scores"]
            ]
            digests[decision_id] = hashlib.sha256(
                json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
    result = {
        "schema_version": "assembled-event-policy-replay-v1",
        "decisions": decisions,
        "greedy_set_changed": changed,
        "tie_size_reduced": reduced_ties,
        "exact_parent_additivity": exact_parent_additivity,
        "combined_sha256": hashlib.sha256(
            json.dumps(digests, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "contract": CONTRACT,
        "passed": decisions > 0 and exact_parent_additivity == decisions,
        "natural_outcomes_used_for_weight_selection": False,
        "game_execution_performed": False,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
