"""Serialize the one-shot event-effect smoke after the active paired trial."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import time
import traceback


GOAL_ROOT = Path("/home/ubuntu/sts2-cloud-goal")
GOAL_STATE = GOAL_ROOT / "state.json"
BASE = Path("/home/ubuntu/sts2-event-effect-smoke-20260918")
RUN = BASE / "run"
STATUS = BASE / "HANDOFF_STATUS.json"
GOAL_UNIT = "sts2-cloud-goal.service"
PREDECESSOR_EVAL_UNIT = "sts2-progress-aux-eval.service"
PREDECESSOR_HANDOFF_UNIT = "sts2-progress-aux-handoff.service"
SMOKE_UNIT = "sts2-event-effect-smoke.service"
PAIRED_UNIT = "sts2-event-effect-paired-eval.service"
PAIRED_RUN = Path("/home/ubuntu/sts2-event-effect-paired-eval-20260918/run")


def atomic(value):
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(STATUS)


def command(*args, check=True):
    result = subprocess.run(args, text=True, capture_output=True, timeout=30)
    if check and result.returncode:
        raise RuntimeError(
            f"command failed: {args[0]} {args[1]}: {result.stderr.strip()}"
        )
    return result


def show(unit, prop):
    return command(
        "systemctl", "show", unit, "-p", prop, "--value", check=False
    ).stdout.strip()


def active(unit):
    return show(unit, "ActiveState") in ("active", "activating", "reloading")


def owner_live(batch):
    launch = Path(batch["path"]) / "LAUNCH.json"
    if not launch.exists():
        return False
    identity = json.loads(launch.read_text(encoding="utf-8"))
    try:
        text = Path("/proc", str(identity["owner_pid"]), "stat").read_text()
        return text.rsplit(")", 1)[1].split()[19] == str(identity["start_ticks"])
    except (FileNotFoundError, ProcessLookupError):
        return False


def batch_terminal(batch):
    status = Path(batch["path"]) / "public-status.json"
    return status.exists() and json.loads(status.read_text(encoding="utf-8")).get(
        "phase"
    ) in ("complete", "failed")


def goal_runners():
    found = []
    for cmdline in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            text = cmdline.read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        if "/home/ubuntu/sts2-cloud-goal/batches/" in text and "run_batch.py run" in text:
            found.append({"pid": int(cmdline.parent.name), "cmdline": text})
    return found


def resume_goal_pid(pid):
    if pid:
        try:
            os.kill(pid, signal.SIGCONT)
        except ProcessLookupError:
            pass


def wait_for_predecessor():
    while active(PREDECESSOR_EVAL_UNIT) or active(PREDECESSOR_HANDOFF_UNIT):
        progress = {}
        path = Path("/home/ubuntu/sts2-cloud-eval/progress-aux/run/public-status.json")
        if path.exists():
            progress = json.loads(path.read_text(encoding="utf-8"))
        atomic({
            "phase": "waiting_for_predecessor_evaluation",
            "predecessor_progress": progress,
            "updated_unix": time.time(),
            "automatic_retry": False,
        })
        time.sleep(30)


def wait_for_boundary():
    while True:
        if not active(GOAL_UNIT):
            command("systemctl", "start", GOAL_UNIT)
            time.sleep(3)
        state = json.loads(GOAL_STATE.read_text(encoding="utf-8"))
        current = state.get("current")
        ready = current is None or (batch_terminal(current) and not owner_live(current))
        atomic({
            "phase": "waiting_for_event_smoke_boundary",
            "current_batch": None if current is None else current["id"],
            "batch_terminal": bool(current and batch_terminal(current)),
            "owner_live": bool(current and owner_live(current)),
            "updated_unix": time.time(),
            "automatic_retry": False,
        })
        if not ready:
            time.sleep(2)
            continue

        pid = int(show(GOAL_UNIT, "MainPID") or 0)
        if pid:
            os.kill(pid, signal.SIGSTOP)
        time.sleep(0.1)
        state = json.loads(GOAL_STATE.read_text(encoding="utf-8"))
        frozen = state.get("current")
        safe = frozen is None or (batch_terminal(frozen) and not owner_live(frozen))
        if not safe:
            resume_goal_pid(pid)
            time.sleep(2)
            continue

        command("systemctl", "stop", "--no-block", GOAL_UNIT)
        resume_goal_pid(pid)
        deadline = time.time() + 30
        while active(GOAL_UNIT) and time.time() < deadline:
            time.sleep(0.25)
        if active(GOAL_UNIT):
            raise RuntimeError("goal service did not stop at the frozen boundary")
        runners = goal_runners()
        if runners:
            command("systemctl", "start", GOAL_UNIT)
            raise RuntimeError(f"sampling runner still live after boundary: {runners}")
        atomic({
            "phase": "event_smoke_boundary_acquired",
            "current_batch": None if frozen is None else frozen["id"],
            "updated_unix": time.time(),
            "automatic_retry": False,
        })
        return


def start_paired_and_monitor():
    command("systemctl", "start", PAIRED_UNIT)
    time.sleep(1)
    if not active(PAIRED_UNIT):
        command("systemctl", "start", GOAL_UNIT)
        raise RuntimeError("event-effect paired service failed to become active")
    while active(PAIRED_UNIT):
        progress = {}
        path = PAIRED_RUN / "public-status.json"
        if path.exists():
            progress = json.loads(path.read_text(encoding="utf-8"))
        atomic({
            "phase": "event_paired_evaluation_active",
            "progress": progress,
            "updated_unix": time.time(),
            "automatic_retry": False,
        })
        time.sleep(30)
    result = show(PAIRED_UNIT, "Result")
    exit_status = show(PAIRED_UNIT, "ExecMainStatus")
    command("systemctl", "start", GOAL_UNIT)
    atomic({
        "phase": "event_paired_evaluation_terminal_goal_resumed",
        "service_result": result,
        "exit_status": exit_status,
        "result_exists": (PAIRED_RUN / "RESULT.json").exists(),
        "runner_error_exists": (PAIRED_RUN / "RUNNER_ERROR.json").exists(),
        "goal_service_active": active(GOAL_UNIT),
        "updated_unix": time.time(),
        "automatic_retry": False,
    })


def smoke_passed():
    path = RUN / "RESULT.json"
    if not path.exists():
        return False
    result = json.loads(path.read_text(encoding="utf-8"))
    return result.get("passed") is True and result.get("integration_passed") is True


def monitor_smoke():
    while active(SMOKE_UNIT):
        progress = {}
        path = RUN / "public-status.json"
        if path.exists():
            progress = json.loads(path.read_text(encoding="utf-8"))
        atomic({
            "phase": "event_smoke_active",
            "progress": progress,
            "updated_unix": time.time(),
            "automatic_retry": False,
        })
        time.sleep(15)
    result = show(SMOKE_UNIT, "Result")
    exit_status = show(SMOKE_UNIT, "ExecMainStatus")
    if result == "success" and exit_status == "0" and smoke_passed():
        atomic({
            "phase": "event_smoke_passed_starting_paired_evaluation",
            "smoke_result_exists": True,
            "updated_unix": time.time(),
            "automatic_retry": False,
        })
        start_paired_and_monitor()
        return
    command("systemctl", "start", GOAL_UNIT)
    atomic({
        "phase": "event_smoke_failed_goal_resumed",
        "service_result": result,
        "exit_status": exit_status,
        "result_exists": (RUN / "RESULT.json").exists(),
        "runner_error_exists": (RUN / "RUNNER_ERROR.json").exists(),
        "goal_service_active": active(GOAL_UNIT),
        "updated_unix": time.time(),
        "automatic_retry": False,
    })


def main():
    required = [RUN / "PROTOCOL.json"]
    if not all(path.exists() for path in required):
        raise RuntimeError("event-effect smoke was not fully prepared")
    if (RUN / "STARTED.json").exists():
        if active(SMOKE_UNIT):
            monitor_smoke()
        elif smoke_passed() and not (PAIRED_RUN / "STARTED.json").exists():
            wait_for_predecessor()
            wait_for_boundary()
            start_paired_and_monitor()
        elif active(PAIRED_UNIT):
            start_paired_and_monitor()
        else:
            if not active(PREDECESSOR_EVAL_UNIT) and not active(PREDECESSOR_HANDOFF_UNIT):
                command("systemctl", "start", GOAL_UNIT)
            atomic({
                "phase": "started_evaluation_not_replayed_goal_resumed",
                "result_exists": (RUN / "RESULT.json").exists(),
                "runner_error_exists": (RUN / "RUNNER_ERROR.json").exists(),
                "paired_result_exists": (PAIRED_RUN / "RESULT.json").exists(),
                "paired_runner_error_exists": (PAIRED_RUN / "RUNNER_ERROR.json").exists(),
                "goal_service_active": active(GOAL_UNIT),
                "updated_unix": time.time(),
                "automatic_retry": False,
            })
        return
    wait_for_predecessor()
    wait_for_boundary()
    command("systemctl", "start", SMOKE_UNIT)
    time.sleep(1)
    if not active(SMOKE_UNIT):
        command("systemctl", "start", GOAL_UNIT)
        raise RuntimeError("event-effect smoke service failed to become active")
    monitor_smoke()


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        atomic({
            "phase": "event_smoke_handoff_error",
            "error": traceback.format_exc(),
            "updated_unix": time.time(),
            "automatic_retry": False,
        })
        if not active(PREDECESSOR_EVAL_UNIT) and not active(PREDECESSOR_HANDOFF_UNIT):
            command("systemctl", "start", GOAL_UNIT, check=False)
        raise
