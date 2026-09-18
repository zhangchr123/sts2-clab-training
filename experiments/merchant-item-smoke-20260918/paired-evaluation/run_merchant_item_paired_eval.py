"""Serialized 60-pair natural evaluation of the source-bound merchant wrapper."""
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


ADAPTER_ROOT = Path("/home/ubuntu/sts2-merchant-smoke-runtime-20260918")
MERCHANT_ROOT = Path("/home/ubuntu/sts2-merchant-item-stage-20260918")
EVENT_ROOT = Path("/home/ubuntu/sts2-event-outcome-future-potions-v2-stage-20260918")
BRIDGE_ROOT = Path("/home/ubuntu/sts2-rest-heal-route-stage-20260918/sts2-solver-bridge")
SMOKE_BASE = Path("/home/ubuntu/sts2-merchant-item-smoke-20260918")
BASE = Path(os.environ.get(
    "STS2_MERCHANT_EVAL_BASE",
    "/home/ubuntu/sts2-merchant-item-paired-eval-20260918",
))
OUT = BASE / "run"
CONTROL = BRIDGE_ROOT / "models-rest-heal-route-v1/migrated-baseline-model.json"
CANDIDATE = MERCHANT_ROOT / "models-merchant-item-v1/merchant-item-candidate-model.json"
REPLAY = MERCHANT_ROOT / "models-merchant-item-v1/MERCHANT_ITEM_POLICY_REPLAY.json"
LIVE_PROBE = MERCHANT_ROOT / "models-merchant-item-v1/MERCHANT_ITEM_LIVE_POLICY_PROBE.json"
PAIRS = 60
COUNT = PAIRS * 2


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value, *, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_evidence(path):
    path = Path(path)
    data = path.read_bytes()
    return {
        "path": str(path),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def validate_parent_lineage(candidate_path, terminal_path):
    """Validate every declared parent artifact and end at the frozen control."""
    current = Path(candidate_path)
    terminal = Path(terminal_path)
    seen = set()
    lineage = []
    while current != terminal:
        require(current not in seen, "Candidate parent lineage contains a cycle")
        seen.add(current)
        artifact = read(current)
        parent = artifact.get("parent_model")
        require(isinstance(parent, dict), "Candidate parent lineage ended before control")
        parent_path = Path(parent.get("path", ""))
        require(parent_path.is_absolute(), "Candidate parent path is not absolute")
        require(file_evidence(parent_path) == parent, "Candidate parent evidence differs")
        lineage.append(file_evidence(current))
        current = parent_path
    lineage.append(file_evidence(terminal))
    require(len(lineage) >= 2, "Candidate must wrap the control")
    return lineage


def runtime_modules():
    sys.path[:0] = [str(path) for path in (
        SMOKE_BASE, ADAPTER_ROOT, MERCHANT_ROOT, EVENT_ROOT, BRIDGE_ROOT
    )]
    os.chdir(BRIDGE_ROOT)
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
    from persistent_acquisition_policy import (
        VERSION as CONTROL_VERSION,
        require_parent_integration,
    )
    from merchant_item_policy import (
        VERSION as CANDIDATE_VERSION,
        source_files as candidate_source_files,
    )
    from run_merchant_item_smoke import verify_maps, validate_merchant_packets
    from probe import ROOT as OUTPUT_ROOT
    return locals()


def allocation():
    jobs = []
    for pair in range(PAIRS):
        arms = ("control", "candidate") if pair % 2 == 0 else ("candidate", "control")
        seed = f"defect-merchant-item-paired-20260918-fresh-{pair:03d}"
        for position, arm in enumerate(arms):
            jobs.append({
                "pair": pair,
                "position": position,
                "arm": arm,
                "seed": seed,
                "label": f"defect-merchant-item-paired-20260918-{arm}-{pair:03d}-{position}",
            })
    return jobs


def validate_allocation(jobs):
    require(len(jobs) == COUNT, "Allocation size differs")
    require(len({row["label"] for row in jobs}) == COUNT, "Duplicate label")
    require(len({row["seed"] for row in jobs}) == PAIRS, "Pair seed count differs")
    for pair in range(PAIRS):
        rows = [row for row in jobs if row["pair"] == pair]
        require(len(rows) == 2, "Pair size differs")
        require({row["arm"] for row in rows} == {"control", "candidate"}, "Pair arms differ")
        require(len({row["seed"] for row in rows}) == 1, "Pair seeds differ")
        require([row["position"] for row in rows] == [0, 1], "Pair order differs")
        expected = ["control", "candidate"] if pair % 2 == 0 else ["candidate", "control"]
        require([row["arm"] for row in rows] == expected, "Alternating arm order differs")
    return True


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


def prepare():
    modules = runtime_modules()
    modules["require_parent_integration"]()
    control, candidate, replay = read(CONTROL), read(CANDIDATE), read(REPLAY)
    live_probe = read(LIVE_PROBE)
    require(candidate["format"] == modules["CANDIDATE_VERSION"], "Candidate format differs")
    lineage = validate_parent_lineage(CANDIDATE, CONTROL)
    require(
        candidate["solver_requested_config"] == control["solver_requested_config"],
        "Solver configuration differs",
    )
    require(candidate["automatic_deployment"] is False, "Candidate permits deployment")
    require(
        candidate["source_files"] == modules["candidate_source_files"](),
        "Candidate source closure differs",
    )
    contract = candidate["merchant_item_contract"]
    require(contract["natural_outcomes_used_for_parameter_selection"] is False, "Candidate uses natural outcomes")
    require(contract["public_state_only"] is True, "Candidate is not public-state-only")
    require(
        replay["passed"] is True
        and replay["counts"]["shop_decisions"] == 403
        and replay["counts"]["applied_rows"] == 462
        and replay["interpretation"]["natural_outcomes_used_for_parameter_selection"] is False,
        "Assembled replay gate did not pass",
    )
    require(
        live_probe["passed"] is True
        and len(live_probe["probes"]) == 5
        and all(probe["max_unaffected_score_difference"] == 0 for probe in live_probe["probes"]),
        "Live policy probe gate did not pass",
    )
    jobs = allocation()
    validate_allocation(jobs)
    require(not OUT.exists(), "Never overwrite the paired evaluation")
    for job in jobs:
        require(not (modules["OUTPUT_ROOT"] / "outputs" / job["label"]).exists(), "Evaluation label exists")
    modules["build_policy"](
        "merchant-item-paired-preflight-control",
        control["solver_requested_config"],
        epsilon=0.0,
        model_path=CONTROL,
    )
    modules["build_policy"](
        "merchant-item-paired-preflight-candidate",
        control["solver_requested_config"],
        epsilon=0.0,
        model_path=CANDIDATE,
    )
    sources = []
    for root in (ADAPTER_ROOT, MERCHANT_ROOT, EVENT_ROOT, BRIDGE_ROOT):
        sources += list(root.glob("*.py")) + list(root.glob("*.json"))
    sources += list((MERCHANT_ROOT / "reference_facts").rglob("*"))
    sources += list((BRIDGE_ROOT.parent / "sts2-cli/lib").glob("*.dll"))
    sources += list((BRIDGE_ROOT / "runtime").rglob("*.dll"))
    sources += [BRIDGE_ROOT.parent / "BASE.json", CONTROL, CANDIDATE,
                REPLAY, LIVE_PROBE, Path(__file__), *[Path(item["path"]) for item in lineage]]
    frozen_by_path = {
        str(path.resolve()): file_evidence(path)
        for path in sources
        if path.is_file()
    }
    models = {"control": file_evidence(CONTROL), "candidate": file_evidence(CANDIDATE)}
    versions = {
        "control": modules["CONTROL_VERSION"],
        "candidate": modules["CANDIDATE_VERSION"],
    }
    bound_jobs = [
        dict(job, model=models[job["arm"]], expected_policy_id=versions[job["arm"]])
        for job in jobs
    ]
    protocol = {
        "schema_version": "merchant-item-paired-natural-evaluation-v1",
        "purpose": "Prospective paired natural evaluation of the complete source-bound merchant candidate chain",
        "planned_pairs": PAIRS,
        "planned_games": COUNT,
        "parallel_workers": 1,
        "jobs": bound_jobs,
        "models": models,
        "policy_ids": versions,
        "config": control["solver_requested_config"],
        "sampling": {
            "ascension": 10,
            "epsilon": 0.0,
            "max_seconds": 1200,
            "max_decisions": 500,
            "selection_budget": 256,
        },
        "arm_order": "Alternating by pair; identical seed within each pair",
        "first_pair_gate": "Both first-pair arms must pass integration audit; never retry",
        "assessment": "Actual Act3 first boss; invalid retained in denominator as failure",
        "improvement_gate": "Strictly more candidate-only target successes and exact one-sided paired p<=0.05",
        "smoke_gate_required": True,
        "natural_outcome_used_for_fit_or_selection": False,
        "no_refit_on_evaluation": True,
        "no_sample_extension": True,
        "automatic_retry": False,
        "automatic_deployment": False,
        "batch_raw_budget_bytes": 24 * 1024**3,
        "stop_when_free_below_bytes": 8 * 1024**3,
        "assembled_replay": file_evidence(REPLAY),
        "merchant_item_contract": contract,
        "candidate_parent_lineage": lineage,
        "live_policy_probe": file_evidence(LIVE_PROBE),
        "frozen_sources": [frozen_by_path[path] for path in sorted(frozen_by_path)],
    }
    OUT.mkdir(parents=True)
    write(OUT / "PROTOCOL.json", protocol, exclusive=True)
    write(
        OUT / "public-status.json",
        {"phase": "prepared_waiting_smoke_gate", "planned": COUNT, "completed": 0, "invalid": 0},
    )
    print(json.dumps({"prepared": True, "pairs": PAIRS, "games": COUNT}), flush=True)


def run():
    modules = runtime_modules()
    protocol = read(OUT / "PROTOCOL.json")
    smoke = read(Path("/home/ubuntu/sts2-merchant-item-smoke-20260918/run/RESULT.json"))
    require(smoke["passed"] is True and smoke["integration_passed"] is True, "Smoke gate failed")
    require(not (OUT / "STARTED.json").exists(), "Never restart paired evaluation")

    def unchanged():
        return all(file_evidence(item["path"]) == item for item in protocol["frozen_sources"])

    require(unchanged(), "Frozen source drift before evaluation")
    write(
        OUT / "STARTED.json",
        {"pid": os.getpid(), "at": time.time(), "automatic_retry": False},
        exclusive=True,
    )
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
            require(
                shutil.disk_usage(BRIDGE_ROOT).free > protocol["stop_when_free_below_bytes"],
                "Cloud disk below reserve",
            )
            raw_bytes = sum(
                path.stat().st_size
                for prior in protocol["jobs"]
                for path in (modules["OUTPUT_ROOT"] / "outputs" / prior["label"]).rglob("*")
                if path.is_file()
            )
            require(raw_bytes < protocol["batch_raw_budget_bytes"], "Raw budget reached")
            folder = modules["OUTPUT_ROOT"] / "outputs" / job["label"]
            require(not folder.exists(), "Never retry a paired seed arm")
            status("paired_natural_evaluation")
            report = modules["run_one"](
                job["label"],
                job["seed"],
                settings=protocol["config"],
                model_path=Path(job["model"]["path"]),
                **protocol["sampling"],
            )
            audit = modules["_Audit"](folder)
            records, _ = audit.run(report)
            traces = [json.loads(line) for line in (folder / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
            policy_rows = [json.loads(line) for line in (folder / "policy.jsonl").read_text(encoding="utf-8").splitlines()]
            policies = {row["decision_id"]: row for row in policy_rows}
            goal = modules["observed_progress"](traces, natural=True, expected_seed=job["seed"])
            issues = list(audit.issues) + list(goal["errors"])
            maps = merchant_packets = None
            try:
                require(len(policies) == len(policy_rows), "Duplicate policy ID")
                modules["validate_whole_run_choices"](records, policies)
                modules["validate_trace_observations"](records, policies, traces)
                maps = modules["verify_maps"](
                    records,
                    policies,
                    traces,
                    modules["policy_input"],
                    modules["validate_map_observation"],
                )
                modules["validate_merchant_lifecycle"](traces)
                modules["validate_previews"](traces)
                if job["arm"] == "candidate":
                    merchant_packets = modules["validate_merchant_packets"](
                        records,
                        policies,
                        job["expected_policy_id"],
                        protocol["merchant_item_contract"],
                    )
            except Exception:
                issues.append({
                    "reason": "explicit_choice_map_merchant_or_event_audit",
                    "detail": traceback.format_exc(),
                })
            manifest = read(folder / "manifest.json")
            runtime = list(manifest["versions"]["sources"].values()) + [
                value
                for key, value in manifest["versions"].items()
                if key != "sources" and value is not None
            ]
            bound = (
                manifest["provenance"]["policy_source"] == job["model"]
                and manifest["provenance"]["id"] == job["expected_policy_id"]
                and manifest["provenance"]["kind"] == "search"
                and manifest["provenance"]["origin"] == "natural"
                and not manifest["provenance"]["llm_involved"]
                and manifest["solver_requested_config"] == protocol["config"]
                and manifest["seed"] == job["seed"]
                and manifest["ascension"] == 10
                and manifest["character"] == "Defect"
                and all(file_evidence(item["path"]) == item for item in runtime)
                and unchanged()
            )
            valid = bool(
                bound and not issues and report["outcome"] in ("victory", "defeat")
            )
            receipt = {
                "run_id": job["label"],
                "seed": job["seed"],
                "pair": job["pair"],
                "position": job["position"],
                "arm": job["arm"],
                "report": report,
                "goal": goal,
                "issues": issues,
                "explicit_map_readback": maps,
                "merchant_policy_readback": merchant_packets,
                "policy_bound": bound,
                "integration_passed": valid,
                "invalid_failure_retained": not valid,
                "goal_success": bool(valid and goal["natural_goal_success"]),
                "evaluation_only": True,
                "natural_outcome_used_for_fit_or_selection": False,
                "refit_or_selection_eligible": False,
            }
            write(OUT / (job["label"] + "-audit.json"), receipt, exclusive=True)
            receipts.append(receipt)
            status("paired_natural_evaluation")
            if index == 1:
                require(
                    all(row["integration_passed"] for row in receipts),
                    "First pair failed audit; preserve and never retry",
                )
        require(unchanged(), "Frozen source drift at closure")
        result = comparison(receipts)
        write(OUT / "RESULT.json", result, exclusive=True)
        raw_sources = [
            file_evidence(path)
            for job in protocol["jobs"]
            for path in (modules["OUTPUT_ROOT"] / "outputs" / job["label"]).rglob("*")
            if path.is_file()
        ]
        write(
            OUT / "SOURCE_CLOSURE.json",
            {
                "passed": True,
                "games": COUNT,
                "protocol": file_evidence(OUT / "PROTOCOL.json"),
                "result": file_evidence(OUT / "RESULT.json"),
                "raw_sources": raw_sources,
                "invalid_failures_retained": sum(not row["integration_passed"] for row in receipts),
                "raw_originals_retained": True,
                "automatic_deployment": False,
            },
            exclusive=True,
        )
        status("complete")
    except BaseException:
        write(
            OUT / "RUNNER_ERROR.json",
            {"error": traceback.format_exc(), "completed": len(receipts), "automatic_retry": False},
            exclusive=True,
        )
        status("failed")
        raise


def main():
    require(len(sys.argv) == 2 and sys.argv[1] in ("prepare", "run"), "Use prepare or run")
    prepare() if sys.argv[1] == "prepare" else run()


if __name__ == "__main__":
    main()
