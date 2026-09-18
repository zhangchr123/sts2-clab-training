"""Assemble the source-closed rest-heal route candidate and replay receipt."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_encounter_damage_candidate import (
    completed_states,
    read,
    read_jsonl,
    sha256_json,
)
from build_full_route_candidate import require, write_new
from build_reward_mechanism_candidate import (
    advance_recorded_run_state,
    assemble as assemble_reward_mechanism,
    observe_recorded_action,
)
import rest_heal_route_features
from rest_heal_route_policy import RestHealRoutePolicy, make_artifact
from reward_mechanism_policy import RewardMechanismPolicy
from run_metadata import file_evidence


def assemble(historical_selection_path, full_route_offline_path,
             damage_offline_path, catalog_path, reward_offline_path,
             rest_offline_path, models):
    _, reward_path, solver_config, migration = assemble_reward_mechanism(
        historical_selection_path,
        full_route_offline_path,
        damage_offline_path,
        catalog_path,
        reward_offline_path,
        models,
    )
    rest_path = Path(models).resolve() / "rest-heal-route-candidate-model.json"
    artifact = make_artifact(
        reward_path,
        solver_config,
        training={
            "purpose": "exact public rest healing plus latched public route risk candidate",
            "offline_replay_result": file_evidence(rest_offline_path),
            "policy_weights_fitted": False,
            "natural_outcomes_used_for_policy_weight_selection": False,
            "future_route_choice_probabilities_assumed": False,
            "automatic_deployment": False,
        },
    )
    write_new(rest_path, artifact)
    RewardMechanismPolicy(reward_path, solver_config=solver_config,
                          seed="migration", epsilon=0.0)
    RestHealRoutePolicy(rest_path, solver_config=solver_config,
                        seed="migration", epsilon=0.0)
    migration.update(
        rest_heal_route_candidate=file_evidence(rest_path),
        rest_heal_route_constructor_validated=True,
    )
    return reward_path, rest_path, solver_config, migration


def _verify_offline_contract(offline):
    require(
        offline.get("schema_version")
        == "rest-heal-route-fixed-prior-offline-replay-v1"
        and offline.get("passed") is True,
        "Offline rest-heal route replay differs",
    )
    interpretation = offline.get("interpretation") or {}
    require(
        interpretation.get("policy_weights_fitted") is False
        and interpretation.get("natural_outcomes_used_for_weight_selection") is False
        and interpretation.get("automatic_deployment") is False,
        "Offline rest-heal route selection contract differs",
    )
    require(
        offline.get("contract") == rest_heal_route_features.CONTRACT
        and offline.get("parameters") == rest_heal_route_features.PRIOR,
        "Offline rest-heal route feature contract differs",
    )


def _verified_sources(offline):
    sources = offline.get("sources") or {}
    source_rows = sources.get("decision_and_policy_files") or []
    require(source_rows and len(source_rows) % 2 == 0,
            "Offline rest-heal route source closure is incomplete")
    source_by_path = {Path(row["path"]).resolve(): row for row in source_rows}
    require(len(source_by_path) == len(source_rows),
            "Offline rest-heal route sources are duplicated")
    for path, expected in source_by_path.items():
        require(file_evidence(path) == expected,
                f"Offline rest-heal route source differs: {path}")
    for key in ("feature_source", "relic_table", "catalog", "replay_source"):
        expected = sources.get(key) or {}
        path = expected.get("path")
        require(isinstance(path, str) and file_evidence(path) == expected,
                f"Offline rest-heal route {key} differs")
    return source_by_path, sources


def verify_replay(reward_path, rest_path, solver_config, offline_path):
    offline = read(offline_path)
    _verify_offline_contract(offline)
    source_by_path, sources = _verified_sources(offline)

    run_dirs = sorted({path.parent for path in source_by_path})
    decisions = score_rows = exact_additivity = recorded_parent_exact = 0
    map_observations = rest_contexts = 0
    max_additivity_error = max_recorded_parent_error = 0.0
    for run_dir in run_dirs:
        parent = RewardMechanismPolicy(
            reward_path, solver_config=solver_config,
            seed=run_dir.name, epsilon=0.0,
        )
        candidate = RestHealRoutePolicy(
            rest_path, solver_config=solver_config,
            seed=run_dir.name, epsilon=0.0,
        )
        decision_path = run_dir / "decisions.jsonl"
        policy_path = run_dir / "policy.jsonl"
        require(decision_path in source_by_path and policy_path in source_by_path,
                f"Run source pair is incomplete: {run_dir}")
        states = completed_states(decision_path)
        pending_rest_context = None
        for recorded in read_jsonl(policy_path):
            decision_id = recorded["decision_id"]
            state = states.get(decision_id)
            require(isinstance(state, dict),
                    f"Recorded decision has no completed state: {decision_id}")
            parent_size = advance_recorded_run_state(parent, state)
            candidate_size = advance_recorded_run_state(candidate, state)
            require(parent_size == candidate_size,
                    "Parent and candidate public deck size differ")

            observation = recorded.get("map_observation")
            if observation is not None:
                require(state.get("decision") == "map_select",
                        f"Map observation is attached to another decision: {decision_id}")
                candidate.set_rest_route_observation(state, observation)
                pending_rest_context = rest_heal_route_features.make_context(
                    state,
                    observation,
                    recorded.get("request") or {},
                    candidate._encounter_damage_catalog,
                )
                # choose() normally consumes this value.  The assembled replay
                # follows the recorded action instead, so consume it explicitly.
                candidate._rest_map_observation = None
                map_observations += 1

            if state.get("decision") == "rest_site":
                require(pending_rest_context is not None,
                        f"Rest decision lacks its prior public map: {decision_id}")
                candidate.set_rest_route_input(state, pending_rest_context)
                scoring = recorded.get("scoring") or {}
                recorded_rows_list = scoring.get("scores") or []
                require(recorded_rows_list,
                        f"Rest decision lacks recorded scores: {decision_id}")
                requests = [row["request"] for row in recorded_rows_list]
                purpose = scoring.get("selection_purpose")
                parent_packet = parent.score_requests(
                    state, requests, selection_purpose=purpose
                )
                candidate_packet = candidate.score_requests(
                    state, requests, selection_purpose=purpose
                )
                parent_rows = {
                    row["candidate_id"]: row for row in parent_packet["scores"]
                }
                candidate_rows = {
                    row["candidate_id"]: row
                    for row in candidate_packet["scores"]
                }
                recorded_rows = {
                    row["candidate_id"]: row for row in recorded_rows_list
                }
                require(parent_rows.keys() == candidate_rows.keys()
                        == recorded_rows.keys(),
                        f"Assembled rest candidates differ: {decision_id}")
                decision_additive = decision_recorded = True
                for candidate_id, candidate_row in candidate_rows.items():
                    parent_row = parent_rows[candidate_id]
                    recorded_row = recorded_rows[candidate_id]
                    adjustment = candidate_row.get("rest_heal_route_adjustment")
                    require(type(adjustment) in (int, float),
                            "Rest-heal route adjustment missing")
                    additive_error = abs(
                        candidate_row["score"]
                        - (parent_row["score"] + adjustment)
                    )
                    recorded_error = abs(
                        parent_row["score"] - recorded_row["score"]
                    )
                    max_additivity_error = max(
                        max_additivity_error, additive_error
                    )
                    max_recorded_parent_error = max(
                        max_recorded_parent_error, recorded_error
                    )
                    decision_additive &= additive_error <= 1e-12
                    decision_recorded &= recorded_error <= 1e-12
                    score_rows += 1
                require(decision_additive,
                        f"Rest-heal route wrapper is not additive: {decision_id}")
                require(decision_recorded,
                        f"Migrated reward parent differs: {decision_id}")
                require(candidate_packet.get("rest_heal_route_applied") is True,
                        f"Rest-heal route context was not applied: {decision_id}")
                exact_additivity += 1
                recorded_parent_exact += 1
                rest_contexts += 1
                decisions += 1
                candidate.set_rest_route_input(state, None)
                pending_rest_context = None

            request = recorded.get("request") or {}
            observe_recorded_action(parent, state, request, parent_size)
            observe_recorded_action(candidate, state, request, candidate_size)

    expected = offline["counts"]
    require(decisions == expected["rest_decisions"],
            "Rest-heal route replay decision count differs")
    require(score_rows == expected["candidate_rows"],
            "Rest-heal route replay row count differs")
    require(rest_contexts == decisions,
            "Rest-heal route public map latch coverage differs")
    result = {
        "schema_version": "rest-heal-route-assembled-replay-v1",
        "passed": True,
        "decisions": decisions,
        "candidate_rows": score_rows,
        "map_observations_replayed": map_observations,
        "rest_contexts_replayed": rest_contexts,
        "exact_parent_additivity": exact_additivity,
        "recorded_reward_parent_exact": recorded_parent_exact,
        "maximum_additivity_error": max_additivity_error,
        "maximum_recorded_parent_error": max_recorded_parent_error,
        "policy_weights_fitted": False,
        "natural_outcomes_used_for_policy_weight_selection": False,
        "future_route_choice_probabilities_assumed": False,
        "automatic_deployment": False,
        "offline_replay": file_evidence(offline_path),
        "offline_catalog": sources["catalog"],
        "reward_mechanism_parent": file_evidence(reward_path),
        "rest_heal_route_candidate": file_evidence(rest_path),
    }
    result["combined_replay_sha256"] = sha256_json(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--historical-selection-model", type=Path, required=True)
    parser.add_argument("--full-route-offline", type=Path, required=True)
    parser.add_argument("--damage-offline", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--reward-offline", type=Path, required=True)
    parser.add_argument("--rest-offline", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    reward_path, rest_path, solver_config, migration = assemble(
        args.historical_selection_model,
        args.full_route_offline,
        args.damage_offline,
        args.catalog,
        args.reward_offline,
        args.rest_offline,
        args.models,
    )
    result = verify_replay(
        reward_path, rest_path, solver_config, args.rest_offline
    )
    result["migration"] = migration
    write_new(args.receipt, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
