"""Publish a validated encounter-damage candidate without deploying it."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


ROOT_FILES = (
    "train_encounter_damage_catalog.py",
    "test_train_encounter_damage_catalog.py",
    "encounter_damage_features.py",
    "test_encounter_damage_features.py",
    "encounter_damage_policy.py",
    "test_encounter_damage_policy.py",
    "replay_encounter_damage_candidate.py",
    "build_encounter_damage_candidate.py",
    "finalize_encounter_damage_candidate.py",
    "sample_runs.py",
    "whole_run_audit.py",
    "audit_batch.py",
    "ENCOUNTER_DAMAGE_CANDIDATE_20260918.md",
)


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
                         encoding="utf-8")
    os.replace(temporary, path)


def command(*args, cwd=None, check=True):
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=check)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--offline-replay", type=Path, required=True)
    parser.add_argument("--public-status", type=Path, required=True)
    args = parser.parse_args()
    stage = args.stage.resolve()
    repo = args.repo.resolve()
    offline = args.offline_replay.resolve()
    models = stage / "models-encounter-damage-v1"
    receipt = models / "ENCOUNTER_DAMAGE_POLICY_REPLAY.json"
    result_path = stage / "ENCOUNTER_DAMAGE_FINALIZE_RESULT.json"
    try:
        result = json.loads(receipt.read_text(encoding="utf-8"))
        if not (
            result.get("passed") is True
            and result.get("decisions") == 2805
            and result.get("candidate_rows") == 4529
            and result.get("exact_parent_additivity") == 2805
            and result.get("recorded_full_route_parent_exact") == 2805
            and result.get("natural_outcomes_used_for_policy_weight_selection") is False
            and result.get("catalog_test_used_for_parameter_selection") is False
        ):
            raise RuntimeError("Assembled encounter-damage replay gate failed")
        destination = repo / "experiments/encounter-damage-candidate-20260918"
        for directory in (destination / "models", destination / "replay",
                          destination / "catalog"):
            directory.mkdir(parents=True, exist_ok=True)
        for source in sorted(models.glob("*.json")):
            target = destination / ("replay" if source.name == receipt.name else "models")
            shutil.copy2(source, target / source.name)
        shutil.copy2(offline, destination / "replay" / "OFFLINE_REPLAY.json")
        shutil.copy2(stage / "encounter_damage_catalog_v3.json",
                     destination / "catalog" / "CATALOG_RESULT.json")
        for name in ROOT_FILES:
            shutil.copy2(stage / name, repo / name)
        atomic(args.public_status, {
            "phase": "offline_candidate_ready_waiting_full_route_parent_gate",
            "status": "validated_not_deployed",
            "completed": 2805,
            "planned": 2805,
            "invalid": 0,
        })
        allowed = tuple(ROOT_FILES) + (
            "automation/continuous-goal/observer-config.json",
            "experiments/encounter-damage-candidate-20260918/",
        )
        dirty = [line[3:] for line in command(
            "git", "status", "--porcelain", cwd=repo
        ).stdout.splitlines()]
        if any(not any(path == prefix or path.startswith(prefix) for prefix in allowed)
               for path in dirty):
            raise RuntimeError(f"Repository has unrelated changes: {dirty}")
        command("git", "add", *allowed, cwd=repo)
        staged = command(
            "git", "diff", "--cached", "--name-only", cwd=repo
        ).stdout.splitlines()
        if staged:
            command(
                "git", "commit", "-m",
                "Add public encounter damage candidate",
                cwd=repo,
            )
        command("git", "push", "origin", "HEAD", cwd=repo)
        commit = command("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
        final = {
            "passed": True,
            "commit": commit,
            "receipt_sha256": sha256(receipt),
            "candidate_sha256": sha256(
                models / "encounter-damage-candidate-model.json"
            ),
            "offline_replay_sha256": sha256(offline),
            "catalog_sha256": sha256(stage / "encounter_damage_catalog_v3.json"),
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
