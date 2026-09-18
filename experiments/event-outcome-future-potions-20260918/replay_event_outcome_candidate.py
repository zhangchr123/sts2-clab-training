"""Replay deterministic event outcomes over the frozen 95-run candidate corpus."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path

from build_encounter_damage_candidate import completed_states, read_jsonl
from build_reward_mechanism_candidate import advance_recorded_run_state, observe_recorded_action
from decision_data import DataContractError, enumerate_candidates
from event_outcome_policy import EventOutcomePolicy
from rest_heal_route_policy import RestHealRoutePolicy
from run_metadata import file_evidence


MARKER = "event_outcome_probability_model"


def require(condition, message):
    if not condition:
        raise DataContractError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_evidence(row):
    path = Path(row["path"])
    require(file_evidence(path) == row, f"Frozen evidence differs: {path}")
    return path


def identity(candidate):
    key = (candidate.get("evidence") or {}).get("text_key")
    if not isinstance(key, str) or ".pages." not in key or ".options." not in key:
        return None
    event = key.split(".pages.", 1)[0]
    option = key.rsplit(".options.", 1)[1]
    while option.endswith("_LOCKED"):
        option = option[:-7]
    return f"{event}:{option}"


def greedy(rows):
    best = max(row["score"] for row in rows)
    return {row["candidate_id"] for row in rows
            if math.isclose(row["score"], best, rel_tol=0.0, abs_tol=1e-12)}


def clear_event_inputs(policy, state):
    policy.set_public_route_input(state, None)
    policy.set_full_route_input(state, None)
    policy.set_encounter_damage_input(state, None)
    policy.set_rest_route_input(state, None)


def replay(manifest_path, model_path):
    manifest_path = Path(manifest_path).resolve()
    model_path = Path(model_path).resolve()
    manifest = read(manifest_path)
    require(manifest.get("passed") is True, "Event gap manifest did not pass")
    run_sources = (manifest.get("sources") or {}).get("runs") or []
    require(len(run_sources) == 95, "Expected the frozen 95-run corpus")
    model = read(model_path)
    solver_config = model["solver_requested_config"]
    parent_path = Path(model["parent_model"]["path"])
    require(file_evidence(parent_path) == model["parent_model"], "Candidate parent differs")

    counts = Counter()
    option_counts = defaultdict(Counter)
    score_stats = defaultdict(list)
    changed_examples = []
    run_evidence = []
    maximum_additivity_error = 0.0

    for run in run_sources:
        run_id = run["run_id"]
        decisions = verify_evidence(run["decisions"])
        policies = verify_evidence(run["policy"])
        status = verify_evidence(run["status"])
        audit = verify_evidence(run["audit"])
        run_evidence.append({
            "run_id": run_id,
            "category": run["category"],
            "status": file_evidence(status),
            "decisions": file_evidence(decisions),
            "policy": file_evidence(policies),
            "audit": file_evidence(audit),
        })
        states = completed_states(decisions)
        recorded_rows = read_jsonl(policies)
        require(states and len(states) == len(recorded_rows), f"Decision sequence differs: {run_id}")
        parent = RestHealRoutePolicy(parent_path, solver_config=solver_config,
                                     seed=run_id, epsilon=0.0)
        candidate = EventOutcomePolicy(model_path, solver_config=solver_config,
                                       seed=run_id, epsilon=0.0)
        parent._verify_encounter_damage_sources = lambda: None
        parent._verify_sources = lambda: None
        candidate._verify_encounter_damage_sources = lambda: None
        candidate._verify_sources = lambda: None

        for recorded in recorded_rows:
            decision_id = recorded["decision_id"]
            state = states.get(decision_id)
            require(isinstance(state, dict), f"Recorded decision lacks state: {decision_id}")
            parent_size = advance_recorded_run_state(parent, state)
            candidate_size = advance_recorded_run_state(candidate, state)
            require(parent_size == candidate_size, "Parent and candidate deck latches differ")
            scoring = recorded.get("scoring") or {}
            historical = scoring.get("scores") or []
            if state.get("decision") == "event_choice":
                require(historical, f"Event scoring is empty: {decision_id}")
                clear_event_inputs(parent, state)
                clear_event_inputs(candidate, state)
                requests = [row["request"] for row in historical]
                purpose = scoring.get("selection_purpose")
                parent_packet = parent.score_requests(state, requests, selection_purpose=purpose)
                candidate_packet = candidate.score_requests(state, requests, selection_purpose=purpose)
                parent_rows = {row["candidate_id"]: row for row in parent_packet["scores"]}
                candidate_rows = {row["candidate_id"]: row for row in candidate_packet["scores"]}
                require(parent_rows.keys() == candidate_rows.keys(), f"Candidate space differs: {decision_id}")
                space = enumerate_candidates(state)
                require(space.get("representation") != "ordered_selection_implicit_v1",
                        "Event choice unexpectedly uses implicit candidates")
                candidate_by_id = {row["candidate_id"]: row for row in space["candidates"]}
                counts["event_decisions"] += 1
                before_greedy = greedy(parent_packet["scores"])
                after_greedy = greedy(candidate_packet["scores"])
                changed = before_greedy != after_greedy
                counts["greedy_changed_decisions"] += int(changed)
                applied_in_decision = 0
                for candidate_id, after in candidate_rows.items():
                    before = parent_rows[candidate_id]
                    adjustment = after.get("event_outcome_adjustment")
                    require(type(adjustment) in (int, float) and math.isfinite(adjustment),
                            "Event outcome adjustment missing")
                    error = abs(after["score"] - (before["score"] + adjustment))
                    maximum_additivity_error = max(maximum_additivity_error, error)
                    require(error <= 1e-12, f"Event outcome wrapper is not additive: {decision_id}")
                    detail = after.get("event_outcome_detail") or {}
                    if not detail.get("applied"):
                        continue
                    applied_in_decision += 1
                    key = detail["identity"]
                    counts["applied_rows"] += 1
                    counts["probability_markers_removed"] += int(
                        MARKER in set(before.get("missing") or [])
                        and MARKER not in set(after.get("missing") or []))
                    option_counts[key]["rows"] += 1
                    option_counts[key]["greedy_before"] += int(candidate_id in before_greedy)
                    option_counts[key]["greedy_after"] += int(candidate_id in after_greedy)
                    option_counts[key]["changed_decision_rows"] += int(changed)
                    option_counts[key]["near_target_rows"] += int(run["category"] == "near_target_failure")
                    score_stats[key].append({
                        "parent": before["score"],
                        "candidate": after["score"],
                        "adjustment": adjustment,
                    })
                counts["applied_decisions"] += int(applied_in_decision > 0)
                if changed and len(changed_examples) < 40:
                    changed_examples.append({
                        "run_id": run_id,
                        "category": run["category"],
                        "decision_id": decision_id,
                        "act": (state.get("context") or {}).get("act"),
                        "floor": (state.get("context") or {}).get("floor"),
                        "greedy_before": sorted(before_greedy),
                        "greedy_after": sorted(after_greedy),
                        "options": {
                            candidate_id: identity(candidate_by_id[candidate_id])
                            for candidate_id in candidate_rows
                        },
                    })
            request = recorded.get("request") or {}
            observe_recorded_action(parent, state, request, parent_size)
            observe_recorded_action(candidate, state, request, candidate_size)

    require(counts["event_decisions"] == manifest["counts"]["event_decisions"],
            "Frozen event decision count differs")
    require(counts["applied_rows"] == 105, "Expected 105 source-bound deterministic option rows")
    require(counts["probability_markers_removed"] == counts["applied_rows"],
            "A deterministic option retained its generic probability marker")
    summaries = {}
    for key, values in sorted(score_stats.items()):
        adjustments = [row["adjustment"] for row in values]
        summaries[key] = {
            **dict(option_counts[key]),
            "adjustment_min": min(adjustments),
            "adjustment_max": max(adjustments),
            "adjustment_mean": sum(adjustments) / len(adjustments),
        }
    return {
        "schema_version": "deterministic-event-outcome-offline-replay-v1",
        "passed": True,
        "interpretation": {
            "policy_weights_fitted": False,
            "natural_outcomes_used_for_weight_selection": False,
            "random_event_outcomes_resolved": False,
            "automatic_deployment": False,
            "live_evaluation_modified": False,
        },
        "counts": dict(counts),
        "maximum_additivity_error": maximum_additivity_error,
        "options": summaries,
        "changed_examples": changed_examples,
        "sources": {
            "gap_manifest": file_evidence(manifest_path),
            "candidate_model": file_evidence(model_path),
            "parent_model": file_evidence(parent_path),
            "replay_source": file_evidence(Path(__file__).resolve()),
            "runs": run_evidence,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = replay(args.manifest, args.model)
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                                      allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "passed": result["passed"],
        "counts": result["counts"],
        "maximum_additivity_error": result["maximum_additivity_error"],
        "options": result["options"],
        "changed_examples": result["changed_examples"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
