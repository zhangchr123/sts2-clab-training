"""Run one merchant-item smoke at a clean sampling boundary, then resume the goal."""
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
    command("systemctl", "start", GOAL_UNIT)
    passed = result == "success" and exit_status == "0" and smoke_passed()
    atomic({
        "phase": "merchant_smoke_passed_goal_resumed" if passed else "merchant_smoke_failed_goal_resumed",
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
    if not (RUN / "PROTOCOL.json").exists():
        raise RuntimeError("merchant-item smoke was not fully prepared")
    if (RUN / "STARTED.json").exists():
        if active(SMOKE_UNIT):
            monitor_smoke()
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
        if not active(SMOKE_UNIT) and not goal_runners():
            command("systemctl", "start", GOAL_UNIT, check=False)
        raise
