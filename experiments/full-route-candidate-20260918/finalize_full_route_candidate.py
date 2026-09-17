"""Publish a validated full-route candidate after its assembled replay finishes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
                         encoding="utf-8")
    os.replace(temporary, path)


def command(*args, cwd=None, check=True):
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=check)


def wait_for_receipt(receipt, unit, timeout_seconds):
    deadline = time.monotonic() + timeout_seconds
    while not receipt.is_file():
        if time.monotonic() >= deadline:
            raise TimeoutError("Assembled full-route replay did not finish before the deadline")
        active = command("systemctl", "is-active", unit, check=False).stdout.strip()
        if active not in ("active", "activating"):
            raise RuntimeError(f"Full-route builder became {active!r} without a receipt")
        time.sleep(30)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--public-status", type=Path, required=True)
    parser.add_argument("--builder-unit", default="sts2-full-route-candidate-build.service")
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    args = parser.parse_args()
    stage = args.stage.resolve()
    repo = args.repo.resolve()
    models = stage / "models-full-route-v1"
    receipt = models / "FULL_ROUTE_POLICY_REPLAY.json"
    result_path = stage / "FULL_ROUTE_FINALIZE_RESULT.json"
    try:
        wait_for_receipt(receipt, args.builder_unit, args.timeout_seconds)
        result = json.loads(receipt.read_text(encoding="utf-8"))
        if not (
            result.get("passed") is True
            and result.get("decisions") == 2805
            and result.get("candidate_rows") == 4529
            and result.get("exact_parent_additivity") == 2805
            and result.get("recorded_parent_exact") == 2805
            and result.get("natural_outcomes_used_for_weight_selection") is False
        ):
            raise RuntimeError("Assembled full-route replay gate failed")
        destination = repo / "experiments/full-route-candidate-20260918"
        (destination / "models").mkdir(parents=True, exist_ok=True)
        (destination / "replay").mkdir(parents=True, exist_ok=True)
        for source in sorted(models.glob("*.json")):
            if source.name == receipt.name:
                shutil.copy2(source, destination / "replay" / source.name)
            else:
                shutil.copy2(source, destination / "models" / source.name)
        shutil.copy2(Path(__file__).resolve(), destination / Path(__file__).name)
        atomic(args.public_status, {
            "phase": "offline_candidate_ready_waiting_parent_chain",
            "status": "validated_not_deployed",
            "completed": 2805,
            "planned": 2805,
            "invalid": 0,
        })
        allowed = (
            "automation/continuous-goal/observer-config.json",
            "automation/continuous-goal/observer-supervisor.py",
            "automation/continuous-goal/test_observer_supervisor.py",
            "experiments/full-route-candidate-20260918/",
        )
        dirty = [line[3:] for line in command("git", "status", "--porcelain", cwd=repo).stdout.splitlines()]
        if any(not any(path == prefix or path.startswith(prefix) for prefix in allowed)
               for path in dirty):
            raise RuntimeError(f"Repository has unrelated changes: {dirty}")
        command("git", "add", *allowed, cwd=repo)
        staged = command("git", "diff", "--cached", "--name-only", cwd=repo).stdout.splitlines()
        if staged:
            command("git", "commit", "-m", "Add full-route candidate and gated observer status",
                    cwd=repo)
        command("git", "push", "origin", "HEAD", cwd=repo)
        commit = command("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
        final = {
            "passed": True,
            "commit": commit,
            "receipt_sha256": sha256(receipt),
            "candidate_sha256": sha256(models / "full-route-candidate-model.json"),
            "pushed": True,
            "automatic_deployment": False,
        }
        atomic(result_path, final)
    except BaseException as exc:
        atomic(args.public_status, {
            "phase": "offline_candidate_finalize_error",
            "status": "error",
        })
        atomic(result_path, {
            "passed": False,
            "error_type": type(exc).__name__,
            "automatic_deployment": False,
        })
        raise


if __name__ == "__main__":
    main()
