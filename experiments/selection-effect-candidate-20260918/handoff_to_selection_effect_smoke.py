"""Gate one selection-effect smoke on the admitted event parent and a clean boundary."""
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
BASE = Path("/home/ubuntu/sts2-selection-effect-smoke-20260918")
RUN = BASE / "run"
STATUS = BASE / "HANDOFF_STATUS.json"
STAGE = Path("/home/ubuntu/sts2-selection-effect-stage-20260918/sts2-solver-bridge")
RUNNER = STAGE / "run_selection_effect_smoke.py"
PARENT_ASSESSMENT = Path(
    "/home/ubuntu/sts2-event-effect-paired-eval-20260918/assessment/ASSESSMENT.json"
)
PARENT_SMOKE_RESULT = Path("/home/ubuntu/sts2-event-effect-smoke-20260918/run/RESULT.json")
GOAL_UNIT = "sts2-cloud-goal.service"
PARENT_ASSESSOR_UNIT = "sts2-event-effect-assessor.service"
PARENT_HANDOFF_UNIT = "sts2-event-effect-smoke-handoff.service"
PARENT_SMOKE_UNIT = "sts2-event-effect-smoke.service"
PARENT_PAIRED_UNIT = "sts2-event-effect-paired-eval.service"
SMOKE_UNIT = "sts2-selection-effect-smoke.service"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic(value):
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATUS.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(STATUS)


def command(*args, check=True, timeout=30):
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
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
    identity = read(launch)
    try:
        text = Path("/proc", str(identity["owner_pid"]), "stat").read_text()
        return text.rsplit(")", 1)[1].split()[19] == str(identity["start_ticks"])
    except (FileNotFoundError, ProcessLookupError):
        return False


def batch_terminal(batch):
    status = Path(batch["path"]) / "public-status.json"
    return status.exists() and read(status).get("phase") in ("complete", "failed")


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


def parent_gate():
    while True:
        if PARENT_ASSESSMENT.exists():
            assessment = read(PARENT_ASSESSMENT)
            accepted = bool(
                assessment.get("passed") is True
                and assessment.get("evaluation_complete") is True
                and assessment.get("candidate_gate_passed") is True
                and assessment.get("deployment_authorized") is False
            )
            atomic({
                "phase": "parent_event_gate_passed" if accepted else "parent_event_rejected_no_selection_smoke",
                "assessment": {
                    key: assessment.get(key)
                    for key in (
                        "passed", "evaluation_complete", "candidate_gate_passed",
                        "candidate_only_success", "control_only_success", "one_sided_paired_p",
                    )
                },
                "updated_unix": time.time(),
                "automatic_retry": False,
            })
            return accepted
        if PARENT_SMOKE_RESULT.exists() and read(PARENT_SMOKE_RESULT).get("passed") is False:
            atomic({
                "phase": "parent_event_smoke_failed_no_selection_smoke",
                "updated_unix": time.time(),
                "automatic_retry": False,
            })
            return False
        parent_live = any(active(unit) for unit in (
            PARENT_ASSESSOR_UNIT, PARENT_HANDOFF_UNIT, PARENT_SMOKE_UNIT, PARENT_PAIRED_UNIT
        ))
        atomic({
            "phase": "waiting_for_parent_event_independent_assessment",
            "parent_chain_live": parent_live,
            "updated_unix": time.time(),
            "automatic_retry": False,
        })
        if not parent_live:
            atomic({
                "phase": "parent_event_terminal_without_assessment_no_selection_smoke",
                "updated_unix": time.time(),
                "automatic_retry": False,
            })
            return False
        time.sleep(60)


def prepare_once():
    if (RUN / "PROTOCOL.json").exists():
        return
    require_absent = (RUN / "STARTED.json", RUN / "RESULT.json", RUN / "RUNNER_ERROR.json")
    if any(path.exists() for path in require_absent):
        raise RuntimeError("Selection smoke has terminal files without a protocol")
    command(
        "runuser", "-u", "ubuntu", "--", "/usr/bin/python3", str(RUNNER), "prepare",
        timeout=120,
    )
    if not (RUN / "PROTOCOL.json").exists():
        raise RuntimeError("Selection smoke prepare did not write its protocol")


def wait_for_boundary():
    while True:
        if not active(GOAL_UNIT):
            command("systemctl", "start", GOAL_UNIT)
            time.sleep(3)
        state = read(GOAL_STATE)
        current = state.get("current")
        ready = current is None or (batch_terminal(current) and not owner_live(current))
        atomic({
            "phase": "waiting_for_selection_smoke_boundary",
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
        state = read(GOAL_STATE)
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
            raise RuntimeError("Goal service did not stop at selection smoke boundary")
        runners = goal_runners()
        if runners:
            command("systemctl", "start", GOAL_UNIT)
            raise RuntimeError(f"Sampling runner remains at selection boundary: {runners}")
        atomic({
            "phase": "selection_smoke_boundary_acquired",
            "current_batch": None if frozen is None else frozen["id"],
            "updated_unix": time.time(),
            "automatic_retry": False,
        })
        return


def smoke_passed():
    result = RUN / "RESULT.json"
    if not result.exists():
        return False
    value = read(result)
    return value.get("passed") is True and value.get("integration_passed") is True


def monitor_smoke():
    while active(SMOKE_UNIT):
        progress = read(RUN / "public-status.json") if (RUN / "public-status.json").exists() else {}
        atomic({
            "phase": "selection_smoke_active",
            "progress": progress,
            "updated_unix": time.time(),
            "automatic_retry": False,
        })
        time.sleep(15)
    command("systemctl", "start", GOAL_UNIT)
    atomic({
        "phase": "selection_smoke_passed_goal_resumed" if smoke_passed() else "selection_smoke_failed_goal_resumed",
        "service_result": show(SMOKE_UNIT, "Result"),
        "exit_status": show(SMOKE_UNIT, "ExecMainStatus"),
        "result_exists": (RUN / "RESULT.json").exists(),
        "runner_error_exists": (RUN / "RUNNER_ERROR.json").exists(),
        "goal_service_active": active(GOAL_UNIT),
        "updated_unix": time.time(),
        "automatic_retry": False,
    })


def main():
    if (RUN / "STARTED.json").exists():
        if active(SMOKE_UNIT):
            monitor_smoke()
        else:
            command("systemctl", "start", GOAL_UNIT)
            atomic({
                "phase": "started_selection_smoke_not_replayed_goal_resumed",
                "result_exists": (RUN / "RESULT.json").exists(),
                "runner_error_exists": (RUN / "RUNNER_ERROR.json").exists(),
                "goal_service_active": active(GOAL_UNIT),
                "updated_unix": time.time(),
                "automatic_retry": False,
            })
        return
    if not parent_gate():
        command("systemctl", "start", GOAL_UNIT)
        return
    prepare_once()
    wait_for_boundary()
    command("systemctl", "start", SMOKE_UNIT)
    time.sleep(1)
    if not active(SMOKE_UNIT):
        command("systemctl", "start", GOAL_UNIT)
        raise RuntimeError("Selection-effect smoke service failed to become active")
    monitor_smoke()


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        atomic({
            "phase": "selection_smoke_handoff_error",
            "error": traceback.format_exc(),
            "updated_unix": time.time(),
            "automatic_retry": False,
        })
        command("systemctl", "start", GOAL_UNIT, check=False)
        raise
