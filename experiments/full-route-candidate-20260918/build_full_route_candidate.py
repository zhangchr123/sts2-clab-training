"""Migrate the selected parent chain and assemble the full-route candidate."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path

from decision_data import DataContractError, state_hash
from event_effect_policy import EventEffectPolicy, make_artifact as make_event_artifact
import full_route_features
from full_route_policy import FullRoutePolicy, make_artifact as make_full_route_artifact
from persistent_acquisition_policy import (
    PersistentAcquisitionPolicy,
    make_artifact as make_persistent_artifact,
)
from public_route_learning import policy_input as public_route_input
from run_metadata import file_evidence
from selection_effect_policy import SelectionEffectPolicy, make_artifact as make_selection_artifact


def require(condition, message):
    if not condition:
        raise DataContractError(message)


def read(path):
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


def write_new(path, value):
    path = Path(path).resolve()
    require(not path.exists(), f"Refusing to overwrite assembled artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                         encoding="utf-8")
    os.replace(temporary, path)


def sha256_json(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def migrate_parent_chain(historical_selection_path, offline_replay_path, models):
    historical_selection_path = Path(historical_selection_path).resolve()
    offline_replay_path = Path(offline_replay_path).resolve()
    models = Path(models).resolve()
    historical_selection = read(historical_selection_path)
    historical_event_path = Path(historical_selection["parent_model"]["path"]).resolve()
    require(file_evidence(historical_event_path) == historical_selection["parent_model"],
            "Historical selection parent evidence differs")
    historical_event = read(historical_event_path)
    historical_baseline_path = Path(historical_event["parent_model"]["path"]).resolve()
    require(file_evidence(historical_baseline_path) == historical_event["parent_model"],
            "Historical event parent evidence differs")
    historical_baseline = read(historical_baseline_path)
    require(historical_baseline.get("format") == "whole-run-functional-role-acquisition-v1",
            "Historical baseline format differs")
    require(historical_event.get("format") == "whole-run-public-event-effects-v1",
            "Historical event format differs")
    require(historical_selection.get("format") == "whole-run-public-selection-effects-v1",
            "Historical selection format differs")
    solver_config = historical_selection["solver_requested_config"]
    require(historical_event["solver_requested_config"] == solver_config
            and historical_baseline["solver_requested_config"] == solver_config,
            "Historical solver configuration differs across parent chain")

    baseline_path = models / "migrated-baseline-model.json"
    event_path = models / "event-effect-candidate-model.json"
    selection_path = models / "selection-effect-candidate-model.json"
    full_route_path = models / "full-route-candidate-model.json"
    baseline = make_persistent_artifact(
        historical_baseline["parameters"],
        solver_config,
        training={
            "purpose": "path-only source-closure migration for isolated full-route evaluation",
            "source_model": file_evidence(historical_baseline_path),
            "weights_fitted": False,
            "parameters_changed": False,
            "natural_outcomes_used": False,
            "automatic_deployment": False,
        },
        noncombat_fruit_juice_enabled=historical_baseline["noncombat_potion_policy"]["enabled"],
        functional_repeat_correction_enabled=historical_baseline[
            "functional_repeat_correction_enabled"
        ],
    )
    require(baseline["parameters"] == historical_baseline["parameters"],
            "Baseline parameter migration differs")
    write_new(baseline_path, baseline)

    event = make_event_artifact(
        baseline_path,
        solver_config,
        training={
            "purpose": "source-closure migration of admitted fixed event-effect parent",
            "source_model": file_evidence(historical_event_path),
            "parameters_changed": False,
            "natural_outcomes_used_for_weight_selection": False,
            "automatic_deployment": False,
        },
    )
    require(event["parameters"] == historical_event["parameters"],
            "Event fixed prior changed during migration")
    write_new(event_path, event)

    selection = make_selection_artifact(
        event_path,
        solver_config,
        training={
            "purpose": "source-closure migration of admitted fixed selection-effect parent",
            "source_model": file_evidence(historical_selection_path),
            "parameters_changed": False,
            "natural_outcomes_used_for_weight_selection": False,
            "automatic_deployment": False,
        },
    )
    require(selection["parameters"] == historical_selection["parameters"],
            "Selection fixed prior changed during migration")
    write_new(selection_path, selection)

    full_route = make_full_route_artifact(
        selection_path,
        solver_config,
        training={
            "purpose": "fixed complete public-route topology utility candidate",
            "weights_fitted": False,
            "natural_outcomes_used_for_weight_selection": False,
            "offline_replay_result": file_evidence(offline_replay_path),
            "automatic_deployment": False,
        },
    )
    write_new(full_route_path, full_route)

    PersistentAcquisitionPolicy(baseline_path, solver_config=solver_config,
                                seed="migration", epsilon=0.0)
    EventEffectPolicy(event_path, solver_config=solver_config, seed="migration", epsilon=0.0)
    SelectionEffectPolicy(selection_path, solver_config=solver_config,
                          seed="migration", epsilon=0.0)
    FullRoutePolicy(full_route_path, solver_config=solver_config, seed="migration", epsilon=0.0)
    migration = {
        "historical_baseline": file_evidence(historical_baseline_path),
        "historical_event": file_evidence(historical_event_path),
        "historical_selection": file_evidence(historical_selection_path),
        "migrated_baseline": file_evidence(baseline_path),
        "migrated_event": file_evidence(event_path),
        "migrated_selection": file_evidence(selection_path),
        "full_route_candidate": file_evidence(full_route_path),
        "baseline_parameters_equal": True,
        "event_parameters_equal": True,
        "selection_parameters_equal": True,
        "constructors_validated": True,
    }
    return selection_path, full_route_path, migration


def verify_replay(selection_path, full_route_path, offline_replay_path):
    offline = read(offline_replay_path)
    require(offline.get("schema_version") == "full-route-fixed-prior-offline-replay-v1"
            and offline.get("passed") is True, "Offline full-route replay differs")
    require(offline.get("interpretation", {}).get(
        "natural_outcomes_used_for_fitting_or_weight_selection") is False,
        "Offline full-route replay used outcomes for selection")
    source_rows = offline.get("sources", {}).get("decision_and_policy_files") or []
    require(source_rows and len(source_rows) % 2 == 0,
            "Offline full-route source closure is incomplete")
    source_by_path = {Path(row["path"]).resolve(): row for row in source_rows}
    require(len(source_by_path) == len(source_rows), "Offline full-route sources are duplicated")
    for path, expected in source_by_path.items():
        require(file_evidence(path) == expected, f"Offline full-route source differs: {path}")

    solver_config = read(full_route_path)["solver_requested_config"]
    parent = SelectionEffectPolicy(selection_path, solver_config=solver_config,
                                   seed="assembled-replay", epsilon=0.0)
    candidate = FullRoutePolicy(full_route_path, solver_config=solver_config,
                                seed="assembled-replay", epsilon=0.0)
    run_dirs = sorted({path.parent for path in source_by_path})
    decisions = score_rows = exact_additivity = recorded_parent_exact = 0
    maximum_additivity_error = maximum_recorded_parent_error = 0.0
    for run_dir in run_dirs:
        decision_path = run_dir / "decisions.jsonl"
        policy_path = run_dir / "policy.jsonl"
        require(decision_path in source_by_path and policy_path in source_by_path,
                f"Run source pair is incomplete: {run_dir}")
        states = completed_states(decision_path)
        for recorded in read_jsonl(policy_path):
            if recorded.get("map_observation") is None:
                continue
            decision_id = recorded["decision_id"]
            state = states[decision_id]
            scoring = recorded["scoring"]
            requests = [row["request"] for row in scoring["scores"]]
            route_value = public_route_input(state, recorded["map_observation"])
            full_value = full_route_features.policy_input(state, recorded["map_observation"])
            parent.set_public_route_input(state, route_value)
            candidate.set_public_route_input(state, route_value)
            candidate.set_full_route_input(state, full_value)
            purpose = scoring.get("selection_purpose")
            parent_packet = parent.score_requests(state, requests, selection_purpose=purpose)
            candidate_packet = candidate.score_requests(state, requests, selection_purpose=purpose)
            parent_rows = {row["candidate_id"]: row for row in parent_packet["scores"]}
            candidate_rows = {row["candidate_id"]: row for row in candidate_packet["scores"]}
            recorded_rows = {row["candidate_id"]: row for row in scoring["scores"]}
            require(parent_rows.keys() == candidate_rows.keys() == recorded_rows.keys(),
                    f"Assembled full-route candidates differ: {decision_id}")
            decision_additive = decision_recorded = True
            for candidate_id, candidate_row in candidate_rows.items():
                parent_row = parent_rows[candidate_id]
                recorded_row = recorded_rows[candidate_id]
                adjustment = candidate_row.get("full_route_adjustment")
                require(type(adjustment) in (int, float), "Full-route adjustment missing")
                additive_error = abs(candidate_row["score"] - (parent_row["score"] + adjustment))
                recorded_error = abs(parent_row["score"] - recorded_row["score"])
                maximum_additivity_error = max(maximum_additivity_error, additive_error)
                maximum_recorded_parent_error = max(maximum_recorded_parent_error, recorded_error)
                decision_additive &= additive_error <= 1e-12
                decision_recorded &= recorded_error <= 1e-12
                score_rows += 1
            require(decision_additive, f"Full-route wrapper is not additive: {decision_id}")
            require(decision_recorded, f"Migrated parent differs from recorded score: {decision_id}")
            exact_additivity += 1
            recorded_parent_exact += 1
            decisions += 1

    expected = offline["counts"]
    require(decisions == expected["map_decisions"], "Full-route replay decision count differs")
    require(score_rows == expected["candidate_rows"], "Full-route replay row count differs")
    result = {
        "schema_version": "full-route-assembled-replay-v1",
        "passed": True,
        "decisions": decisions,
        "candidate_rows": score_rows,
        "exact_parent_additivity": exact_additivity,
        "recorded_parent_exact": recorded_parent_exact,
        "maximum_additivity_error": maximum_additivity_error,
        "maximum_recorded_parent_error": maximum_recorded_parent_error,
        "natural_outcomes_used_for_weight_selection": False,
        "offline_replay": file_evidence(offline_replay_path),
        "selection_parent": file_evidence(selection_path),
        "full_route_candidate": file_evidence(full_route_path),
    }
    result["combined_replay_sha256"] = sha256_json(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--historical-selection-model", type=Path, required=True)
    parser.add_argument("--offline-replay", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    selection_path, full_route_path, migration = migrate_parent_chain(
        args.historical_selection_model, args.offline_replay, args.models
    )
    replay = verify_replay(selection_path, full_route_path, args.offline_replay)
    replay["migration"] = migration
    write_new(args.receipt, replay)
    print(json.dumps(replay, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
