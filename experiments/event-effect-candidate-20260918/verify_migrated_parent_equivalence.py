"""Hash parent-policy scores on recorded event states for path migration checks."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def evidence(path: Path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def jsonl_map(path: Path, execution=False):
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        decision_id = row.get("decision_id")
        if decision_id and (decision_id not in result or execution and "execution" in row):
            result[decision_id] = row
    return result


def normalized(packet):
    fields = (
        "candidate_id",
        "request",
        "score",
        "rule_score",
        "learned_residual",
        "functional_repeat_correction",
        "search_features",
        "deck_discipline",
        "event_risk_guard",
        "missing",
    )
    return [{key: row.get(key) for key in fields} for row in packet["scores"]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--outputs", type=Path, required=True)
    parser.add_argument("--audits", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.source.resolve()))
    from persistent_acquisition_policy import PersistentAcquisitionPolicy

    model = json.loads(args.model.read_text(encoding="utf-8"))
    settings = model["solver_requested_config"]
    audits = {}
    for root in args.audits:
        for path in root.rglob("*-audit.json"):
            audit = json.loads(path.read_text(encoding="utf-8"))
            run_id = (audit.get("job") or {}).get("name") or audit.get("run_id")
            if audit.get("integration_passed") and run_id:
                audits[run_id] = audit
    decision_hashes = {}
    for run_id in sorted(audits):
        folder = args.outputs / run_id
        decision_path = folder / "decisions.jsonl"
        policy_path = folder / "policy.jsonl"
        if not decision_path.is_file() or not policy_path.is_file():
            continue
        states = jsonl_map(decision_path, execution=True)
        policies = jsonl_map(policy_path)
        policy = PersistentAcquisitionPolicy(
            args.model, solver_config=settings, seed=run_id + ":migration-equivalence", epsilon=0.0
        )
        for decision_id, original in policies.items():
            state = states[decision_id]["state"]
            if state.get("decision") != "event_choice":
                continue
            requests = [row["request"] for row in original["scoring"]["scores"]]
            replayed = policy.score_requests(state, requests)
            decision_hashes[decision_id] = hashlib.sha256(canonical(normalized(replayed))).hexdigest()
    combined = hashlib.sha256(canonical(decision_hashes)).hexdigest()
    result = {
        "schema_version": "parent-event-score-migration-equivalence-v1",
        "source": str(args.source.resolve()),
        "model": evidence(args.model),
        "decisions": len(decision_hashes),
        "decision_hashes": decision_hashes,
        "combined_sha256": combined,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("decisions", "combined_sha256")}, indent=2))


if __name__ == "__main__":
    main()
