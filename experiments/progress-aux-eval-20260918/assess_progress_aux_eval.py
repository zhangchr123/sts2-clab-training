"""Independently verify and archive the frozen progress-aux paired trial.

This observer never starts an engine, retries a seed, edits a model, or deploys a
candidate.  It waits for the one-shot runner to become terminal, verifies the
closed evidence, and publishes a reproducible archive to the private evidence
repository.  A failed or interrupted trial is preserved as such.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import traceback
import zipfile


BASE = Path(os.environ.get("STS2_PROGRESS_AUX_ROOT", "/home/ubuntu/sts2-cloud-eval/progress-aux"))
RUN = BASE / "run"
ASSESSMENT_DIR = BASE / "assessment"
ASSESSMENT = ASSESSMENT_DIR / "ASSESSMENT.json"
PUBLIC_STATUS = ASSESSMENT_DIR / "public-status.json"
UPLOAD = ASSESSMENT_DIR / "UPLOAD.json"
SOLVER_ROOT = Path(os.environ.get(
    "STS2_SOLVER_ROOT", "/home/ubuntu/sts2-linux-smoke-20260917/sts2-solver-bridge"))
REPO = Path(os.environ.get("STS2_CLOUD_REPO", "/home/ubuntu/sts2-cloud-repo"))
REMOTE = "git@github.com:zhangchr123/sts2-clab-training.git"
DEST_REL = Path("experiments/progress-aux-eval-20260918/results")
COUNT = 120
PAIRS = 60
REPO_LIMIT = 900_000_000
SECRET = re.compile(
    rb"-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----|"
    rb"github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{24,}")


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


def file_evidence(path):
    path = Path(path)
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def same_content(left, right):
    return left["bytes"] == right["bytes"] and left["sha256"] == right["sha256"]


def comparison(rows):
    by = {(row["pair"], row["arm"]): row for row in rows}
    expected = {(pair, arm) for pair in range(PAIRS) for arm in ("control", "candidate")}
    require(len(rows) == COUNT and set(by) == expected, "Full original paired denominator required")
    require(all(row["integration_passed"] or not row["goal_success"] for row in rows),
            "Invalid run cannot claim target success")
    arms = {}
    for arm in ("control", "candidate"):
        selected = [row for row in rows if row["arm"] == arm]
        arms[arm] = {
            "games": PAIRS,
            "first_boss_successes": sum(row["goal_success"] for row in selected),
            "full_victories": sum(row["integration_passed"] and row["report"]["outcome"] == "victory"
                                  for row in selected),
            "invalid_failures": sum(not row["integration_passed"] for row in selected),
            "outcomes": dict(Counter(row["report"]["outcome"] for row in selected)),
        }
    plus = sum(by[pair, "candidate"]["goal_success"] and
               not by[pair, "control"]["goal_success"] for pair in range(PAIRS))
    minus = sum(by[pair, "control"]["goal_success"] and
                not by[pair, "candidate"]["goal_success"] for pair in range(PAIRS))
    discordant = plus + minus
    p_value = (sum(math.comb(discordant, k) for k in range(plus, discordant + 1)) /
               2**discordant if discordant else 1.0)
    return {
        **arms,
        "candidate_only_success": plus,
        "control_only_success": minus,
        "one_sided_paired_p": p_value,
        "improvement_gate_passed": plus > minus and p_value <= 0.05,
        "automatic_deployment": False,
        "evaluation_used_for_refit": False,
        "goal_complete": False,
    }


def validate_allocation(protocol):
    jobs = protocol["jobs"]
    require(protocol["planned_pairs"] == PAIRS and protocol["planned_games"] == COUNT,
            "Planned denominator differs")
    require(protocol["parallel_workers"] == 1, "Execution amendment differs")
    require(protocol["automatic_retry"] is False and protocol["automatic_deployment"] is False,
            "Trial unexpectedly permits retry or deployment")
    require(protocol["no_refit_on_evaluation"] is True and protocol["no_sample_extension"] is True,
            "Frozen evaluation restrictions differ")
    require(len(jobs) == COUNT, "Allocation size differs")
    require(len({job["label"] for job in jobs}) == COUNT, "Duplicate evaluation label")
    expected = {(pair, arm) for pair in range(PAIRS) for arm in ("control", "candidate")}
    require({(job["pair"], job["arm"]) for job in jobs} == expected, "Pair/arm allocation differs")
    for pair in range(PAIRS):
        selected = [job for job in jobs if job["pair"] == pair]
        require(len(selected) == 2 and len({job["seed"] for job in selected}) == 1,
                "Paired arms do not share one seed")
    for arm, evidence in protocol["models"].items():
        require(arm in ("control", "candidate"), "Unexpected model arm")
        require(same_content(evidence, file_evidence(evidence["path"])), f"{arm} model changed")
    for job in jobs:
        require(job["model"] == protocol["models"][job["arm"]], "Job model binding differs")
    return jobs


def verify_complete(base=BASE, solver_root=SOLVER_ROOT):
    run = Path(base) / "run"
    protocol_path = run / "PROTOCOL.json"
    result_path = run / "RESULT.json"
    closure_path = run / "SOURCE_CLOSURE.json"
    protocol, result, closure = read(protocol_path), read(result_path), read(closure_path)
    jobs = validate_allocation(protocol)
    for item in protocol["frozen_sources"]:
        require(same_content(item, file_evidence(item["path"])), "Frozen source drift detected")

    expected_audits = {job["label"] + "-audit.json" for job in jobs}
    actual_audits = {path.name for path in run.glob("*-audit.json")}
    require(actual_audits == expected_audits, "Audit receipt set differs from allocation")
    rows = []
    for job in jobs:
        row = read(run / (job["label"] + "-audit.json"))
        require((row["run_id"], row["seed"], row["pair"], row["arm"]) ==
                (job["label"], job["seed"], job["pair"], job["arm"]), "Audit identity differs")
        require(type(row["integration_passed"]) is bool and type(row["goal_success"]) is bool,
                "Audit booleans malformed")
        require(row["evaluation_only"] is True and row["refit_or_selection_eligible"] is False,
                "Evaluation leaked into fitting eligibility")
        require(row["invalid_failure_retained"] is (not row["integration_passed"]),
                "Invalid denominator handling differs")
        require(row["integration_passed"] or not row["goal_success"],
                "Invalid audit claimed success")
        require(row["report"]["seed"] == job["seed"] and
                row["report"]["outcome"] in ("victory", "defeat"), "Run report differs")
        require(row["goal_success"] is bool(row["integration_passed"] and
                                             row["goal"]["natural_goal_success"]),
                "Goal success derivation differs")
        rows.append(row)
    require(all(row["integration_passed"] for row in rows[:2]), "First pair audit gate failed")

    computed = comparison(rows)
    require(result == computed, "Published comparison differs from independent recomputation")
    require(closure["passed"] is True and closure["games"] == COUNT,
            "Source closure is not complete")
    require(closure["automatic_deployment"] is False and closure["raw_originals_retained"] is True,
            "Closure permits deployment or discarded originals")
    require(same_content(closure["protocol"], file_evidence(protocol_path)), "Closure protocol changed")
    require(same_content(closure["result"], file_evidence(result_path)), "Closure result changed")
    require(closure["invalid_failures_retained"] ==
            sum(not row["integration_passed"] for row in rows), "Closure invalid count differs")

    expected_raw = {}
    allowed_roots = []
    for job in jobs:
        folder = Path(solver_root) / "outputs" / job["label"]
        require(folder.is_dir(), "Allocated raw output folder missing")
        allowed_roots.append(folder.resolve())
        for path in folder.rglob("*"):
            if path.is_file():
                expected_raw[str(path)] = file_evidence(path)
    declared_raw = {item["path"]: item for item in closure["raw_sources"]}
    require(set(declared_raw) == set(expected_raw), "Raw source closure path set differs")
    for path, expected in expected_raw.items():
        require(declared_raw[path] == expected, "Raw source changed after closure")
        resolved = Path(path).resolve()
        require(any(resolved == root or root in resolved.parents for root in allowed_roots),
                "Raw closure escaped allocated output folders")

    return {
        "schema_version": "progress-aux-independent-assessment-v1",
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
        "next_action": ("candidate_passed_prepare_independent_deployment_review"
                        if computed["improvement_gate_passed"] else
                        "candidate_rejected_keep_control_and_use_disagreements_for_next_fit"),
        "protocol": file_evidence(protocol_path),
        "result": file_evidence(result_path),
        "source_closure": file_evidence(closure_path),
        "verified_unix": time.time(),
    }


def service_active():
    result = subprocess.run(
        ["systemctl", "show", "sts2-progress-aux-eval.service", "-p", "ActiveState", "--value"],
        text=True, capture_output=True, timeout=30)
    return result.stdout.strip() in ("active", "activating", "reloading")


def safe_bytes(path):
    data = Path(path).read_bytes()
    require(not SECRET.search(data), "Credential-like content rejected from archive")
    return data


def zip_game(target, folder, receipt=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".zip.tmp")
    members = []
    with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(p for p in folder.rglob("*") if p.is_file()):
            data = safe_bytes(path)
            name = path.relative_to(folder).as_posix()
            info = zipfile.ZipInfo(name, date_time=(2026, 9, 18, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, data)
            members.append({"name": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        if receipt is not None:
            data = safe_bytes(receipt)
            info = zipfile.ZipInfo("AUDIT_RECEIPT.json", date_time=(2026, 9, 18, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, data)
            members.append({"name": "AUDIT_RECEIPT.json", "bytes": len(data),
                            "sha256": hashlib.sha256(data).hexdigest()})
    with zipfile.ZipFile(temp) as archive:
        require(archive.testzip() is None, "ZIP readback failed")
        require(archive.namelist() == [item["name"] for item in members], "ZIP member set differs")
    temp.replace(target)
    return {"archive": file_evidence(target), "members": members}


def copy_evidence(staging, assessment, solver_root=SOLVER_ROOT):
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for path in sorted(p for p in RUN.iterdir() if p.is_file()):
        if path.name.endswith(".tmp"):
            continue
        data = safe_bytes(path)
        (staging / path.name).write_bytes(data)
    (staging / "ASSESSMENT.json").write_bytes(safe_bytes(ASSESSMENT))
    protocol = read(RUN / "PROTOCOL.json")
    archives = []
    for job in protocol["jobs"]:
        folder = Path(solver_root) / "outputs" / job["label"]
        if not folder.is_dir():
            continue
        receipt = RUN / (job["label"] + "-audit.json")
        target = staging / "games" / (job["label"] + ".zip")
        entry = {"run_id": job["label"], "seed": job["seed"], "pair": job["pair"], "arm": job["arm"]}
        entry.update(zip_game(target, folder, receipt if receipt.exists() else None))
        entry["archive"]["path"] = target.relative_to(staging).as_posix()
        archives.append(entry)
    atomic(staging / "ARCHIVE_INDEX.json", archives)
    files = []
    for path in sorted(p for p in staging.rglob("*") if p.is_file()):
        item = file_evidence(path)
        item["path"] = path.relative_to(staging).as_posix()
        files.append(item)
    atomic(staging / "RESULTS_MANIFEST.json", {
        "schema_version": "progress-aux-results-archive-v1",
        "assessment_passed": assessment["passed"],
        "candidate_gate_passed": assessment.get("candidate_gate_passed", False),
        "deployment_authorized": False,
        "automatic_retry": False,
        "game_archives": len(archives),
        "files": files,
    })


def run_git(*args, check=True):
    result = subprocess.run(["git", "-C", str(REPO), *args], text=True, capture_output=True, timeout=300)
    if check and result.returncode:
        raise RuntimeError(f"git {args[0]} failed: {result.stderr.strip()[:500]}")
    return result


def tree_bytes(root):
    return sum(path.stat().st_size for path in Path(root).rglob("*") if path.is_file())


def archive_and_push(assessment):
    require(run_git("remote", "get-url", "origin").stdout.strip() == REMOTE, "Unexpected Git remote")
    staging = ASSESSMENT_DIR / "archive-staging"
    destination = REPO / DEST_REL
    status = run_git("status", "--porcelain").stdout.splitlines()
    unrelated = [line for line in status if DEST_REL.as_posix() not in line[3:].replace("\\", "/")]
    require(not unrelated, "Repository has unrelated unreviewed changes")
    if not destination.exists():
        require(not status, "Results path is dirty before archive creation")
        copy_evidence(staging, assessment)
        require(tree_bytes(REPO) + tree_bytes(staging) < REPO_LIMIT, "Repository would exceed 900 MB budget")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging.replace(destination)
    else:
        require((destination / "ASSESSMENT.json").exists() and
                read(destination / "ASSESSMENT.json") == assessment,
                "Existing results destination differs")
        require((destination / "RESULTS_MANIFEST.json").exists(), "Existing results manifest missing")
    run_git("add", "--", DEST_REL.as_posix())
    staged = [name for name in run_git("diff", "--cached", "--name-only").stdout.splitlines() if name]
    require(all(name.startswith(DEST_REL.as_posix() + "/") for name in staged), "Unexpected staged path")
    if staged:
        run_git("commit", "-m", "Archive independently verified progress-aux paired evaluation")
    else:
        require(run_git("log", "-1", "--format=%H", "--", DEST_REL.as_posix()).stdout.strip(),
                "Results exist but have no Git commit")
    commit = run_git("rev-parse", "HEAD").stdout.strip()
    remote = run_git("ls-remote", "origin", "refs/heads/main").stdout.split()
    if not remote or remote[0] != commit:
        pushed = run_git("push", "origin", "HEAD:main", check=False)
        require(pushed.returncode == 0, "Git push failed")
        remote = run_git("ls-remote", "origin", "refs/heads/main").stdout.split()
    require(remote and remote[0] == commit, "Remote head verification failed")
    receipt = {
        "commit": commit,
        "remote_verified": True,
        "repository_bytes_including_history": tree_bytes(REPO),
        "game_archives": len(list((destination / "games").glob("*.zip"))),
        "compressed_game_bytes": sum(path.stat().st_size for path in (destination / "games").glob("*.zip")),
        "destination": str(DEST_REL),
        "uploaded_unix": time.time(),
    }
    atomic(UPLOAD, receipt)
    return receipt


def failure_assessment(reason, kind):
    protocol = RUN / "PROTOCOL.json"
    started = RUN / "STARTED.json"
    error = RUN / "RUNNER_ERROR.json"
    return {
        "schema_version": "progress-aux-independent-assessment-v1",
        "passed": False,
        "evaluation_complete": False,
        "failure_kind": kind,
        "reason": reason[:2000],
        "candidate_gate_passed": False,
        "deployment_authorized": False,
        "automatic_retry": False,
        "evaluation_used_for_refit": False,
        "next_action": "preserve_failed_trial_keep_control_and_continue_sampling",
        "protocol": file_evidence(protocol) if protocol.exists() else None,
        "started": file_evidence(started) if started.exists() else None,
        "runner_error": file_evidence(error) if error.exists() else None,
        "verified_unix": time.time(),
    }


def wait_for_terminal():
    while not (RUN / "STARTED.json").exists():
        atomic(PUBLIC_STATUS, {"phase": "waiting_for_evaluation_start", "updated_unix": time.time()})
        time.sleep(10)
    while True:
        if (RUN / "RESULT.json").exists() and (RUN / "SOURCE_CLOSURE.json").exists():
            if not service_active():
                return "complete"
        if (RUN / "RUNNER_ERROR.json").exists() and not service_active():
            return "failed"
        if not service_active():
            time.sleep(5)
            if not service_active() and not (RUN / "RESULT.json").exists() and not (RUN / "RUNNER_ERROR.json").exists():
                return "interrupted"
        status = read(RUN / "public-status.json") if (RUN / "public-status.json").exists() else {}
        atomic(PUBLIC_STATUS, {"phase": "waiting_for_evaluation_terminal", "evaluation": status,
                              "updated_unix": time.time()})
        time.sleep(10)


def main():
    import fcntl
    ASSESSMENT_DIR.mkdir(parents=True, exist_ok=True)
    lock = (ASSESSMENT_DIR / "assessor.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if ASSESSMENT.exists() and UPLOAD.exists():
        return
    terminal = wait_for_terminal()
    atomic(PUBLIC_STATUS, {"phase": "verifying_terminal_evidence", "terminal": terminal,
                          "updated_unix": time.time()})
    if not ASSESSMENT.exists():
        if terminal == "complete":
            try:
                assessment = verify_complete()
            except Exception:
                assessment = failure_assessment(traceback.format_exc(), "independent_verification_failed")
        elif terminal == "failed":
            assessment = failure_assessment(read(RUN / "RUNNER_ERROR.json")["error"], "runner_failed")
        else:
            assessment = failure_assessment("Started evaluation became inactive without a terminal marker",
                                            "runner_interrupted")
        atomic(ASSESSMENT, assessment)
    assessment = read(ASSESSMENT)
    while not UPLOAD.exists():
        try:
            receipt = archive_and_push(assessment)
            atomic(PUBLIC_STATUS, {"phase": "complete", "assessment_passed": assessment["passed"],
                                  "candidate_gate_passed": assessment.get("candidate_gate_passed", False),
                                  "upload": receipt, "updated_unix": time.time()})
        except Exception as exc:
            atomic(PUBLIC_STATUS, {"phase": "archive_retry_wait", "error_type": type(exc).__name__,
                                  "reason": str(exc)[:500], "updated_unix": time.time()})
            time.sleep(60)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        atomic(PUBLIC_STATUS, {"phase": "assessor_error", "error": traceback.format_exc(),
                              "automatic_retry": False, "updated_unix": time.time()})
        raise
