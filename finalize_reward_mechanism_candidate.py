"""Publish a validated reward-mechanism candidate without deploying it."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


ROOT_FILES = (
    "analyze_reward_feature_gaps.py",
    "reward_mechanism_facts.py",
    "reward_mechanism_features.py",
    "reward_mechanism_policy.py",
    "test_reward_mechanism_features.py",
    "test_reward_mechanism_policy.py",
    "replay_reward_mechanism_candidate.py",
    "build_reward_mechanism_candidate.py",
    "finalize_reward_mechanism_candidate.py",
    "sample_runs.py",
    "whole_run_audit.py",
    "audit_batch.py",
    "current_cards_eng.json",
    "REWARD_MECHANISM_CANDIDATE_20260918.md",
)


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def command(*args, cwd=None, check=True):
    return subprocess.run(
        args, cwd=cwd, text=True, capture_output=True, check=check
    )


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--offline-replay", type=Path, required=True)
    parser.add_argument("--gap-audit", type=Path, required=True)
    parser.add_argument("--draw-rate-prior", type=Path, required=True)
    parser.add_argument("--public-status", type=Path, required=True)
    args = parser.parse_args()
    stage = args.stage.resolve()
    repo = args.repo.resolve()
    offline = args.offline_replay.resolve()
    gap_audit = args.gap_audit.resolve()
    draw_rate_prior = args.draw_rate_prior.resolve()
    models = stage / "models-reward-mechanism-v4"
    receipt = models / "REWARD_MECHANISM_POLICY_REPLAY.json"
    result_path = stage / "REWARD_MECHANISM_FINALIZE_RESULT.json"
    try:
        result = json.loads(receipt.read_text(encoding="utf-8"))
        if not (
            result.get("passed") is True
            and result.get("decisions") == 1496
            and result.get("candidate_rows") == 6008
            and result.get("exact_parent_additivity") == 1496
            and result.get("recorded_encounter_parent_exact") == 1496
            and result.get("maximum_additivity_error") == 0.0
            and result.get("maximum_recorded_parent_error") == 0.0
            and result.get("policy_weights_fitted") is False
            and result.get("natural_outcomes_used_for_policy_weight_selection") is False
            and result.get("future_condition_probabilities_assumed") is False
        ):
            raise RuntimeError("Assembled reward-mechanism replay gate failed")
        destination = repo / "experiments/reward-mechanism-candidate-20260918"
        for directory in (
            destination / "models",
            destination / "replay",
            destination / "analysis",
            destination / "sources",
        ):
            directory.mkdir(parents=True, exist_ok=True)
        for source in sorted(models.glob("*.json")):
            target = destination / (
                "replay" if source.name == receipt.name else "models"
            )
            shutil.copy2(source, target / source.name)
        shutil.copy2(offline, destination / "replay" / "OFFLINE_REPLAY.json")
        shutil.copy2(gap_audit, destination / "analysis" / "FEATURE_GAP_RESULT.json")
        shutil.copy2(stage / "current_cards_eng.json",
                     destination / "sources" / "current_cards_eng.json")
        shutil.copy2(draw_rate_prior,
                     destination / "sources" / "result_cleaned.csv")
        for name in ROOT_FILES:
            shutil.copy2(stage / name, repo / name)

        observer_path = repo / "automation/continuous-goal/observer-config.json"
        observer = json.loads(observer_path.read_text(encoding="utf-8"))
        status_entry = {
            "name": "reward-mechanism-candidate",
            "path": str(args.public_status.resolve()),
        }
        status_files = observer.get("status_files")
        if not isinstance(status_files, list):
            raise RuntimeError("Observer status file configuration differs")
        matches = [row for row in status_files
                   if row.get("name") == status_entry["name"]]
        if matches and matches != [status_entry]:
            raise RuntimeError("Observer reward status entry differs")
        if not matches:
            status_files.append(status_entry)
        atomic(observer_path, observer)

        atomic(args.public_status, {
            "phase": "offline_candidate_ready_waiting_encounter_damage_parent_gate",
            "status": "validated_not_deployed",
            "completed": 1496,
            "planned": 1496,
            "invalid": 0,
        })
        allowed = tuple(ROOT_FILES) + (
            "automation/continuous-goal/observer-config.json",
            "experiments/reward-mechanism-candidate-20260918/",
        )
        dirty = [line[3:] for line in command(
            "git", "status", "--porcelain", cwd=repo
        ).stdout.splitlines()]
        if any(not any(path == prefix or path.startswith(prefix)
                       for prefix in allowed) for path in dirty):
            raise RuntimeError(f"Repository has unrelated changes: {dirty}")
        command("git", "add", *allowed, cwd=repo)
        staged = command(
            "git", "diff", "--cached", "--name-only", cwd=repo
        ).stdout.splitlines()
        if staged:
            command(
                "git", "commit", "-m",
                "Add current reward mechanism candidate",
                cwd=repo,
            )
        command("git", "push", "origin", "HEAD", cwd=repo)
        commit = command("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
        final = {
            "passed": True,
            "commit": commit,
            "receipt_sha256": sha256(receipt),
            "candidate_sha256": sha256(
                models / "reward-mechanism-candidate-model.json"
            ),
            "offline_replay_sha256": sha256(offline),
            "gap_audit_sha256": sha256(gap_audit),
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
            "error": str(exc)[:500],
            "automatic_deployment": False,
        })
        raise


if __name__ == "__main__":
    main()
