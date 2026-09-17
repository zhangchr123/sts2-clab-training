"""Serialized CLab execution of the frozen 60-pair progress-auxiliary trial."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time
import traceback


ROOT = Path("/home/ubuntu/sts2-linux-smoke-20260917/sts2-solver-bridge")
BASE_CHECKS = Path("/home/ubuntu/sts2-cloud-checks-20260917")
BASE = Path("/home/ubuntu/sts2-cloud-eval/progress-aux")
INPUT = BASE / "input"
MIGRATION = BASE / "output"
OUT = BASE / "run"
CONTROL = BASE_CHECKS / "linux-rebound-model.json"
CANDIDATE = MIGRATION / "candidate-runtime-model.json"
ALLOCATION = INPUT / "allocation.json"
DECLARATION = INPUT / "declaration.json"
COUNT = 120
PAIRS = 60


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        return
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_evidence(path):
    path = Path(path)
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def same_content(left, right):
    return left["bytes"] == right["bytes"] and left["sha256"] == right["sha256"]


def owner_state(identity):
    try:
        text = Path("/proc", str(identity["owner_pid"]), "stat").read_text()
        ticks = text.rsplit(")", 1)[1].split()[19]
        return "live" if ticks == str(identity["start_ticks"]) else "reused"
    except (FileNotFoundError, ProcessLookupError):
        return "missing"


def validate_allocation(jobs):
    require(len(jobs) == COUNT, "Frozen allocation size differs")
    require(len({job["label"] for job in jobs}) == COUNT, "Duplicate evaluation label")
    require(len({job["seed"] for job in jobs}) == PAIRS, "Frozen pair seeds differ")
    expected = {(pair, arm) for pair in range(PAIRS) for arm in ("control", "candidate")}
    require({(job["pair"], job["arm"]) for job in jobs} == expected, "Pair/arm allocation differs")
    for pair in range(PAIRS):
        rows = [job for job in jobs if job["pair"] == pair]
        require(len({job["seed"] for job in rows}) == 1, "Paired arms do not share a seed")
    return True


def validate_model_difference(control, candidate):
    allowed = {"parameters", "training", "migration", "automatic_deployment", "first_boss_success_verified"}
    require(all(control.get(key) == candidate.get(key) for key in control if key not in allowed),
            "Runtime mechanism, solver, guard, feature source or deck contract differs")
    names = control["parameter_names"]
    require(names == candidate["parameter_names"] and len(names) == 471, "Parameter schema differs")
    require(set(control["parameters"]) == set(candidate["parameters"]) == set(names), "Parameter mapping differs")
    old, roles = names[:438], names[438:]
    require(all(candidate["parameters"][name] == control["parameters"][name] for name in roles),
            "The 33 functional extension parameters changed")
    changed = [name for name in old if candidate["parameters"][name] != control["parameters"][name]]
    require(changed, "Candidate changes no old parameters")
    require(all(type(candidate["parameters"][name]) in (int, float)
                and math.isfinite(candidate["parameters"][name])
                and abs(candidate["parameters"][name]) <= 4
                and abs(candidate["parameters"][name] - control["parameters"][name]) <= 1 + 1e-12
                for name in old), "Candidate is outside the frozen parameter bounds")
    require(candidate.get("automatic_deployment") is False, "Candidate unexpectedly marked for deployment")
    return changed


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
            "full_victories": sum(row["integration_passed"] and row["report"]["outcome"] == "victory" for row in selected),
            "invalid_failures": sum(not row["integration_passed"] for row in selected),
            "outcomes": dict(Counter(row["report"]["outcome"] for row in selected)),
        }
    plus = sum(by[pair, "candidate"]["goal_success"] and not by[pair, "control"]["goal_success"] for pair in range(PAIRS))
    minus = sum(by[pair, "control"]["goal_success"] and not by[pair, "candidate"]["goal_success"] for pair in range(PAIRS))
    discordant = plus + minus
    p_value = sum(math.comb(discordant, k) for k in range(plus, discordant + 1)) / 2**discordant if discordant else 1.0
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


def runtime_modules():
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    os.environ["DOTNET_ROOT"] = "/home/ubuntu/.dotnet"
    os.environ["PATH"] = "/home/ubuntu/.dotnet:" + os.environ["PATH"]
    from sample_runs import run_one, build_policy
    from audit_batch import _Audit
    from boss_progress import observed_progress
    from whole_run_audit import validate_whole_run_choices
    from merchant_removal_audit import validate_merchant_lifecycle
    from merchant_removal_value import validate_previews
    from public_route_learning import validate_trace_observations, policy_input
    from map_observation import validate_map_observation
    from persistent_acquisition_policy import require_parent_integration, VERSION
    return locals()


def verify_maps(records, policies, traces, policy_input, validate_map_observation):
    before = []
    current = {"type": "initializing"}
    for trace in traces:
        before.append(current)
        response = trace.get("response")
        if isinstance(response, dict) and (response.get("type") == "decision" or
                (trace["request"]["cmd"] in ("action", "start_run") and response.get("type") == "error")):
            current = response
    used, cursor = [], 0
    for record in records:
        packet, state = policies[record["decision_id"]], record["state"]
        if state.get("decision") != "map_select":
            require("map_observation" not in packet, "Map evidence on non-map decision")
            continue
        index = next((i for i in range(cursor, len(traces))
                      if before[i] == state and traces[i]["request"] == record["chosen"]["request"]), None)
        require(index is not None and index > 0, "Missing original map action")
        query = index - 1
        require(before[query] == state, "Map query current state differs")
        observation = packet["map_observation"]
        validate_map_observation(state, observation, traces[query])
        require(packet["scoring"]["public_route_input"] == policy_input(state, observation), "Map scoring input differs")
        used.append(query)
        cursor = index + 1
    require(used == [i for i, trace in enumerate(traces) if trace["request"]["cmd"] == "get_map"],
            "Unaccounted map query")
    return {"passed": True, "map_queries": len(used)}


def prepare():
    modules = runtime_modules()
    modules["require_parent_integration"]()
    require(read(BASE_CHECKS / "PORTABILITY_RESULT.json")["passed"], "Scoring portability must pass")
    require(read(BASE_CHECKS / "LINUX_NATURAL_RESULT.json")["passed"], "Linux natural integration must pass")
    migration = read(MIGRATION / "MIGRATION_RESULT.json")
    runtime_readback = read(MIGRATION / "RUNTIME_READBACK.json")
    require(migration["passed"] and runtime_readback["passed"], "Candidate migration/readback must pass")
    require(same_content(migration["candidate"], file_evidence(CANDIDATE)), "Migrated candidate changed")
    require(same_content(runtime_readback["candidate"], file_evidence(CANDIDATE)), "Readback candidate changed")
    declaration, jobs = read(DECLARATION), read(ALLOCATION)
    require(same_content(declaration["allocation"], file_evidence(ALLOCATION)), "Original allocation content changed")
    validate_allocation(jobs)
    control, candidate = read(CONTROL), read(CANDIDATE)
    changed = validate_model_difference(control, candidate)
    require(not OUT.exists(), "Never overwrite the cloud paired evaluation")
    for job in jobs:
        require(not (ROOT / "outputs" / job["label"]).exists(), "A frozen evaluation label already exists")
    for name, model in (("control", CONTROL), ("candidate", CANDIDATE)):
        modules["build_policy"]("cloud-progress-aux-preflight-" + name, control["solver_requested_config"], epsilon=0.0, model_path=model)
    sources = list(ROOT.glob("*.py")) + list(ROOT.glob("*.json")) + list((ROOT / "reference_facts").rglob("*"))
    sources += list((ROOT.parent / "sts2-cli/lib").glob("*.dll")) + list((ROOT / "runtime").rglob("*.dll"))
    sources += [CONTROL, CANDIDATE, ALLOCATION, DECLARATION, Path(__file__), ROOT.parent / "BASE.json",
                MIGRATION / "MIGRATION_RESULT.json", MIGRATION / "MIGRATION_PROTOCOL.json", MIGRATION / "RUNTIME_READBACK.json",
                INPUT / "protocol.json", INPUT / "INDEPENDENT_READBACK.json",
                BASE_CHECKS / "LINUX_NATURAL_RESULT.json", BASE_CHECKS / "LINUX_PROTOCOL.json", BASE_CHECKS / "PORTABILITY_RESULT.json"]
    frozen = [file_evidence(path) for path in sources if path.is_file()]
    models = {"control": file_evidence(CONTROL), "candidate": file_evidence(CANDIDATE)}
    bound_jobs = [dict(job, model=models[job["arm"]]) for job in jobs]
    protocol = {
        "version": "cloud-progress-auxiliary-paired-v1",
        "original_trial_version": declaration["version"],
        "purpose": "Prospective paired natural evaluation of the admitted 438 progress-auxiliary fit on the verified 471 Linux runtime",
        "planned_pairs": PAIRS,
        "planned_games": COUNT,
        "parallel_workers": 1,
        "execution_amendment": "Serialized for the 4 GiB CLab host before any natural outcome; allocation/order/gates unchanged",
        "jobs": bound_jobs,
        "models": models,
        "changed_old_parameters": changed,
        "config": control["solver_requested_config"],
        "sampling": {"ascension": 10, "epsilon": 0.0, "max_seconds": 1200, "max_decisions": 500, "selection_budget": 256},
        "first_pair_gate": "Both first-pair arms must complete and pass integration audit; never retry",
        "assessment": "Actual Act3 first boss; full A10 victory secondary; invalid retained in denominator as failure",
        "improvement_gate": "Strictly more candidate target successes and exact one-sided paired p<=0.05",
        "no_refit_on_evaluation": True,
        "no_sample_extension": True,
        "automatic_retry": False,
        "automatic_deployment": False,
        "batch_raw_budget_bytes": 24 * 1024**3,
        "stop_when_free_below_bytes": 8 * 1024**3,
        "frozen_sources": frozen,
    }
    OUT.mkdir(parents=True)
    write(OUT / "PROTOCOL.json", protocol, exclusive=True)
    write(OUT / "public-status.json", {"phase": "prepared", "planned": COUNT, "completed": 0, "invalid": 0})
    print(json.dumps({"prepared": True, "pairs": PAIRS, "games": COUNT, "changed_parameters": len(changed)}), flush=True)


def run():
    modules = runtime_modules()
    protocol = read(OUT / "PROTOCOL.json")
    require(not (OUT / "STARTED.json").exists(), "Never restart the paired evaluation")

    def unchanged():
        return all(file_evidence(item["path"]) == item for item in protocol["frozen_sources"])

    require(unchanged(), "Frozen source drift before evaluation")
    write(OUT / "STARTED.json", {"pid": os.getpid(), "at": time.time(), "automatic_retry": False}, exclusive=True)
    receipts = []

    def status(phase):
        write(OUT / "public-status.json", {
            "phase": phase,
            "planned": COUNT,
            "completed": len(receipts),
            "invalid": sum(not row["integration_passed"] for row in receipts),
            "control_target_successes": sum(row["arm"] == "control" and row["goal_success"] for row in receipts),
            "candidate_target_successes": sum(row["arm"] == "candidate" and row["goal_success"] for row in receipts),
        })

    try:
        for index, job in enumerate(protocol["jobs"]):
            require(unchanged(), "Frozen source drift before game")
            require(shutil.disk_usage(ROOT).free > protocol["stop_when_free_below_bytes"], "Cloud disk below 8 GiB reserve")
            raw_bytes = sum(path.stat().st_size for prior in protocol["jobs"]
                            for path in (ROOT / "outputs" / prior["label"]).rglob("*") if path.is_file())
            require(raw_bytes < protocol["batch_raw_budget_bytes"], "Evaluation raw data reached its budget")
            folder = ROOT / "outputs" / job["label"]
            require(not folder.exists(), "Never retry a started paired seed arm")
            status("paired_natural_evaluation")
            report = modules["run_one"](job["label"], job["seed"], settings=protocol["config"],
                                        model_path=Path(job["model"]["path"]), **protocol["sampling"])
            audit = modules["_Audit"](folder)
            records, _ = audit.run(report)
            traces = [json.loads(line) for line in (folder / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
            policies_list = [json.loads(line) for line in (folder / "policy.jsonl").read_text(encoding="utf-8").splitlines()]
            policies = {row["decision_id"]: row for row in policies_list}
            goal = modules["observed_progress"](traces, natural=True, expected_seed=job["seed"])
            issues = list(audit.issues) + list(goal["errors"])
            maps = None
            try:
                require(len(policies) == len(policies_list), "Duplicate policy ID")
                modules["validate_whole_run_choices"](records, policies)
                modules["validate_trace_observations"](records, policies, traces)
                maps = verify_maps(records, policies, traces, modules["policy_input"], modules["validate_map_observation"])
                modules["validate_merchant_lifecycle"](traces)
                modules["validate_previews"](traces)
            except Exception:
                issues.append({"reason": "explicit_choice_or_map_or_merchant_audit", "detail": traceback.format_exc()})
            manifest = read(folder / "manifest.json")
            runtime = list(manifest["versions"]["sources"].values()) + [
                value for key, value in manifest["versions"].items() if key != "sources" and value is not None
            ]
            bound = (manifest["provenance"]["policy_source"] == job["model"]
                     and manifest["provenance"]["id"] == modules["VERSION"]
                     and manifest["provenance"]["origin"] == "natural"
                     and not manifest["provenance"]["llm_involved"]
                     and manifest["solver_requested_config"] == protocol["config"]
                     and manifest["seed"] == job["seed"] and manifest["ascension"] == 10
                     and manifest["character"] == "Defect"
                     and all(file_evidence(item["path"]) == item for item in runtime))
            valid = bool(bound and not issues and report["outcome"] in ("victory", "defeat") and unchanged())
            receipt = {
                "run_id": job["label"], "seed": job["seed"], "pair": job["pair"], "arm": job["arm"],
                "report": report, "goal": goal, "issues": issues, "explicit_map_readback": maps,
                "policy_bound": bound, "integration_passed": valid,
                "invalid_failure_retained": not valid, "goal_success": valid and goal["natural_goal_success"],
                "evaluation_only": True, "refit_or_selection_eligible": False,
            }
            write(OUT / (job["label"] + "-audit.json"), receipt, exclusive=True)
            receipts.append(receipt)
            status("paired_natural_evaluation")
            if index == 1:
                require(all(row["integration_passed"] for row in receipts), "First pair failed audit; preserve and never retry")
        require(unchanged(), "Frozen source drift at closure")
        result = comparison(receipts)
        write(OUT / "RESULT.json", result, exclusive=True)
        raw_sources = [file_evidence(path) for job in protocol["jobs"]
                       for path in (ROOT / "outputs" / job["label"]).rglob("*") if path.is_file()]
        write(OUT / "SOURCE_CLOSURE.json", {
            "passed": True, "games": COUNT, "protocol": file_evidence(OUT / "PROTOCOL.json"),
            "result": file_evidence(OUT / "RESULT.json"), "raw_sources": raw_sources,
            "invalid_failures_retained": sum(not row["integration_passed"] for row in receipts),
            "raw_originals_retained": True, "automatic_deployment": False,
        }, exclusive=True)
        status("complete")
    except BaseException:
        write(OUT / "RUNNER_ERROR.json", {"error": traceback.format_exc(), "completed": len(receipts), "automatic_retry": False})
        status("failed")
        raise


def main():
    require(len(sys.argv) == 2 and sys.argv[1] in ("prepare", "run"), "Use prepare or run")
    prepare() if sys.argv[1] == "prepare" else run()


if __name__ == "__main__":
    main()
