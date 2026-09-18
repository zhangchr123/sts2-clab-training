"""Build the immutable merchant item wrapper artifact."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from merchant_item_policy import make_artifact


ROOT = Path(__file__).resolve().parent


def atomic(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    parent = json.loads(Path(args.parent).read_text(encoding="utf-8"))
    artifact = make_artifact(
        args.parent,
        parent["solver_requested_config"],
        training={
            "purpose": "source-bound merchant relic, potion purchase, and potion replacement utility",
            "covered_relics": 3,
            "covered_potions": 11,
            "policy_weights_fitted": False,
            "natural_outcomes_used_for_parameter_selection": False,
            "automatic_deployment": False,
        },
    )
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic(output, artifact)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

