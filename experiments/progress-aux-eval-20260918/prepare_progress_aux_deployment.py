"""Prepare, explicitly activate, or roll back the progress-aux candidate.

Preparation is read-only with respect to the active policy.  Activation requires
the independently verified natural gate, an exact plan digest, an inactive goal
service, and no live batch runner.  This file is tooling, not automatic deployment.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


EVAL = Path(os.environ.get("STS2_PROGRESS_AUX_ROOT", "/home/ubuntu/sts2-cloud-eval/progress-aux"))
ASSESSMENT = EVAL / "assessment" / "ASSESSMENT.json"
RUN = EVAL / "run"
CANDIDATE = EVAL / "output" / "candidate-runtime-model.json"
GOAL_ROOT = Path(os.environ.get("STS2_GOAL_ROOT", "/home/ubuntu/sts2-cloud-goal"))
LIVE_TEMPLATE = GOAL_ROOT / "runner_template.py"
DEPLOY = EVAL / "deployment"
PLAN = DEPLOY / "DEPLOYMENT_PLAN.json"
CANDIDATE_TEMPLATE = DEPLOY / "candidate-runner-template.py"
BACKUP_TEMPLATE = DEPLOY / "baseline-runner-template.py"
ACTIVATION = DEPLOY / "ACTIVATION.json"
ROLLBACK = DEPLOY / "ROLLBACK.json"
BASELINE_LITERAL = "model=BASE_CHECKS/'linux-rebound-model.json'"
CANDIDATE_LITERAL = "model=pathlib.Path('/home/ubuntu/sts2-cloud-eval/progress-aux/output/candidate-runtime-model.json')"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def atomic_bytes(path, data, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        with path.open("xb") as handle:
            handle.write(data)
        return
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_bytes(data)
    temp.replace(path)


def evidence(path):
    path = Path(path)
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def same_content(left, right):
    return left["bytes"] == right["bytes"] and left["sha256"] == right["sha256"]


def validate_gate(assessment_path=ASSESSMENT, run=RUN, candidate=CANDIDATE):
    assessment_path, run, candidate = Path(assessment_path), Path(run), Path(candidate)
    assessment = read(assessment_path)
    result = read(run / "RESULT.json")
    protocol = read(run / "PROTOCOL.json")
    closure = read(run / "SOURCE_CLOSURE.json")
    require(assessment.get("passed") is True and assessment.get("evaluation_complete") is True,
            "Independent evaluation assessment did not pass")
    require(assessment.get("games") == 120 and assessment.get("pairs") == 60 and
            assessment.get("audits_verified") == 120, "Independent denominator differs")
    require(assessment.get("candidate_gate_passed") is True, "Candidate natural gate did not pass")
    require(assessment.get("deployment_authorized") is False,
            "Assessment must not claim automatic deployment authorization")
    require(same_content(assessment["result"], evidence(run / "RESULT.json")),
            "Assessed result changed")
    require(same_content(assessment["protocol"], evidence(run / "PROTOCOL.json")),
            "Assessed protocol changed")
    require(same_content(assessment["source_closure"], evidence(run / "SOURCE_CLOSURE.json")),
            "Assessed source closure changed")
    require(result.get("improvement_gate_passed") is True and
            result.get("candidate_only_success", 0) > result.get("control_only_success", 0) and
            result.get("one_sided_paired_p", 1) <= 0.05, "Frozen statistical gate differs")
    require(result.get("automatic_deployment") is False and result.get("evaluation_used_for_refit") is False,
            "Evaluation unexpectedly permits deployment or refit")
    require(closure.get("passed") is True and closure.get("automatic_deployment") is False,
            "Source closure did not pass")
    candidate_evidence = evidence(candidate)
    require(protocol["models"]["candidate"] == candidate_evidence, "Candidate model differs from protocol")
    model = read(candidate)
    require(model.get("automatic_deployment") is False and model.get("first_boss_success_verified") is False,
            "Candidate metadata was mutated to claim deployment or proof")
    return assessment, result, protocol, candidate_evidence


def prepare(assessment_path=ASSESSMENT, run=RUN, candidate=CANDIDATE,
            live_template=LIVE_TEMPLATE, deploy=DEPLOY):
    assessment_path, run, candidate = Path(assessment_path), Path(run), Path(candidate)
    live_template, deploy = Path(live_template), Path(deploy)
    plan_path = deploy / "DEPLOYMENT_PLAN.json"
    candidate_template = deploy / "candidate-runner-template.py"
    require(not plan_path.exists() and not candidate_template.exists(), "Deployment plan already exists")
    assessment, result, protocol, candidate_evidence = validate_gate(assessment_path, run, candidate)
    source = live_template.read_text(encoding="utf-8")
    require(source.count(BASELINE_LITERAL) == 1 and CANDIDATE_LITERAL not in source,
            "Live runner template is not the exact baseline form")
    replacement = source.replace(BASELINE_LITERAL, CANDIDATE_LITERAL)
    compile(replacement, str(candidate_template), "exec")
    atomic_bytes(candidate_template, replacement.encode("utf-8"), exclusive=True)
    plan = {
        "schema_version": "progress-aux-manual-deployment-plan-v1",
        "prepared_unix": time.time(),
        "assessment": evidence(assessment_path),
        "result": evidence(run / "RESULT.json"),
        "protocol": evidence(run / "PROTOCOL.json"),
        "source_closure": evidence(run / "SOURCE_CLOSURE.json"),
        "candidate_model": candidate_evidence,
        "control_model": protocol["models"]["control"],
        "baseline_runner_template": evidence(live_template),
        "candidate_runner_template": evidence(candidate_template),
        "gate": {
            "control_first_boss_successes": result["control"]["first_boss_successes"],
            "candidate_first_boss_successes": result["candidate"]["first_boss_successes"],
            "candidate_only_success": result["candidate_only_success"],
            "control_only_success": result["control_only_success"],
            "one_sided_paired_p": result["one_sided_paired_p"],
        },
        "manual_activation_required": True,
        "clean_boundary_required": True,
        "goal_service_must_be_inactive": True,
        "live_batch_runner_must_be_absent": True,
        "automatic_deployment": False,
        "activation_changes_only_future_batch_template": True,
        "current_or_completed_batches_unchanged": True,
        "rollback_template": str(deploy / "baseline-runner-template.py"),
    }
    atomic(plan_path, plan)
    return plan_path, plan


def goal_inactive():
    result = subprocess.run(
        ["systemctl", "show", "sts2-cloud-goal.service", "-p", "ActiveState", "--value"],
        text=True, capture_output=True, timeout=30)
    return result.stdout.strip() in ("inactive", "failed")


def live_batch_runners():
    found = []
    for cmdline in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            text = cmdline.read_bytes().replace(b"\0", b" ").decode(errors="replace")
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        if "/home/ubuntu/sts2-cloud-goal/batches/" in text and "run_batch.py run" in text:
            found.append(int(cmdline.parent.name))
    return found


def activate(plan_path=PLAN, plan_digest=None, live_template=LIVE_TEMPLATE,
             inactive_check=goal_inactive, runner_check=live_batch_runners):
    plan_path, live_template = Path(plan_path), Path(live_template)
    plan = read(plan_path)
    require(plan_digest == evidence(plan_path)["sha256"], "Exact deployment plan digest required")
    require(plan["manual_activation_required"] is True and plan["automatic_deployment"] is False,
            "Plan is not manual-only")
    require(inactive_check(), "Goal service must be inactive at a clean boundary")
    require(not runner_check(), "A live sampling batch runner still exists")
    require(same_content(plan["assessment"], evidence(plan["assessment"]["path"])), "Assessment changed")
    require(same_content(plan["result"], evidence(plan["result"]["path"])), "Result changed")
    require(same_content(plan["protocol"], evidence(plan["protocol"]["path"])), "Protocol changed")
    require(same_content(plan["source_closure"], evidence(plan["source_closure"]["path"])), "Closure changed")
    require(same_content(plan["candidate_model"], evidence(plan["candidate_model"]["path"])),
            "Candidate model changed")
    require(same_content(plan["baseline_runner_template"], evidence(live_template)),
            "Live template is no longer the reviewed baseline")
    candidate_template = Path(plan["candidate_runner_template"]["path"])
    require(same_content(plan["candidate_runner_template"], evidence(candidate_template)),
            "Candidate runner template changed")
    backup = plan_path.parent / "baseline-runner-template.py"
    require(not backup.exists(), "Baseline backup already exists")
    atomic_bytes(backup, live_template.read_bytes(), exclusive=True)
    atomic_bytes(live_template, candidate_template.read_bytes())
    require(same_content(evidence(candidate_template), evidence(live_template)), "Activated template readback failed")
    record = {
        "schema_version": "progress-aux-manual-activation-v1",
        "activated_unix": time.time(),
        "plan": evidence(plan_path),
        "candidate_model": plan["candidate_model"],
        "previous_template": evidence(backup),
        "active_template": evidence(live_template),
        "automatic_deployment": False,
        "future_batches_only": True,
        "goal_service_restarted": False,
    }
    activation = plan_path.parent / "ACTIVATION.json"
    require(not activation.exists(), "Activation record already exists")
    atomic(activation, record)
    return activation, record


def rollback(activation_path=ACTIVATION, activation_digest=None, live_template=LIVE_TEMPLATE,
             inactive_check=goal_inactive, runner_check=live_batch_runners):
    activation_path, live_template = Path(activation_path), Path(live_template)
    record = read(activation_path)
    require(activation_digest == evidence(activation_path)["sha256"], "Exact activation digest required")
    require(inactive_check(), "Goal service must be inactive at a clean boundary")
    require(not runner_check(), "A live sampling batch runner still exists")
    require(same_content(record["active_template"], evidence(live_template)), "Active template changed")
    backup = Path(record["previous_template"]["path"])
    require(same_content(record["previous_template"], evidence(backup)), "Rollback template changed")
    atomic_bytes(live_template, backup.read_bytes())
    require(same_content(evidence(backup), evidence(live_template)), "Rollback readback failed")
    result = {
        "schema_version": "progress-aux-manual-rollback-v1",
        "rolled_back_unix": time.time(),
        "activation": evidence(activation_path),
        "restored_template": evidence(live_template),
        "goal_service_restarted": False,
        "automatic_restart": False,
    }
    path = activation_path.parent / "ROLLBACK.json"
    require(not path.exists(), "Rollback record already exists")
    atomic(path, result)
    return path, result


def main():
    require(len(sys.argv) >= 2, "Use prepare, activate PLAN_SHA256, or rollback ACTIVATION_SHA256")
    if sys.argv[1:] == ["prepare"]:
        path, value = prepare()
    elif len(sys.argv) == 3 and sys.argv[1] == "activate":
        path, value = activate(plan_digest=sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == "rollback":
        path, value = rollback(activation_digest=sys.argv[2])
    else:
        raise ValueError("Use prepare, activate PLAN_SHA256, or rollback ACTIVATION_SHA256")
    print(json.dumps({"path": str(path), "evidence": evidence(path), "automatic_deployment": False,
                      "record": value}, ensure_ascii=False))


if __name__ == "__main__":
    main()
