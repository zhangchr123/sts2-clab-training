"""Independently verify the frozen event-effect paired evaluation."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time
import traceback


BASE = Path("/home/ubuntu/sts2-event-effect-paired-eval-20260918")
RUN = BASE / "run"
ASSESSMENT_DIR = BASE / "assessment"
ASSESSMENT = ASSESSMENT_DIR / "ASSESSMENT.json"
PUBLIC_STATUS = ASSESSMENT_DIR / "public-status.json"
SOLVER_ROOT = Path("/home/ubuntu/sts2-event-effect-stage-20260918/sts2-solver-bridge")
SMOKE_RUN = Path("/home/ubuntu/sts2-event-effect-smoke-20260918/run")
PAIRS = 60
COUNT = PAIRS * 2


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def file_evidence(path):
    path = Path(path)
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def same_content(left, right):
    return left["bytes"] == right["bytes"] and left["sha256"] == right["sha256"]


def validate_allocation(protocol):
    jobs = protocol["jobs"]
    require(protocol["planned_pairs"] == PAIRS, "Pair count differs")
    require(protocol["planned_games"] == COUNT, "Game count differs")
    require(protocol["parallel_workers"] == 1, "Worker count differs")
    require(protocol["automatic_retry"] is False, "Retry permitted")
    require(protocol["automatic_deployment"] is False, "Deployment permitted")
    require(protocol["no_refit_on_evaluation"] is True, "Refit permitted")
    require(protocol["no_sample_extension"] is True, "Sample extension permitted")
    require(len(jobs) == COUNT, "Allocation size differs")
    require(len({row["label"] for row in jobs}) == COUNT, "Duplicate label")
    for pair in range(PAIRS):
        rows = [row for row in jobs if row["pair"] == pair]
        require(len(rows) == 2, "Pair size differs")
        require({row["arm"] for row in rows} == {"control", "candidate"}, "Pair arms differ")
        require(len({row["seed"] for row in rows}) == 1, "Pair seeds differ")
        expected = ["control", "candidate"] if pair % 2 == 0 else ["candidate", "control"]
        require([row["arm"] for row in rows] == expected, "Arm order differs")
    return jobs


def comparison(rows):
    by = {(row["pair"], row["arm"]): row for row in rows}
    expected = {(pair, arm) for pair in range(PAIRS) for arm in ("control", "candidate")}
    require(len(rows) == COUNT and set(by) == expected, "Full denominator required")
    require(
        all(row["integration_passed"] or not row["goal_success"] for row in rows),
        "Invalid run claimed success",
    )
    arms = {}
    for arm in ("control", "candidate"):
        selected = [row for row in rows if row["arm"] == arm]
        arms[arm] = {
            "games": PAIRS,
            "first_boss_successes": sum(row["goal_success"] for row in selected),
            "full_victories": sum(
                row["integration_passed"] and row["report"]["outcome"] == "victory"
                for row in selected
            ),
            "invalid_failures": sum(not row["integration_passed"] for row in selected),
            "outcomes": dict(Counter(row["report"]["outcome"] for row in selected)),
        }
    plus = sum(
        by[pair, "candidate"]["goal_success"]
        and not by[pair, "control"]["goal_success"]
        for pair in range(PAIRS)
    )
    minus = sum(
        by[pair, "control"]["goal_success"]
        and not by[pair, "candidate"]["goal_success"]
        for pair in range(PAIRS)
    )
    discordant = plus + minus
    p_value = (
        sum(math.comb(discordant, k) for k in range(plus, discordant + 1))
        / 2**discordant
        if discordant
        else 1.0
    )
    return {
        **arms,
        "candidate_only_success": plus,
        "control_only_success": minus,
        "one_sided_paired_p": p_value,
        "improvement_gate_passed": plus > minus and p_value <= 0.05,
        "automatic_deployment": False,
        "evaluation_used_for_refit": False,
        "sample_extension": False,
        "goal_complete": False,
    }


def verify_complete():
    protocol_path = RUN / "PROTOCOL.json"
    result_path = RUN / "RESULT.json"
    closure_path = RUN / "SOURCE_CLOSURE.json"
    protocol, result, closure = read(protocol_path), read(result_path), read(closure_path)
    jobs = validate_allocation(protocol)
    smoke = read(SMOKE_RUN / "RESULT.json")
    require(smoke["passed"] is True and smoke["integration_passed"] is True, "Smoke gate differs")
    for item in protocol["frozen_sources"]:
        require(same_content(item, file_evidence(item["path"])), "Frozen source drift")
    expected_audits = {job["label"] + "-audit.json" for job in jobs}
    actual_audits = {path.name for path in RUN.glob("*-audit.json")}
    require(actual_audits == expected_audits, "Audit receipt set differs")
    rows = []
    for job in jobs:
        row = read(RUN / (job["label"] + "-audit.json"))
        require(
            (row["run_id"], row["seed"], row["pair"], row["position"], row["arm"])
            == (job["label"], job["seed"], job["pair"], job["position"], job["arm"]),
            "Audit identity differs",
        )
        require(type(row["integration_passed"]) is bool, "Integration flag malformed")
        require(type(row["goal_success"]) is bool, "Goal flag malformed")
        require(row["refit_or_selection_eligible"] is False, "Evaluation entered fitting")
        require(row["natural_outcome_used_for_fit_or_selection"] is False, "Outcome leak")
        require(row["invalid_failure_retained"] is (not row["integration_passed"]), "Invalid handling differs")
        require(row["integration_passed"] or not row["goal_success"], "Invalid success")
        require(row["report"]["seed"] == job["seed"], "Report seed differs")
        require(row["report"]["outcome"] in ("victory", "defeat"), "Outcome differs")
        require(
            row["goal_success"]
            is bool(row["integration_passed"] and row["goal"]["natural_goal_success"]),
            "Goal derivation differs",
        )
        rows.append(row)
    require(all(row["integration_passed"] for row in rows[:2]), "First pair gate failed")
    computed = comparison(rows)
    require(result == computed, "Published comparison differs")
    require(closure["passed"] is True and closure["games"] == COUNT, "Closure incomplete")
    require(closure["automatic_deployment"] is False, "Closure permits deployment")
    require(closure["raw_originals_retained"] is True, "Raw originals discarded")
    require(same_content(closure["protocol"], file_evidence(protocol_path)), "Protocol changed")
    require(same_content(closure["result"], file_evidence(result_path)), "Result changed")

    expected_raw = {}
    allowed_roots = []
    for job in jobs:
        folder = SOLVER_ROOT / "outputs" / job["label"]
        require(folder.is_dir(), "Raw output folder missing")
        allowed_roots.append(folder.resolve())
        for path in folder.rglob("*"):
            if path.is_file():
                expected_raw[str(path)] = file_evidence(path)
    declared_raw = {item["path"]: item for item in closure["raw_sources"]}
    require(set(declared_raw) == set(expected_raw), "Raw closure path set differs")
    for path, expected in expected_raw.items():
        require(declared_raw[path] == expected, "Raw source changed")
        resolved = Path(path).resolve()
        require(
            any(resolved == root or root in resolved.parents for root in allowed_roots),
            "Raw path escaped allocation",
        )
    return {
        "schema_version": "event-effect-independent-assessment-v1",
        "passed": True,
        "evaluation_complete": True,
        "games": COUNT,
        "pairs": PAIRS,
        "audits_verified": len(rows),
        "raw_files_verified": len(expected_raw),
        "control_first_boss_successes": computed["control"]["first_boss_successes"],
        "candidate_first_boss_successes": computed["candidate"]["first_boss_successes"],
        "candidate_only_success": computed["candidate_only_success"],
        "control_only_success": computed["control_only_success"],
        "one_sided_paired_p": computed["one_sided_paired_p"],
        "candidate_gate_passed": computed["improvement_gate_passed"],
        "deployment_authorized": False,
        "automatic_retry": False,
        "evaluation_used_for_refit": False,
        "next_action": (
            "candidate_passed_prepare_independent_deployment_review"
            if computed["improvement_gate_passed"]
            else "candidate_rejected_keep_control_and_use_disagreements_for_next_iteration"
        ),
        "protocol": file_evidence(protocol_path),
        "result": file_evidence(result_path),
        "source_closure": file_evidence(closure_path),
        "verified_unix": time.time(),
    }


def service_active():
    result = subprocess.run(
        ["systemctl", "show", "sts2-event-effect-paired-eval.service", "-p", "ActiveState", "--value"],
        text=True,
        capture_output=True,
        timeout=30,
    )
    return result.stdout.strip() in ("active", "activating", "reloading")


def main():
    ASSESSMENT_DIR.mkdir(parents=True, exist_ok=True)
    if ASSESSMENT.exists():
        return
    while True:
        if ASSESSMENT.exists():
            return
        if (RUN / "RESULT.json").exists() and not service_active():
            break
        if (RUN / "RUNNER_ERROR.json").exists() and not service_active():
            atomic(ASSESSMENT, {
                "schema_version": "event-effect-independent-assessment-v1",
                "passed": False,
                "evaluation_complete": False,
                "automatic_retry": False,
                "deployment_authorized": False,
                "runner_error": file_evidence(RUN / "RUNNER_ERROR.json"),
                "verified_unix": time.time(),
            })
            atomic(PUBLIC_STATUS, read(ASSESSMENT))
            return
        smoke_result = SMOKE_RUN / "RESULT.json"
        if smoke_result.exists() and read(smoke_result).get("passed") is False:
            atomic(PUBLIC_STATUS, {
                "phase": "paired_evaluation_not_run_smoke_failed",
                "automatic_retry": False,
                "updated_unix": time.time(),
            })
            return
        progress = {}
        status = RUN / "public-status.json"
        if status.exists():
            progress = read(status)
        atomic(PUBLIC_STATUS, {
            "phase": "waiting_for_event_paired_evaluation_terminal",
            "evaluation": progress,
            "updated_unix": time.time(),
        })
        time.sleep(60)
    try:
        assessment = verify_complete()
    except BaseException:
        atomic(ASSESSMENT, {
            "schema_version": "event-effect-independent-assessment-v1",
            "passed": False,
            "evaluation_complete": False,
            "automatic_retry": False,
            "deployment_authorized": False,
            "assessment_error": traceback.format_exc(),
            "verified_unix": time.time(),
        })
        atomic(PUBLIC_STATUS, read(ASSESSMENT))
        raise
    atomic(ASSESSMENT, assessment)
    atomic(PUBLIC_STATUS, assessment)


if __name__ == "__main__":
    main()
