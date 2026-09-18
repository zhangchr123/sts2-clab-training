#!/usr/bin/env python3
"""Safely keep the CLab continuous-training control plane alive.

The sampler is owned by sts2-cloud-goal.service.  This supervisor never
restarts that service while a batch runner is alive, and it leaves the goal
alone while the frozen paired evaluation owns the clean boundary.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any


GOAL_PATH = Path("/home/ubuntu/sts2-cloud-goal/GOAL.json")
STATE_PATH = Path("/home/ubuntu/sts2-cloud-goal/state.json")
HANDOFF_STATUS_PATHS = (
    Path("/home/ubuntu/sts2-cloud-eval/progress-aux/HANDOFF_STATUS.json"),
    Path("/home/ubuntu/sts2-event-effect-smoke-20260918/HANDOFF_STATUS.json"),
    Path("/home/ubuntu/sts2-selection-effect-smoke-20260918/HANDOFF_STATUS.json"),
    Path("/home/ubuntu/sts2-merchant-item-smoke-20260918/HANDOFF_STATUS.json"),
)
STATUS_PATH = Path("/home/ubuntu/sts2-cloud-goal/continuity-status.json")
GOAL_UNIT = "sts2-cloud-goal.service"
OBSERVER_UNIT = "sts2-observer.service"
EXCLUSIVE_UNITS = (
    "sts2-progress-aux-eval.service",
    "sts2-progress-aux-handoff.service",
    "sts2-event-effect-smoke.service",
    "sts2-event-effect-smoke-handoff.service",
    "sts2-event-effect-paired-eval.service",
    "sts2-selection-effect-smoke.service",
    "sts2-selection-effect-smoke-handoff.service",
    "sts2-selection-effect-paired-eval.service",
    "sts2-merchant-item-smoke.service",
    "sts2-merchant-item-smoke-handoff.service",
)
STALE_SECONDS = 20 * 60


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def unit_active(unit: str) -> bool:
    result = subprocess.run(
        ["systemctl", "is-active", "--quiet", unit], check=False
    )
    return result.returncode == 0


def process_identity_is_live(pid: Any, expected_start_ticks: Any) -> bool:
    try:
        numeric_pid = int(pid)
        stat_fields = Path(f"/proc/{numeric_pid}/stat").read_text().split()
        actual_start_ticks = stat_fields[21]
    except (TypeError, ValueError, IndexError, FileNotFoundError, OSError):
        return False
    return str(expected_start_ticks) == actual_start_ticks


def evaluation_owns_boundary() -> bool:
    if any(unit_active(unit) for unit in EXCLUSIVE_UNITS):
        return True
    owning_phases = {
        "evaluation_running",
        "evaluation_started",
        "goal_suspended_for_evaluation",
        "waiting_for_clean_sampling_boundary",
        "clean_boundary_acquired",
        "paired_evaluation_active",
        "waiting_for_predecessor_evaluation",
        "waiting_for_event_smoke_boundary",
        "event_smoke_boundary_acquired",
        "event_smoke_active",
        "event_smoke_passed_starting_paired_evaluation",
        "event_paired_evaluation_active",
        "waiting_for_parent_event_independent_assessment",
        "waiting_for_selection_smoke_boundary",
        "selection_smoke_boundary_acquired",
        "selection_smoke_active",
        "selection_smoke_passed_starting_paired_evaluation",
        "selection_paired_evaluation_active",
        "waiting_for_merchant_smoke_boundary",
        "merchant_smoke_boundary_acquired",
        "merchant_smoke_active",
    }
    for path in HANDOFF_STATUS_PATHS:
        handoff = read_json(path)
        phase = str(handoff.get("phase", handoff.get("status", ""))).lower()
        if phase in owning_phases:
            return True
    return False


def run_action(action: str, unit: str, dry_run: bool) -> None:
    if dry_run:
        return
    subprocess.run(["systemctl", action, unit], check=True)


def write_status(payload: dict[str, Any], dry_run: bool) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if not dry_run:
        temporary = STATUS_PATH.with_suffix(".json.tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, STATUS_PATH)
        os.chown(STATUS_PATH, 1000, 1000)
    print(text, end="")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    now = time.time()
    goal = read_json(GOAL_PATH)
    state = read_json(STATE_PATH)
    current = state.get("current") if isinstance(state.get("current"), dict) else {}
    runner_live = process_identity_is_live(
        current.get("owner_pid"), current.get("start_ticks")
    )
    goal_active = unit_active(GOAL_UNIT)
    observer_active = unit_active(OBSERVER_UNIT)
    evaluation_active = evaluation_owns_boundary()
    state_age_seconds = (
        max(0.0, now - STATE_PATH.stat().st_mtime)
        if STATE_PATH.exists()
        else None
    )
    actions: list[str] = []

    authorized = goal.get("enabled") is True and goal.get("status") == "active"
    if authorized:
        if not observer_active:
            run_action("start", OBSERVER_UNIT, args.dry_run)
            actions.append("start_observer")
            observer_active = True

        if not goal_active:
            if runner_live:
                actions.append("defer_goal_start_live_runner")
            elif evaluation_active:
                actions.append("defer_goal_start_evaluation_boundary")
            else:
                run_action("start", GOAL_UNIT, args.dry_run)
                actions.append("start_goal")
                goal_active = True
        elif (
            state_age_seconds is not None
            and state_age_seconds > STALE_SECONDS
            and not runner_live
            and not evaluation_active
        ):
            run_action("restart", GOAL_UNIT, args.dry_run)
            actions.append("restart_stale_goal_without_live_runner")
    else:
        actions.append("goal_not_authorized")

    payload = {
        "checked_at_unix": now,
        "authorized": authorized,
        "goal_active": goal_active,
        "observer_active": observer_active,
        "evaluation_owns_boundary": evaluation_active,
        "current_batch": current.get("id"),
        "current_phase": current.get("phase"),
        "runner_live": runner_live,
        "state_age_seconds": state_age_seconds,
        "actions": actions,
        "dry_run": args.dry_run,
        "safety": "never_restart_goal_with_live_runner_or_evaluation_boundary",
    }
    write_status(payload, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
