"""Build and self-verify the isolated Future of Potions event candidate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from event_outcome_policy import EventOutcomePolicy, make_artifact
from run_metadata import file_evidence


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--config-from", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    config = read(args.config_from.resolve())["solver_requested_config"]
    training = {
        "purpose": (
            "current-engine event outcomes for Bugslayer, Self Help Book, "
            "public-resolved This Or That, and the source-bound public "
            "Future of Potions reward distribution"
        ),
        "future_potions_public_reward_pool_cards": 86,
        "future_potions_bridge_option_variables_validated": True,
        "future_potions_bridge_full_regression_terminations": 25,
        "policy_weights_fitted": False,
        "natural_outcomes_used_for_policy_weight_selection": False,
        "other_random_event_outcomes_resolved": False,
        "automatic_deployment": False,
    }
    artifact = make_artifact(args.parent, config, training=training)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(artifact, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")

    # Loading performs the full artifact/source/parent closure validation.
    policy = EventOutcomePolicy(output, solver_config=config, seed="artifact-self-check", epsilon=0.0)
    print(json.dumps({
        "candidate": file_evidence(output),
        "parent": artifact["parent_model"],
        "policy_id": policy.provenance["id"],
        "contract": artifact["event_outcome_contract"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
