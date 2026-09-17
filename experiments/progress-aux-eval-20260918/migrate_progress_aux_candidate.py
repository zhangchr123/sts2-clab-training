"""Bind the admitted 438-parameter progress-auxiliary fit to the 471 runtime.

This is a schema migration, not a deployment.  It refuses to write a candidate
unless the cloud runtime's first 438 parameters exactly equal the frozen source
model and its remaining 33 parameters remain untouched.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def evidence(path: Path):
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def atomic(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def migrate(current, baseline, learned, sources):
    old_names = baseline["parameter_names"]
    current_names = current["parameter_names"]
    learned_names = learned["parameter_names"]
    require(len(old_names) == 438 and len(current_names) == 471, "Unexpected model dimensions")
    require(learned_names == old_names, "Learned model schema differs from frozen 438 baseline")
    require(current_names[:438] == old_names, "Cloud runtime does not preserve the 438-prefix schema")
    role_names = current_names[438:]
    require(len(role_names) == 33 and len(set(current_names)) == 471, "Cloud role extension differs")
    require(set(current["parameters"]) == set(current_names), "Current parameter mapping differs")
    require(set(baseline["parameters"]) == set(old_names), "Baseline parameter mapping differs")
    require(set(learned["parameters"]) == set(old_names), "Learned parameter mapping differs")
    require(
        all(current["parameters"][name] == baseline["parameters"][name] for name in old_names),
        "Cloud 438 prefix is not the frozen fit baseline",
    )
    require(all(math.isfinite(float(learned["parameters"][name])) for name in old_names), "Non-finite learned value")

    candidate = copy.deepcopy(current)
    for name in old_names:
        candidate["parameters"][name] = learned["parameters"][name]
    candidate["automatic_deployment"] = False
    candidate["first_boss_success_verified"] = False
    candidate["training"] = copy.deepcopy(learned.get("training", {}))
    candidate["training"].update(
        {
            "runtime_schema_migration": "438-prefix-to-471-functional-zero-extension-v1",
            "runtime_control_model": sources["current"],
            "frozen_438_baseline": sources["baseline"],
            "fitted_438_candidate": sources["learned"],
            "natural_evaluation_used_for_migration": False,
            "automatic_deployment": False,
        }
    )
    candidate["migration"] = {
        "version": "progress-auxiliary-438-to-functional-471-v1",
        "old_parameter_count": 438,
        "unchanged_extension_count": 33,
        "extension_parameter_names": role_names,
        "extension_values_unchanged": True,
        "natural_outcomes_read": False,
        "production_deployed": False,
    }

    changed = [
        name for name in old_names
        if candidate["parameters"][name] != current["parameters"][name]
    ]
    require(changed, "Learned candidate changes no runtime parameters")
    require(
        all(candidate["parameters"][name] == current["parameters"][name] for name in role_names),
        "Functional extension changed during migration",
    )
    require(candidate["parameter_names"] == current_names, "Runtime parameter order changed")
    return candidate, old_names, role_names, changed


def run(current_path: Path, baseline_path: Path, learned_path: Path, output: Path):
    paths = {"current": current_path, "baseline": baseline_path, "learned": learned_path}
    sources = {name: evidence(path) for name, path in paths.items()}
    candidate, old_names, role_names, changed = migrate(
        read(current_path), read(baseline_path), read(learned_path), sources
    )
    candidate_path = output / "candidate-runtime-model.json"
    atomic(candidate_path, candidate)
    reread = read(candidate_path)
    require(reread == candidate, "Candidate atomic readback differs")
    protocol = {
        "version": "cloud-progress-auxiliary-paired-migration-v1",
        "declared_before_natural_evaluation": True,
        "source_natural_evaluation_games_started": 0,
        "allocation": {"pairs": 60, "games": 120, "same_seed_arms": ["control", "candidate"]},
        "execution_amendment": {
            "reason": "CLab has 4 GiB RAM; serialize the frozen allocation to one engine worker",
            "workers": 1,
            "allocation_and_order_unchanged": True,
            "outcome_dependent_change": False,
        },
        "assessment": "actual Act3 first boss; full A10 victory secondary; invalid retained in denominator",
        "improvement_gate": "strictly more candidate target successes and exact one-sided paired p<=0.05",
        "no_refit_on_evaluation": True,
        "no_sample_extension": True,
        "automatic_retry": False,
        "automatic_deployment": False,
        "sources": sources,
        "candidate": evidence(candidate_path),
    }
    atomic(output / "MIGRATION_PROTOCOL.json", protocol)
    result = {
        "passed": True,
        "old_parameter_count": len(old_names),
        "extension_parameter_count": len(role_names),
        "changed_old_parameters": len(changed),
        "changed_parameter_names": changed,
        "extension_unchanged": True,
        "natural_outcomes_read": False,
        "automatic_deployment": False,
        "candidate": evidence(candidate_path),
        "protocol": evidence(output / "MIGRATION_PROTOCOL.json"),
    }
    atomic(output / "MIGRATION_RESULT.json", result)
    print(json.dumps(result, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--learned", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.current, args.baseline, args.learned, args.output)


if __name__ == "__main__":
    main()
