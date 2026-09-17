"""Assemble the source-closed reward-mechanism candidate and replay receipt."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_encounter_damage_candidate import (
    assemble as assemble_encounter_damage,
    completed_states,
    read,
    read_jsonl,
    sha256_json,
)
from build_full_route_candidate import require, write_new
from decision_data import enumerate_candidates
import deck_discipline
from encounter_damage_policy import EncounterDamagePolicy
import reward_mechanism_features
from reward_mechanism_policy import RewardMechanismPolicy, make_artifact
from run_metadata import file_evidence


def assemble(historical_selection_path, full_route_offline_path,
             damage_offline_path, catalog_path, reward_offline_path, models):
    _, damage_path, solver_config, migration = assemble_encounter_damage(
        historical_selection_path,
        full_route_offline_path,
        damage_offline_path,
        catalog_path,
        models,
    )
    reward_path = Path(models).resolve() / "reward-mechanism-candidate-model.json"
    reward = make_artifact(
        damage_path,
        solver_config,
        training={
            "purpose": "current-engine description-bound reward semantics candidate",
            "offline_replay_result": file_evidence(reward_offline_path),
            "policy_weights_fitted": False,
            "natural_outcomes_used_for_policy_weight_selection": False,
            "future_condition_probabilities_assumed": False,
            "automatic_deployment": False,
        },
    )
    write_new(reward_path, reward)
    EncounterDamagePolicy(damage_path, solver_config=solver_config,
                          seed="migration", epsilon=0.0)
    RewardMechanismPolicy(reward_path, solver_config=solver_config,
                          seed="migration", epsilon=0.0)
    migration.update(
        reward_mechanism_candidate=file_evidence(reward_path),
        reward_mechanism_constructor_validated=True,
    )
    return damage_path, reward_path, solver_config, migration


def advance_recorded_run_state(policy, state):
    """Apply the public-state half of the compact-deck latch used by choose()."""
    size = deck_discipline.deck_size(state)
    policy._special_builds.update(deck_discipline.visible_special_builds(state))
    if policy._pending_mirror_size is not None:
        if size >= policy._pending_mirror_size * 2:
            policy._special_builds.add("REFLECTIONS_SHATTER")
        policy._pending_mirror_size = None
    return size


def observe_recorded_action(policy, state, request, size):
    """Replay only the historical action needed by the Reflections latch."""
    if request.get("action") != "choose_option":
        return
    space = enumerate_candidates(state)
    require(space.get("representation") != "ordered_selection_implicit_v1",
            "Event choice unexpectedly uses implicit candidates")
    chosen = next(
        (candidate for candidate in space["candidates"]
         if candidate["request"] == request),
        None,
    )
    require(chosen is not None, "Recorded event choice is no longer legal")
    if chosen["evidence"].get("text_key") == deck_discipline.MIRROR:
        policy._pending_mirror_size = size


def verify_replay(damage_path, reward_path, solver_config, offline_path):
    offline = read(offline_path)
    require(
        offline.get("schema_version") == "reward-mechanism-fixed-prior-offline-replay-v1"
        and offline.get("passed") is True,
        "Offline reward-mechanism replay differs",
    )
    interpretation = offline.get("interpretation") or {}
    require(
        interpretation.get("policy_weights_fitted") is False
        and interpretation.get("natural_outcomes_used_for_weight_selection") is False
        and interpretation.get("automatic_deployment") is False,
        "Offline reward-mechanism selection contract differs",
    )
    require(
        offline.get("contract") == reward_mechanism_features.FEATURE_CONTRACT
        and offline.get("parameters") == reward_mechanism_features.PRIOR,
        "Offline reward-mechanism feature contract differs",
    )
    sources = offline.get("sources") or {}
    source_rows = sources.get("decision_and_policy_files") or []
    require(source_rows and len(source_rows) % 2 == 0,
            "Offline reward-mechanism source closure is incomplete")
    source_by_path = {Path(row["path"]).resolve(): row for row in source_rows}
    require(len(source_by_path) == len(source_rows),
            "Offline reward-mechanism sources are duplicated")
    for path, expected in source_by_path.items():
        require(file_evidence(path) == expected,
                f"Offline reward-mechanism source differs: {path}")
    for key in ("facts_source", "feature_source", "card_table", "replay_source"):
        expected = sources.get(key) or {}
        path = expected.get("path")
        require(isinstance(path, str) and file_evidence(path) == expected,
                f"Offline reward-mechanism {key} differs")

    run_dirs = sorted({path.parent for path in source_by_path})
    decisions = score_rows = exact_additivity = recorded_parent_exact = 0
    max_additivity_error = max_recorded_parent_error = 0.0
    for run_dir in run_dirs:
        parent = EncounterDamagePolicy(damage_path, solver_config=solver_config,
                                       seed=run_dir.name, epsilon=0.0)
        candidate = RewardMechanismPolicy(reward_path, solver_config=solver_config,
                                          seed=run_dir.name, epsilon=0.0)
        decision_path = run_dir / "decisions.jsonl"
        policy_path = run_dir / "policy.jsonl"
        require(decision_path in source_by_path and policy_path in source_by_path,
                f"Run source pair is incomplete: {run_dir}")
        states = completed_states(decision_path)
        for recorded in read_jsonl(policy_path):
            decision_id = recorded["decision_id"]
            state = states.get(decision_id)
            require(isinstance(state, dict),
                    f"Recorded decision has no completed state: {decision_id}")
            parent_size = advance_recorded_run_state(parent, state)
            candidate_size = advance_recorded_run_state(candidate, state)
            require(parent_size == candidate_size,
                    "Parent and candidate public deck size differ")
            scoring = recorded.get("scoring") or {}
            recorded_rows_list = scoring.get("scores") or []
            if any((row.get("request") or {}).get("action") == "select_card_reward"
                   for row in recorded_rows_list):
                require(state.get("decision") == "card_reward",
                        f"Reward state differs: {decision_id}")
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
                    row["candidate_id"]: row for row in candidate_packet["scores"]
                }
                recorded_rows = {
                    row["candidate_id"]: row for row in recorded_rows_list
                }
                require(parent_rows.keys() == candidate_rows.keys() == recorded_rows.keys(),
                        f"Assembled reward-mechanism candidates differ: {decision_id}")
                decision_additive = decision_recorded = True
                for candidate_id, candidate_row in candidate_rows.items():
                    parent_row = parent_rows[candidate_id]
                    recorded_row = recorded_rows[candidate_id]
                    adjustment = candidate_row.get("reward_mechanism_adjustment")
                    require(type(adjustment) in (int, float),
                            "Reward-mechanism adjustment missing")
                    additive_error = abs(
                        candidate_row["score"] - (parent_row["score"] + adjustment)
                    )
                    recorded_error = abs(parent_row["score"] - recorded_row["score"])
                    max_additivity_error = max(max_additivity_error, additive_error)
                    max_recorded_parent_error = max(
                        max_recorded_parent_error, recorded_error
                    )
                    decision_additive &= additive_error <= 1e-12
                    decision_recorded &= recorded_error <= 1e-12
                    score_rows += 1
                require(decision_additive,
                        f"Reward-mechanism wrapper is not additive: {decision_id}")
                require(decision_recorded,
                        f"Migrated encounter parent differs: {decision_id}")
                exact_additivity += 1
                recorded_parent_exact += 1
                decisions += 1
            request = recorded.get("request") or {}
            observe_recorded_action(parent, state, request, parent_size)
            observe_recorded_action(candidate, state, request, candidate_size)

    expected = offline["counts"]
    require(decisions == expected["reward_decisions"],
            "Reward-mechanism replay decision count differs")
    require(score_rows == expected["candidate_rows"],
            "Reward-mechanism replay row count differs")
    result = {
        "schema_version": "reward-mechanism-assembled-replay-v1",
        "passed": True,
        "decisions": decisions,
        "candidate_rows": score_rows,
        "exact_parent_additivity": exact_additivity,
        "recorded_encounter_parent_exact": recorded_parent_exact,
        "maximum_additivity_error": max_additivity_error,
        "maximum_recorded_parent_error": max_recorded_parent_error,
        "policy_weights_fitted": False,
        "natural_outcomes_used_for_policy_weight_selection": False,
        "future_condition_probabilities_assumed": False,
        "offline_replay": file_evidence(offline_path),
        "encounter_damage_parent": file_evidence(damage_path),
        "reward_mechanism_candidate": file_evidence(reward_path),
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
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    damage_path, reward_path, solver_config, migration = assemble(
        args.historical_selection_model,
        args.full_route_offline,
        args.damage_offline,
        args.catalog,
        args.reward_offline,
        args.models,
    )
    result = verify_replay(
        damage_path, reward_path, solver_config, args.reward_offline
    )
    result["migration"] = migration
    write_new(args.receipt, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
