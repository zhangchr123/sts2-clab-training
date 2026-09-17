"""Independent real-policy readback for the migrated progress-auxiliary model."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys


TIE = 1e-12


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evidence(path):
    path = Path(path)
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def expected_delta(features, control_parameters, candidate_parameters, names):
    return sum(
        (candidate_parameters[name] - control_parameters[name]) * features[name]
        for name in names
    )


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def run(root, control_path, candidate_path, branch_input, output):
    root = Path(root).resolve()
    control_path = Path(control_path).resolve()
    candidate_path = Path(candidate_path).resolve()
    branch_input = Path(branch_input).resolve()
    output = Path(output).resolve()
    control = read(control_path)
    candidate = read(candidate_path)
    data = read(branch_input)
    require(control["parameter_names"] == candidate["parameter_names"], "Runtime schemas differ")
    names = control["parameter_names"]
    require(len(names) == 471 and len(data["groups"]) == 254, "Unexpected verification scope")
    require(candidate.get("automatic_deployment") is False, "Candidate unexpectedly marked for deployment")
    require(candidate["migration"]["natural_outcomes_read"] is False, "Migration claims natural outcomes")

    sys.path.insert(0, str(root))
    os.chdir(root)
    from sample_runs import build_policy
    from decision_data import enumerate_candidates

    control_policy = build_policy(
        "progress-aux-control-readback", control["solver_requested_config"], epsilon=0.0, model_path=Path(control_path)
    )
    candidate_policy = build_policy(
        "progress-aux-candidate-readback", control["solver_requested_config"], epsilon=0.0, model_path=Path(candidate_path)
    )
    maximum_error = 0.0
    scored = 0
    changed_top_sets = 0
    for group in data["groups"]:
        for policy in (control_policy, candidate_policy):
            policy.base._special_builds = set(group.get("observed_special_builds", []))
        expected_ids = set(group["candidate_ids"])
        scored_rows = []
        for policy, label in ((control_policy, "control"), (candidate_policy, "candidate")):
            before = policy.base.rng.getstate()
            rows = {r["candidate_id"]: r for r in policy.base.score(group["state"], enumerate_candidates(group["state"]))["scores"]}
            require(policy.base.rng.getstate() == before, f"{label} scoring consumed RNG")
            repeat = {r["candidate_id"]: r for r in policy.base.score(group["state"], enumerate_candidates(group["state"]))["scores"]}
            require(rows == repeat and policy.base.rng.getstate() == before, f"{label} scoring is not deterministic")
            require(expected_ids <= set(rows), f"{label} is missing a frozen branch candidate")
            scored_rows.append(rows)
        control_rows, candidate_rows = scored_rows
        for cid in group["candidate_ids"]:
            c0, c1 = control_rows[cid], candidate_rows[cid]
            require(c0["search_features"] == c1["search_features"], "Runtime feature drift between arms")
            expected = expected_delta(c0["search_features"], control["parameters"], candidate["parameters"], names)
            maximum_error = max(maximum_error, abs((c1["score"] - c0["score"]) - expected))
            scored += 1
        cmax = max(row["score"] for row in control_rows.values())
        nmax = max(row["score"] for row in candidate_rows.values())
        ctop = {cid for cid, row in control_rows.items() if row["score"] >= cmax - TIE}
        ntop = {cid for cid, row in candidate_rows.items() if row["score"] >= nmax - TIE}
        changed_top_sets += ctop != ntop

    require(scored == 1016, "Did not score all four arms of all gates")
    require(maximum_error <= 1e-8, "Runtime score delta differs from migrated linear parameters")
    require(changed_top_sets > 0, "Migrated candidate changes no controlled decisions")
    result = {
        "passed": True,
        "gates": 254,
        "scores_verified": scored,
        "changed_top_sets": changed_top_sets,
        "maximum_score_delta_error": maximum_error,
        "control": evidence(control_path),
        "candidate": evidence(candidate_path),
        "branch_input": evidence(branch_input),
        "natural_outcomes_read": False,
        "production_deployed": False,
    }
    atomic(output, result)
    print(json.dumps(result, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--control", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--branch-input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    run(args.root, args.control, args.candidate, args.branch_input, args.output)


if __name__ == "__main__":
    main()
