"""Rebind the validated event parent and assemble the selection-effect wrapper.

The migration changes source paths and hashes only.  It preserves all learned
parent parameters and both fixed priors, then verifies actual wrapper additivity
on every audited upgrade decision before writing a replay receipt.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from decision_data import DataContractError
from event_effect_policy import EventEffectPolicy, make_artifact as make_event_artifact
from persistent_acquisition_policy import (
    PersistentAcquisitionPolicy,
    make_artifact as make_persistent_artifact,
)
from replay_selection_effect_candidate import jsonl_map
from run_metadata import file_evidence
from selection_effect_policy import SelectionEffectPolicy, make_artifact as make_selection_artifact


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DataContractError(message)


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"Refusing to overwrite assembled artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def migrate_parent_chain(
    historical_event_path: Path, offline_replay_path: Path, models: Path
) -> tuple[Path, Path, Path, dict[str, Any]]:
    historical_event_path = historical_event_path.resolve()
    offline_replay_path = offline_replay_path.resolve()
    historical_event = read(historical_event_path)
    historical_baseline_path = Path(historical_event["parent_model"]["path"]).resolve()
    require(file_evidence(historical_baseline_path) == historical_event["parent_model"],
            "Historical event parent evidence differs")
    historical_baseline = read(historical_baseline_path)
    require(historical_baseline.get("format") == "whole-run-functional-role-acquisition-v1",
            "Historical baseline format differs")
    require(historical_event.get("format") == "whole-run-public-event-effects-v1",
            "Historical event format differs")

    solver_config = historical_event["solver_requested_config"]
    require(historical_baseline.get("solver_requested_config") == solver_config,
            "Historical solver configuration differs across parent chain")

    baseline_path = models / "migrated-baseline-model.json"
    event_path = models / "event-effect-candidate-model.json"
    selection_path = models / "selection-effect-candidate-model.json"
    baseline = make_persistent_artifact(
        historical_baseline["parameters"],
        solver_config,
        training={
            "purpose": "path-only source-closure migration for isolated selection-effect evaluation",
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
            "purpose": "fixed public canonical upgrade-preview utility candidate",
            "weights_fitted": False,
            "natural_outcomes_used_for_weight_selection": False,
            "offline_replay_result": file_evidence(offline_replay_path),
            "automatic_deployment": False,
        },
    )
    write_new(selection_path, selection)

    # Constructors independently recheck complete source closure and parent hashes.
    PersistentAcquisitionPolicy(baseline_path, solver_config=solver_config, seed="migration", epsilon=0.0)
    EventEffectPolicy(event_path, solver_config=solver_config, seed="migration", epsilon=0.0)
    SelectionEffectPolicy(selection_path, solver_config=solver_config, seed="migration", epsilon=0.0)
    migration = {
        "historical_baseline": file_evidence(historical_baseline_path),
        "historical_event": file_evidence(historical_event_path),
        "migrated_baseline": file_evidence(baseline_path),
        "migrated_event": file_evidence(event_path),
        "selection_candidate": file_evidence(selection_path),
        "baseline_parameters_equal": True,
        "event_parameters_equal": True,
        "constructors_validated": True,
    }
    return baseline_path, event_path, selection_path, migration


def verify_replay(
    event_path: Path, selection_path: Path, offline_replay_path: Path
) -> dict[str, Any]:
    offline = read(offline_replay_path)
    require(offline.get("schema_version") == "selection-effect-offline-replay-v1",
            "Offline selection replay schema differs")
    require(offline.get("interpretation", {}).get(
        "natural_outcomes_used_for_fitting_or_weight_selection") is False,
        "Offline replay used outcomes for selection")
    source_rows = offline.get("sources", {}).get("decision_and_policy_files") or []
    require(source_rows and len(source_rows) % 2 == 0, "Offline replay source closure is incomplete")
    source_by_path = {Path(row["path"]).resolve(): row for row in source_rows}
    require(len(source_by_path) == len(source_rows), "Offline replay has duplicate source paths")
    for path, expected in source_by_path.items():
        require(file_evidence(path) == expected, f"Offline replay source differs: {path}")

    run_dirs = sorted({path.parent for path in source_by_path})
    solver_config = read(selection_path)["solver_requested_config"]
    parent = EventEffectPolicy(event_path, solver_config=solver_config, seed="assembled-replay", epsilon=0.0)
    candidate = SelectionEffectPolicy(
        selection_path, solver_config=solver_config, seed="assembled-replay", epsilon=0.0
    )
    decisions = 0
    score_rows = 0
    exact_parent_additivity = 0
    recorded_parent_exact = 0
    maximum_additivity_error = 0.0
    maximum_recorded_parent_error = 0.0
    for run_dir in run_dirs:
        decision_path = run_dir / "decisions.jsonl"
        policy_path = run_dir / "policy.jsonl"
        require(decision_path in source_by_path and policy_path in source_by_path,
                f"Run source pair is incomplete: {run_dir}")
        states = jsonl_map(decision_path, prefer_execution=True)
        policies = jsonl_map(policy_path)
        for decision_id, recorded in policies.items():
            scoring = recorded.get("scoring") or {}
            if scoring.get("selection_purpose") != "upgrade":
                continue
            state = (states.get(decision_id) or {}).get("state") or {}
            require(state.get("decision") == "card_select", "Upgrade replay state differs")
            requests = [row["request"] for row in scoring.get("scores") or []]
            parent_packet = parent.score_requests(state, requests, selection_purpose="upgrade")
            candidate_packet = candidate.score_requests(state, requests, selection_purpose="upgrade")
            parent_rows = {row["candidate_id"]: row for row in parent_packet["scores"]}
            candidate_rows = {row["candidate_id"]: row for row in candidate_packet["scores"]}
            recorded_rows = {row["candidate_id"]: row for row in scoring["scores"]}
            require(parent_rows.keys() == candidate_rows.keys() == recorded_rows.keys(),
                    "Assembled replay candidate ids differ")
            decision_additive = True
            decision_recorded_exact = True
            for candidate_id, candidate_row in candidate_rows.items():
                parent_row = parent_rows[candidate_id]
                recorded_row = recorded_rows[candidate_id]
                adjustment = candidate_row.get("selection_effect_adjustment")
                require(type(adjustment) in (int, float), "Selection adjustment missing")
                error = abs(candidate_row["score"] - (parent_row["score"] + adjustment))
                recorded_error = abs(parent_row["score"] - recorded_row["score"])
                maximum_additivity_error = max(maximum_additivity_error, error)
                maximum_recorded_parent_error = max(maximum_recorded_parent_error, recorded_error)
                decision_additive &= error <= 1e-12
                decision_recorded_exact &= recorded_error <= 1e-12
                score_rows += 1
            require(decision_additive, f"Selection wrapper is not additive: {decision_id}")
            require(decision_recorded_exact, f"Migrated parent differs from recorded score: {decision_id}")
            exact_parent_additivity += int(decision_additive)
            recorded_parent_exact += int(decision_recorded_exact)
            decisions += 1

    require(decisions == offline["all"]["decisions"] == 91, "Upgrade replay decision count differs")
    require(score_rows == offline["all"]["candidate_rows"] == 3604, "Upgrade replay row count differs")
    return {
        "schema_version": "selection-effect-assembled-replay-v1",
        "passed": True,
        "decisions": decisions,
        "candidate_rows": score_rows,
        "exact_parent_additivity": exact_parent_additivity,
        "recorded_parent_exact": recorded_parent_exact,
        "maximum_additivity_error": maximum_additivity_error,
        "maximum_recorded_parent_error": maximum_recorded_parent_error,
        "natural_outcomes_used_for_weight_selection": False,
        "offline_replay": file_evidence(offline_replay_path),
        "event_parent": file_evidence(event_path),
        "selection_candidate": file_evidence(selection_path),
        "combined_replay_sha256": sha256_json({
            "offline": file_evidence(offline_replay_path),
            "event_parent": file_evidence(event_path),
            "selection_candidate": file_evidence(selection_path),
            "decisions": decisions,
            "candidate_rows": score_rows,
            "exact_parent_additivity": exact_parent_additivity,
            "recorded_parent_exact": recorded_parent_exact,
        }),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--historical-event-model", type=Path, required=True)
    parser.add_argument("--offline-replay", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    _, event_path, selection_path, migration = migrate_parent_chain(
        args.historical_event_model, args.offline_replay, args.models
    )
    replay = verify_replay(event_path, selection_path, args.offline_replay)
    replay["migration"] = migration
    write_new(args.receipt, replay)
    print(json.dumps(replay, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
