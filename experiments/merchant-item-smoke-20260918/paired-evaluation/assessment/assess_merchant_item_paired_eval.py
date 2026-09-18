"""Independently verify the frozen merchant-item paired evaluation."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time
import traceback


BASE = Path("/home/ubuntu/sts2-merchant-item-paired-eval-20260918")
RUN = BASE / "run"
ASSESSMENT_DIR = BASE / "assessment"
ASSESSMENT = ASSESSMENT_DIR / "ASSESSMENT.json"
PUBLIC_STATUS = ASSESSMENT_DIR / "public-status.json"
SOLVER_ROOT = Path("/home/ubuntu/sts2-rest-heal-route-stage-20260918/sts2-solver-bridge")
SMOKE_RUN = Path("/home/ubuntu/sts2-merchant-item-smoke-20260918/run")
PAIRED_UNIT = "sts2-merchant-item-paired-eval.service"
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
    require(protocol["schema_version"] == "merchant-item-paired-natural-evaluation-v1", "Protocol schema differs")
    require(protocol["planned_pairs"] == PAIRS, "Pair count differs")
    require(protocol["planned_games"] == COUNT, "Game count differs")
    require(protocol["parallel_workers"] == 1, "Worker count differs")
    require(protocol["automatic_retry"] is False, "Retry permitted")
    require(protocol["automatic_deployment"] is False, "Deployment permitted")
    require(protocol["no_refit_on_evaluation"] is True, "Refit permitted")
    require(protocol["no_sample_extension"] is True, "Sample extension permitted")
    require(protocol["natural_outcome_used_for_fit_or_selection"] is False, "Outcome leak permitted")
    require(protocol["smoke_gate_required"] is True, "Smoke gate omitted")
    require(protocol["assessment"].startswith("Actual Act3 first boss"), "Target definition differs")
    jobs = protocol["jobs"]
    require(len(jobs) == COUNT, "Allocation size differs")
    require(len({row["label"] for row in jobs}) == COUNT, "Duplicate label")
    require(len({row["seed"] for row in jobs}) == PAIRS, "Pair seed count differs")
    require(set(protocol["models"]) == {"control", "candidate"}, "Model arms differ")
    require(set(protocol["policy_ids"]) == {"control", "candidate"}, "Policy arms differ")
    for arm in ("control", "candidate"):
        require(
            same_content(protocol["models"][arm], file_evidence(protocol["models"][arm]["path"])),
            f"{arm} model evidence differs",
        )
    require(protocol["models"]["control"]["sha256"] != protocol["models"]["candidate"]["sha256"], "Arms use the same model")
    for pair in range(PAIRS):
        rows = [row for row in jobs if row["pair"] == pair]
        require(len(rows) == 2, "Pair size differs")
        require({row["arm"] for row in rows} == {"control", "candidate"}, "Pair arms differ")
        require(len({row["seed"] for row in rows}) == 1, "Pair seeds differ")
        require([row["position"] for row in rows] == [0, 1], "Pair positions differ")
        expected = ["control", "candidate"] if pair % 2 == 0 else ["candidate", "control"]
        require([row["arm"] for row in rows] == expected, "Arm order differs")
        for row in rows:
            require(row["model"] == protocol["models"][row["arm"]], "Job model differs")
            require(row["expected_policy_id"] == protocol["policy_ids"][row["arm"]], "Job policy differs")
    return jobs


def comparison(rows):
    by = {(row["pair"], row["arm"]): row for row in rows}
    expected = {(pair, arm) for pair in range(PAIRS) for arm in ("control", "candidate")}
    require(len(rows) == COUNT and set(by) == expected, "Full denominator required")
    require(
        all(row["integration_passed"] or not row["goal_success"] for row in rows),
        "Invalid run claimed target success",
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
        by[pair, "candidate"]["goal_success"] and not by[pair, "control"]["goal_success"]
        for pair in range(PAIRS)
    )
    minus = sum(
        by[pair, "control"]["goal_success"] and not by[pair, "candidate"]["goal_success"]
        for pair in range(PAIRS)
    )
    discordant = plus + minus
    p_value = (
        sum(math.comb(discordant, k) for k in range(plus, discordant + 1)) / 2**discordant
        if discordant else 1.0
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


def validate_raw_policy(job, protocol, folder):
    manifest = read(folder / "manifest.json")
    provenance = manifest["provenance"]
    require(provenance["policy_source"] == job["model"], "Raw policy model differs")
    require(provenance["id"] == job["expected_policy_id"], "Raw manifest policy differs")
    require(provenance["kind"] == "search", "Raw policy kind differs")
    require(provenance["origin"] == "natural", "Raw policy origin differs")
    require(provenance["llm_involved"] is False, "LLM entered gameplay")
    require(manifest["solver_requested_config"] == protocol["config"], "Raw config differs")
    require(manifest["seed"] == job["seed"], "Raw seed differs")
    require(manifest["ascension"] == 10 and manifest["character"] == "Defect", "Raw run setup differs")
    policy_path = folder / "policy.jsonl"
    rows = [json.loads(line) for line in policy_path.read_text(encoding="utf-8").splitlines()]
    require(rows, "Raw policy trace is empty")
    require(len({row["decision_id"] for row in rows}) == len(rows), "Duplicate raw policy ID")
    for row in rows:
        scoring = row["scoring"]
        require(scoring["policy_id"] == job["expected_policy_id"], "Raw decision policy differs")
        if job["arm"] == "candidate":
            require(scoring["merchant_item_contract"] == protocol["merchant_item_contract"], "Raw merchant contract differs")
            require(type(scoring["merchant_item_applied_rows"]) is int, "Raw merchant count malformed")
            for score in scoring["scores"]:
                require("merchant_item_adjustment" in score, "Raw merchant adjustment missing")
                require("merchant_item_detail" in score, "Raw merchant detail missing")
                detail = score["merchant_item_detail"]
                if detail.get("applied"):
                    require(detail["natural_outcomes_used"] is False, "Natural outcome leak")
                    require(detail["hidden_runtime_state_used"] is False, "Hidden-state leak")
                else:
                    require(score["merchant_item_adjustment"] == 0, "Unapplied merchant score changed")
    return len(rows)


def validate_receipt(job, row):
    require(
        (row["run_id"], row["seed"], row["pair"], row["position"], row["arm"])
        == (job["label"], job["seed"], job["pair"], job["position"], job["arm"]),
        "Audit identity differs",
    )
    require(type(row["integration_passed"]) is bool, "Integration flag malformed")
    require(type(row["goal_success"]) is bool, "Goal flag malformed")
    require(row["refit_or_selection_eligible"] is False, "Evaluation entered fitting")
    require(row["natural_outcome_used_for_fit_or_selection"] is False, "Outcome leak")
    require(row["evaluation_only"] is True, "Receipt is not evaluation-only")
    require(row["invalid_failure_retained"] is (not row["integration_passed"]), "Invalid handling differs")
    require(row["integration_passed"] or not row["goal_success"], "Invalid success")
    require(row["report"]["seed"] == job["seed"], "Report seed differs")
    require(row["report"]["outcome"] in ("victory", "defeat"), "Outcome differs")
    require(
        row["goal_success"] is bool(row["integration_passed"] and row["goal"]["natural_goal_success"]),
        "Goal derivation differs",
    )
    expected_valid = bool(row["policy_bound"] and not row["issues"] and row["report"]["outcome"] in ("victory", "defeat"))
    require(row["integration_passed"] is expected_valid, "Integration derivation differs")
    if row["integration_passed"]:
        require(row["explicit_map_readback"]["passed"] is True, "Map readback failed")
        if job["arm"] == "candidate":
            require(row["merchant_policy_readback"]["passed"] is True, "Merchant readback failed")
        else:
            require(row["merchant_policy_readback"] is None, "Control has merchant readback")


def verify_complete():
    protocol_path = RUN / "PROTOCOL.json"
    result_path = RUN / "RESULT.json"
    closure_path = RUN / "SOURCE_CLOSURE.json"
    protocol, result, closure = read(protocol_path), read(result_path), read(closure_path)
    jobs = validate_allocation(protocol)
    smoke = read(SMOKE_RUN / "RESULT.json")
    require(smoke["passed"] is True and smoke["integration_passed"] is True, "Smoke gate differs")
    require(smoke["automatic_deployment"] is False, "Smoke permits deployment")
    for item in protocol["frozen_sources"]:
        require(same_content(item, file_evidence(item["path"])), "Frozen source drift")
    expected_audits = {job["label"] + "-audit.json" for job in jobs}
    actual_audits = {path.name for path in RUN.glob("*-audit.json")}
    require(actual_audits == expected_audits, "Audit receipt set differs")
    rows = []
    raw_policy_rows = 0
    expected_raw = {}
    allowed_roots = []
    for job in jobs:
        row = read(RUN / (job["label"] + "-audit.json"))
        validate_receipt(job, row)
        rows.append(row)
        folder = SOLVER_ROOT / "outputs" / job["label"]
        require(folder.is_dir(), "Raw output folder missing")
        allowed_roots.append(folder.resolve())
        raw_policy_rows += validate_raw_policy(job, protocol, folder)
        for path in folder.rglob("*"):
            if path.is_file():
                expected_raw[str(path)] = file_evidence(path)
    require(all(row["integration_passed"] for row in rows[:2]), "First pair gate failed")
    computed = comparison(rows)
    require(result == computed, "Published comparison differs")
    require(closure["passed"] is True and closure["games"] == COUNT, "Closure incomplete")
    require(closure["automatic_deployment"] is False, "Closure permits deployment")
    require(closure["raw_originals_retained"] is True, "Raw originals discarded")
    require(closure["invalid_failures_retained"] == sum(not row["integration_passed"] for row in rows), "Invalid count differs")
    require(same_content(closure["protocol"], file_evidence(protocol_path)), "Protocol changed")
    require(same_content(closure["result"], file_evidence(result_path)), "Result changed")
    declared_raw = {item["path"]: item for item in closure["raw_sources"]}
    require(len(declared_raw) == len(closure["raw_sources"]), "Duplicate raw closure path")
    require(set(declared_raw) == set(expected_raw), "Raw closure path set differs")
    for path, expected in expected_raw.items():
        require(declared_raw[path] == expected, "Raw source changed")
        resolved = Path(path).resolve()
        require(any(resolved == root or root in resolved.parents for root in allowed_roots), "Raw path escaped allocation")
    return {
        "schema_version": "merchant-item-independent-assessment-v1",
        "passed": True,
        "evaluation_complete": True,
        "games": COUNT,
        "pairs": PAIRS,
        "audits_verified": len(rows),
        "raw_files_verified": len(expected_raw),
        "raw_policy_rows_verified": raw_policy_rows,
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
        ["systemctl", "show", PAIRED_UNIT, "-p", "ActiveState", "--value"],
        text=True, capture_output=True, timeout=30,
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
                "schema_version": "merchant-item-independent-assessment-v1",
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
        progress = read(RUN / "public-status.json") if (RUN / "public-status.json").exists() else {}
        atomic(PUBLIC_STATUS, {
            "phase": "waiting_for_merchant_paired_evaluation_terminal",
            "evaluation": progress,
            "updated_unix": time.time(),
        })
        time.sleep(60)
    try:
        assessment = verify_complete()
    except BaseException:
        atomic(ASSESSMENT, {
            "schema_version": "merchant-item-independent-assessment-v1",
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
