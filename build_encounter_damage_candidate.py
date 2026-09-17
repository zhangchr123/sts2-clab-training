"""Assemble the source-closed encounter-damage candidate and exact replay receipt."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from build_full_route_candidate import migrate_parent_chain, require, write_new
from decision_data import state_hash
from encounter_damage_policy import EncounterDamagePolicy, make_artifact
import full_route_features
from full_route_policy import FullRoutePolicy
from public_route_learning import policy_input as public_route_input
from run_metadata import file_evidence


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


def sha256_json(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def assemble(historical_selection_path, full_route_offline_path,
             damage_offline_path, catalog_path, models):
    selection_path, full_route_path, migration = migrate_parent_chain(
        historical_selection_path, full_route_offline_path, models
    )
    full_artifact = read(full_route_path)
    solver_config = full_artifact["solver_requested_config"]
    damage_path = Path(models).resolve() / "encounter-damage-candidate-model.json"
    damage = make_artifact(
        full_route_path,
        catalog_path,
        solver_config,
        training={
            "purpose": "public known-node route damage burden candidate",
            "catalog_fit": file_evidence(catalog_path),
            "offline_replay_result": file_evidence(damage_offline_path),
            "policy_weights_fitted": False,
            "natural_outcomes_used_for_policy_weight_selection": False,
            "catalog_test_used_for_selection": False,
            "automatic_deployment": False,
        },
    )
    write_new(damage_path, damage)
    FullRoutePolicy(full_route_path, solver_config=solver_config,
                    seed="migration", epsilon=0.0)
    EncounterDamagePolicy(damage_path, solver_config=solver_config,
                          seed="migration", epsilon=0.0)
    migration.update(
        encounter_damage_catalog=file_evidence(catalog_path),
        encounter_damage_candidate=file_evidence(damage_path),
        encounter_damage_constructor_validated=True,
    )
    return full_route_path, damage_path, solver_config, migration


def verify_replay(full_route_path, damage_path, solver_config, offline_path):
    offline = read(offline_path)
    require(
        offline.get("schema_version") == "encounter-damage-fixed-prior-offline-replay-v1"
        and offline.get("passed") is True,
        "Offline encounter-damage replay differs",
    )
    interpretation = offline.get("interpretation") or {}
    require(
        interpretation.get("policy_parameters_fitted") is False
        and interpretation.get("natural_outcomes_used_for_policy_weight_selection") is False
        and interpretation.get("catalog_test_used_for_parameter_selection") is False
        and interpretation.get("automatic_deployment") is False,
        "Offline encounter-damage selection contract differs",
    )
    source_rows = offline.get("sources", {}).get("decision_and_policy_files") or []
    require(source_rows and len(source_rows) % 2 == 0,
            "Offline encounter-damage source closure is incomplete")
    source_by_path = {Path(row["path"]).resolve(): row for row in source_rows}
    require(len(source_by_path) == len(source_rows),
            "Offline encounter-damage sources are duplicated")
    for path, expected in source_by_path.items():
        require(file_evidence(path) == expected,
                f"Offline encounter-damage source differs: {path}")

    parent = FullRoutePolicy(full_route_path, solver_config=solver_config,
                             seed="assembled-replay", epsilon=0.0)
    candidate = EncounterDamagePolicy(damage_path, solver_config=solver_config,
                                      seed="assembled-replay", epsilon=0.0)
    run_dirs = sorted({path.parent for path in source_by_path})
    decisions = score_rows = exact_additivity = recorded_parent_exact = 0
    max_additivity_error = max_recorded_parent_error = 0.0
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
            observation = recorded["map_observation"]
            route_value = public_route_input(state, observation)
            full_value = full_route_features.policy_input(state, observation)
            parent.set_public_route_input(state, route_value)
            parent.set_full_route_input(state, full_value)
            candidate.set_public_route_input(state, route_value)
            candidate.set_full_route_input(state, full_value)
            damage_value = candidate.make_encounter_damage_input(state, observation)
            candidate.set_encounter_damage_input(state, damage_value)
            purpose = scoring.get("selection_purpose")
            parent_packet = parent.score_requests(
                state, requests, selection_purpose=purpose
            )
            candidate_packet = candidate.score_requests(
                state, requests, selection_purpose=purpose
            )
            recorded_full_parent = full_route_features.adjust(
                state, scoring, full_value
            )
            parent_rows = {row["candidate_id"]: row for row in parent_packet["scores"]}
            candidate_rows = {
                row["candidate_id"]: row for row in candidate_packet["scores"]
            }
            recorded_rows = {
                row["candidate_id"]: row for row in recorded_full_parent["scores"]
            }
            require(parent_rows.keys() == candidate_rows.keys() == recorded_rows.keys(),
                    f"Assembled encounter-damage candidates differ: {decision_id}")
            decision_additive = decision_recorded = True
            for candidate_id, candidate_row in candidate_rows.items():
                parent_row = parent_rows[candidate_id]
                recorded_row = recorded_rows[candidate_id]
                adjustment = candidate_row.get("encounter_damage_adjustment")
                require(type(adjustment) in (int, float),
                        "Encounter-damage adjustment missing")
                additive_error = abs(
                    candidate_row["score"] - (parent_row["score"] + adjustment)
                )
                recorded_error = abs(parent_row["score"] - recorded_row["score"])
                max_additivity_error = max(max_additivity_error, additive_error)
                max_recorded_parent_error = max(max_recorded_parent_error, recorded_error)
                decision_additive &= additive_error <= 1e-12
                decision_recorded &= recorded_error <= 1e-12
                score_rows += 1
            require(decision_additive,
                    f"Encounter-damage wrapper is not additive: {decision_id}")
            require(decision_recorded,
                    f"Migrated full-route parent differs: {decision_id}")
            exact_additivity += 1
            recorded_parent_exact += 1
            decisions += 1

    expected = offline["counts"]
    require(decisions == expected["map_decisions"],
            "Encounter-damage replay decision count differs")
    require(score_rows == expected["candidate_rows"],
            "Encounter-damage replay row count differs")
    result = {
        "schema_version": "encounter-damage-assembled-replay-v1",
        "passed": True,
        "decisions": decisions,
        "candidate_rows": score_rows,
        "exact_parent_additivity": exact_additivity,
        "recorded_full_route_parent_exact": recorded_parent_exact,
        "maximum_additivity_error": max_additivity_error,
        "maximum_recorded_parent_error": max_recorded_parent_error,
        "natural_outcomes_used_for_policy_weight_selection": False,
        "catalog_test_used_for_parameter_selection": False,
        "offline_replay": file_evidence(offline_path),
        "full_route_parent": file_evidence(full_route_path),
        "encounter_damage_candidate": file_evidence(damage_path),
    }
    result["combined_replay_sha256"] = sha256_json(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--historical-selection-model", type=Path, required=True)
    parser.add_argument("--full-route-offline", type=Path, required=True)
    parser.add_argument("--damage-offline", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    full_route_path, damage_path, solver_config, migration = assemble(
        args.historical_selection_model,
        args.full_route_offline,
        args.damage_offline,
        args.catalog,
        args.models,
    )
    result = verify_replay(
        full_route_path, damage_path, solver_config, args.damage_offline
    )
    result["migration"] = migration
    write_new(args.receipt, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
