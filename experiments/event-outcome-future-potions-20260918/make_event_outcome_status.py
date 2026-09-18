"""Verify final evidence and publish a non-deployment candidate status."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from decision_data import DataContractError
from run_metadata import file_evidence


def require(condition, message):
    if not condition:
        raise DataContractError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--bridge-regression", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    model, replay, probe, regression = map(
        read, (args.model, args.replay, args.probe, args.bridge_regression)
    )
    require(replay.get("passed") is True, "Frozen replay did not pass")
    require(replay.get("counts", {}).get("event_decisions") == 667
            and replay["counts"].get("applied_rows") == 105
            and replay["maximum_additivity_error"] == 0.0,
            "Frozen replay counts differ")
    require(probe.get("passed") is True and len(probe.get("rows") or []) == 2,
            "Live Future probe did not pass")
    require(probe["maximum_additivity_error"] == 0.0
            and probe["maximum_all_pool_adjustment"] <= probe["candidate_adjustment_abs_cap"],
            "Live Future probe envelope differs")
    require(regression.get("phase") == "passed" and regression.get("failures") == 0
            and regression.get("completed_characters") == 5
            and sum(row["completed"] for row in regression["results"].values()) == 25,
            "Bridge full-run regression differs")
    require(model.get("automatic_deployment") is False,
            "Candidate unexpectedly enables automatic deployment")

    result = {
        "schema_version": "candidate-publication-v2",
        "status": "validated_not_deployed",
        "candidate": file_evidence(args.model.resolve()),
        "parent": model["parent_model"],
        "frozen_replay": file_evidence(args.replay.resolve()),
        "live_policy_probe": file_evidence(args.probe.resolve()),
        "bridge_full_run_regression": file_evidence(args.bridge_regression.resolve()),
        "behavior": {
            "historical_event_decisions_replayed": 667,
            "historical_source_bound_rows": 105,
            "historical_greedy_changed_decisions": 34,
            "historical_maximum_additivity_error": 0.0,
            "live_future_options_resolved": 2,
            "live_future_greedy_changed": probe["greedy_before"] != probe["greedy_after"],
            "live_future_maximum_all_pool_adjustment": probe["maximum_all_pool_adjustment"],
            "bridge_natural_runs_terminated": 25,
            "bridge_regression_failures": 0,
        },
        "scope": [
            "BUGSLAYER deterministic card acquisition",
            "SELF_HELP_BOOK deterministic source-bound enchantment utility",
            "THIS_OR_THAT PLAIN public-resolved deterministic classification",
            "THE_FUTURE_OF_POTIONS public precommitted exact reward distribution",
        ],
        "limitations": [
            "relative fixed utility, not calibrated win probability",
            "reward pool bound to current headless Defect A10 unlock state",
            "known public card-reward modifying relics fail closed",
            "historical states without option variables remain unresolved",
            "prospective third-act first-boss evaluation not yet run",
        ],
        "prospective_evaluation_run": False,
        "automatic_deployment": False,
        "blocking_gate": (
            "wait for the admitted parent chain and a separately declared "
            "clean prospective evaluation"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
