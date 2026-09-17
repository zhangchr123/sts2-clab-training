"""Switch from continuous sampling to the frozen paired trial at a clean batch boundary."""
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
EVAL_ROOT = Path("/home/ubuntu/sts2-cloud-eval/progress-aux")
EVAL_RUN = EVAL_ROOT / "run"
STATUS = EVAL_ROOT / "HANDOFF_STATUS.json"
GOAL_UNIT = "sts2-cloud-goal.service"
EVAL_UNIT = "sts2-progress-aux-eval.service"


def atomic(value):
    temp = STATUS.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(STATUS)


def command(*args, check=True):
    result = subprocess.run(args, text=True, capture_output=True, timeout=30)
    if check and result.returncode:
        raise RuntimeError(f"command failed: {args[0]} {args[1]}: {result.stderr.strip()}")
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
    except FileNotFoundError:
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


def resume_goal_pid(pid):
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
        ready = current is None or (batch_terminal(current) and not owner_live(current))
        atomic({"phase": "waiting_for_clean_sampling_boundary", "current_batch": None if current is None else current["id"],
                "batch_terminal": bool(current and batch_terminal(current)), "owner_live": bool(current and owner_live(current)),
                "updated_unix": time.time(), "automatic_retry": False})
        if not ready:
            time.sleep(2)
            continue

        pid_text = show(GOAL_UNIT, "MainPID")
        pid = int(pid_text or 0)
        if pid:
            os.kill(pid, signal.SIGSTOP)
        time.sleep(0.1)
        state = json.loads(GOAL_STATE.read_text(encoding="utf-8"))
        frozen_current = state.get("current")
        safe = frozen_current is None or (batch_terminal(frozen_current) and not owner_live(frozen_current))
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
        atomic({"phase": "clean_boundary_acquired", "current_batch": None if frozen_current is None else frozen_current["id"],
                "updated_unix": time.time(), "automatic_retry": False})
        return


def monitor_evaluation():
    while active(EVAL_UNIT):
        progress = {}
        path = EVAL_RUN / "public-status.json"
        if path.exists():
            progress = json.loads(path.read_text(encoding="utf-8"))
        atomic({"phase": "paired_evaluation_active", "progress": progress, "updated_unix": time.time(),
                "automatic_retry": False})
        time.sleep(30)
    result = show(EVAL_UNIT, "Result")
    exit_status = show(EVAL_UNIT, "ExecMainStatus")
    command("systemctl", "start", GOAL_UNIT)
    atomic({"phase": "paired_evaluation_terminal_goal_resumed", "service_result": result,
            "exit_status": exit_status, "result_exists": (EVAL_RUN / "RESULT.json").exists(),
            "runner_error_exists": (EVAL_RUN / "RUNNER_ERROR.json").exists(),
            "goal_service_active": active(GOAL_UNIT), "updated_unix": time.time(), "automatic_retry": False})


def main():
    require_files = [EVAL_RUN / "PROTOCOL.json", EVAL_ROOT / "output" / "RUNTIME_READBACK.json"]
    if not all(path.exists() for path in require_files):
        raise RuntimeError("paired evaluation was not fully prepared")
    if (EVAL_RUN / "STARTED.json").exists():
        if active(EVAL_UNIT):
            monitor_evaluation()
        else:
            # Never replay a started allocation after a reboot or service failure.
            command("systemctl", "start", GOAL_UNIT)
            atomic({"phase": "started_evaluation_not_replayed_goal_resumed",
                    "result_exists": (EVAL_RUN / "RESULT.json").exists(),
                    "runner_error_exists": (EVAL_RUN / "RUNNER_ERROR.json").exists(),
                    "updated_unix": time.time(), "automatic_retry": False})
        return
    wait_for_boundary()
    command("systemctl", "start", EVAL_UNIT)
    time.sleep(1)
    if not active(EVAL_UNIT):
        command("systemctl", "start", GOAL_UNIT)
        raise RuntimeError("paired evaluation service failed to become active")
    monitor_evaluation()


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        atomic({"phase": "handoff_error", "error": traceback.format_exc(), "updated_unix": time.time(),
                "automatic_retry": False})
        raise
