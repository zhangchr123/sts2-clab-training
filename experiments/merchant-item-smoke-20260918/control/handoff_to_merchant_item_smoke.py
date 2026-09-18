"""Run merchant smoke and paired evaluation at one clean boundary, then resume."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import time
import traceback


GOAL_STATE = Path("/home/ubuntu/sts2-cloud-goal/state.json")
BASE = Path("/home/ubuntu/sts2-merchant-item-smoke-20260918")
RUN = BASE / "run"
STATUS = BASE / "HANDOFF_STATUS.json"
GOAL_UNIT = "sts2-cloud-goal.service"
SMOKE_UNIT = "sts2-merchant-item-smoke.service"
PAIRED_UNIT = "sts2-merchant-item-paired-eval.service"
PAIRED_RUN = Path("/home/ubuntu/sts2-merchant-item-paired-eval-20260918/run")


def atomic(value):
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(STATUS)


def command(*args, check=True):
    result = subprocess.run(args, text=True, capture_output=True, timeout=30)
    if check and result.returncode:
        raise RuntimeError(f"command failed: {' '.join(args)}: {result.stderr.strip()}")
    return result


def show(unit, prop):
    return command("systemctl", "show", unit, "-p", prop, "--value", check=False).stdout.strip()


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
    return status.exists() and json.loads(status.read_text(encoding="utf-8")).get("phase") in ("complete", "failed")


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


def resume_pid(pid):
    if pid:
        try:
            os.kill(pid, signal.SIGCONT)
        except ProcessLookupError:
            pass


def wait_for_boundary():
    while True:
        if not active(GOAL_UNIT):
            command("systemctl", "start", GOAL_UNIT)
            time.sleep(3)
        state = json.loads(GOAL_STATE.read_text(encoding="utf-8"))
        current = state.get("current")
        terminal = bool(current and batch_terminal(current))
        live = bool(current and owner_live(current))
        atomic({
            "phase": "waiting_for_merchant_smoke_boundary",
            "current_batch": None if current is None else current["id"],
            "batch_terminal": terminal,
            "owner_live": live,
            "updated_unix": time.time(),
            "automatic_retry": False,
        })
        if current is not None and (not terminal or live):
            time.sleep(2)
            continue

        pid = int(show(GOAL_UNIT, "MainPID") or 0)
        if pid:
            os.kill(pid, signal.SIGSTOP)
        time.sleep(0.1)
        frozen = json.loads(GOAL_STATE.read_text(encoding="utf-8")).get("current")
        safe = frozen is None or (batch_terminal(frozen) and not owner_live(frozen))
        if not safe:
            resume_pid(pid)
            time.sleep(2)
            continue
        command("systemctl", "stop", "--no-block", GOAL_UNIT)
        resume_pid(pid)
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
            "phase": "merchant_smoke_boundary_acquired",
            "current_batch": None if frozen is None else frozen["id"],
            "updated_unix": time.time(),
            "automatic_retry": False,
        })
        return


def smoke_passed():
    path = RUN / "RESULT.json"
    if not path.exists():
        return False
    result = json.loads(path.read_text(encoding="utf-8"))
    return result.get("passed") is True and result.get("integration_passed") is True


def start_paired_and_monitor(*, start=True):
    if start:
        command("systemctl", "start", PAIRED_UNIT)
        time.sleep(1)
        if not active(PAIRED_UNIT):
            command("systemctl", "start", GOAL_UNIT)
            raise RuntimeError("merchant-item paired evaluation failed to become active")
    while active(PAIRED_UNIT):
        progress = {}
        path = PAIRED_RUN / "public-status.json"
        if path.exists():
            progress = json.loads(path.read_text(encoding="utf-8"))
        atomic({
            "phase": "merchant_paired_evaluation_active",
            "progress": progress,
            "updated_unix": time.time(),
            "automatic_retry": False,
        })
        time.sleep(30)
    result = show(PAIRED_UNIT, "Result")
    exit_status = show(PAIRED_UNIT, "ExecMainStatus")
    command("systemctl", "start", GOAL_UNIT)
    atomic({
        "phase": "merchant_paired_evaluation_terminal_goal_resumed",
        "service_result": result,
        "exit_status": exit_status,
        "result_exists": (PAIRED_RUN / "RESULT.json").exists(),
        "runner_error_exists": (PAIRED_RUN / "RUNNER_ERROR.json").exists(),
        "goal_service_active": active(GOAL_UNIT),
        "candidate_deployed": False,
        "updated_unix": time.time(),
        "automatic_retry": False,
    })


def monitor_smoke():
    while active(SMOKE_UNIT):
        progress = {}
        path = RUN / "public-status.json"
        if path.exists():
            progress = json.loads(path.read_text(encoding="utf-8"))
        atomic({
            "phase": "merchant_smoke_active",
            "progress": progress,
            "updated_unix": time.time(),
            "automatic_retry": False,
        })
        time.sleep(15)
    result = show(SMOKE_UNIT, "Result")
    exit_status = show(SMOKE_UNIT, "ExecMainStatus")
    passed = result == "success" and exit_status == "0" and smoke_passed()
    if passed:
        atomic({
            "phase": "merchant_smoke_passed_starting_paired_evaluation",
            "result_exists": True,
            "updated_unix": time.time(),
            "automatic_retry": False,
        })
        start_paired_and_monitor()
        return
    command("systemctl", "start", GOAL_UNIT)
    atomic({
        "phase": "merchant_smoke_failed_goal_resumed",
        "service_result": result,
        "exit_status": exit_status,
        "result_exists": (RUN / "RESULT.json").exists(),
        "runner_error_exists": (RUN / "RUNNER_ERROR.json").exists(),
        "goal_service_active": active(GOAL_UNIT),
        "candidate_deployed": False,
        "updated_unix": time.time(),
        "automatic_retry": False,
    })


def main():
    if not (RUN / "PROTOCOL.json").exists() or not (PAIRED_RUN / "PROTOCOL.json").exists():
        raise RuntimeError("merchant-item smoke or paired evaluation was not fully prepared")
    if (RUN / "STARTED.json").exists():
        if active(SMOKE_UNIT):
            monitor_smoke()
        elif smoke_passed() and not (PAIRED_RUN / "STARTED.json").exists():
            if active(GOAL_UNIT) or goal_runners():
                wait_for_boundary()
            start_paired_and_monitor()
        elif active(PAIRED_UNIT):
            start_paired_and_monitor(start=False)
        else:
            command("systemctl", "start", GOAL_UNIT)
            atomic({
                "phase": "started_smoke_not_replayed_goal_resumed",
                "result_exists": (RUN / "RESULT.json").exists(),
                "runner_error_exists": (RUN / "RUNNER_ERROR.json").exists(),
                "goal_service_active": active(GOAL_UNIT),
                "updated_unix": time.time(),
                "automatic_retry": False,
            })
        return
    wait_for_boundary()
    command("systemctl", "start", SMOKE_UNIT)
    time.sleep(1)
    if not active(SMOKE_UNIT):
        command("systemctl", "start", GOAL_UNIT)
        raise RuntimeError("merchant-item smoke service failed to become active")
    monitor_smoke()


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        atomic({
            "phase": "merchant_smoke_handoff_error",
            "error": traceback.format_exc(),
            "updated_unix": time.time(),
            "automatic_retry": False,
        })
        if not active(SMOKE_UNIT) and not active(PAIRED_UNIT) and not goal_runners():
            command("systemctl", "start", GOAL_UNIT, check=False)
        raise
