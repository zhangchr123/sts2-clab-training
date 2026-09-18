"""One-shot natural integration smoke for the source-bound merchant wrapper.

This is an integration gate only.  It never retries the allocated seed, fits
from the outcome, selects a model, extends the denominator, or deploys the
candidate.
"""
from __future__ import annotations

import hashlib
import json
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
BASE = Path(os.environ.get(
    "STS2_MERCHANT_SMOKE_BASE",
    "/home/ubuntu/sts2-merchant-item-smoke-20260918",
))
OUT = BASE / "run"
MODEL = MERCHANT_ROOT / "models-merchant-item-v1/merchant-item-candidate-model.json"
REPLAY = MERCHANT_ROOT / "models-merchant-item-v1/MERCHANT_ITEM_POLICY_REPLAY.json"
LIVE_PROBE = MERCHANT_ROOT / "models-merchant-item-v1/MERCHANT_ITEM_LIVE_POLICY_PROBE.json"
LABEL = "defect-merchant-item-smoke-20260918-000"
SEED = "defect-merchant-item-smoke-20260918-fresh-000"


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


def runtime_modules():
    sys.path[:0] = [str(path) for path in (
        ADAPTER_ROOT, MERCHANT_ROOT, EVENT_ROOT, BRIDGE_ROOT
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
    from persistent_acquisition_policy import require_parent_integration
    from merchant_item_policy import VERSION, source_files
    from probe import ROOT as OUTPUT_ROOT
    return locals()


def verify_maps(records, policies, traces, policy_input, validate_map_observation):
    before = []
    current = {"type": "initializing"}
    for trace in traces:
        before.append(current)
        response = trace.get("response")
        if isinstance(response, dict) and (
            response.get("type") == "decision"
            or (
                trace["request"]["cmd"] in ("action", "start_run")
                and response.get("type") == "error"
            )
        ):
            current = response
    used, cursor = [], 0
    for record in records:
        packet, state = policies[record["decision_id"]], record["state"]
        if state.get("decision") != "map_select":
            require("map_observation" not in packet, "Map evidence on non-map decision")
            continue
        index = next(
            (
                i
                for i in range(cursor, len(traces))
                if before[i] == state
                and traces[i]["request"] == record["chosen"]["request"]
            ),
            None,
        )
        require(index is not None and index > 0, "Missing original map action")
        query = index - 1
        require(before[query] == state, "Map query current state differs")
        observation = packet["map_observation"]
        validate_map_observation(state, observation, traces[query])
        require(
            packet["scoring"]["public_route_input"] == policy_input(state, observation),
            "Map scoring input differs",
        )
        used.append(query)
        cursor = index + 1
    require(
        used
        == [i for i, trace in enumerate(traces) if trace["request"]["cmd"] == "get_map"],
        "Unaccounted map query",
    )
    return {"passed": True, "map_queries": len(used)}


def validate_merchant_packets(records, policies, version, contract):
    shop_decisions = 0
    applied_rows = 0
    nonzero_adjusted_rows = 0
    for record in records:
        scoring = policies[record["decision_id"]]["scoring"]
        require(scoring["policy_id"] == version, "Decision did not use merchant wrapper")
        require(scoring["merchant_item_contract"] == contract, "Merchant contract differs")
        shop_decisions += record["state"].get("decision") == "shop"
        for row in scoring["scores"]:
            require("merchant_item_adjustment" in row, "Merchant adjustment missing")
            require("merchant_item_detail" in row, "Merchant detail missing")
            detail = row["merchant_item_detail"]
            if detail.get("applied"):
                require(detail["natural_outcomes_used"] is False, "Natural outcome leak")
                require(detail["hidden_runtime_state_used"] is False, "Hidden runtime state leak")
                require(record["state"].get("decision") == "shop", "Merchant item applied outside shop")
                applied_rows += 1
                nonzero_adjusted_rows += row["merchant_item_adjustment"] != 0
            else:
                require(row["merchant_item_adjustment"] == 0, "Unapplied merchant row changed score")
                require(detail.get("reason") in ("not_merchant_item", "unsupported_item"),
                        "Unexplained merchant candidate")
        require(scoring["merchant_item_applied_rows"] == sum(
            bool(row["merchant_item_detail"].get("applied")) for row in scoring["scores"]
        ), "Merchant applied-row count differs")
    return {
        "passed": True,
        "shop_decisions": shop_decisions,
        "applied_rows": applied_rows,
        "nonzero_adjusted_rows": nonzero_adjusted_rows,
    }


def prepare():
    modules = runtime_modules()
    modules["require_parent_integration"]()
    candidate = read(MODEL)
    replay = read(REPLAY)
    live_probe = read(LIVE_PROBE)
    require(candidate["format"] == modules["VERSION"], "Candidate format differs")
    require(candidate["automatic_deployment"] is False, "Candidate permits deployment")
    require(candidate["source_files"] == modules["source_files"](), "Source closure differs")
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
    require(not OUT.exists(), "Never overwrite the one-shot smoke allocation")
    require(not (modules["OUTPUT_ROOT"] / "outputs" / LABEL).exists(), "Smoke label already exists")
    modules["build_policy"](
        "merchant-item-smoke-preflight",
        candidate["solver_requested_config"],
        epsilon=0.0,
        model_path=MODEL,
    )
    sources = []
    for root in (ADAPTER_ROOT, MERCHANT_ROOT, EVENT_ROOT, BRIDGE_ROOT):
        sources += list(root.glob("*.py")) + list(root.glob("*.json"))
    sources += list((MERCHANT_ROOT / "reference_facts").rglob("*"))
    sources += list((BRIDGE_ROOT.parent / "sts2-cli/lib").glob("*.dll"))
    sources += list((BRIDGE_ROOT / "runtime").rglob("*.dll"))
    sources += [BRIDGE_ROOT.parent / "BASE.json", MODEL,
                Path(candidate["parent_model"]["path"]), REPLAY, LIVE_PROBE, Path(__file__)]
    frozen_by_path = {
        str(path.resolve()): file_evidence(path)
        for path in sources
        if path.is_file()
    }
    protocol = {
        "schema_version": "merchant-item-one-shot-integration-smoke-v1",
        "purpose": "One fresh Defect A10 natural integration gate for the source-bound merchant wrapper",
        "job": {
            "label": LABEL,
            "seed": SEED,
            "model": file_evidence(MODEL),
        },
        "config": candidate["solver_requested_config"],
        "sampling": {
            "ascension": 10,
            "epsilon": 0.0,
            "max_seconds": 1200,
            "max_decisions": 500,
            "selection_budget": 256,
        },
        "integration_gate_only": True,
        "natural_outcome_used_for_fit_or_selection": False,
        "refit_or_selection_eligible": False,
        "automatic_retry": False,
        "automatic_deployment": False,
        "sample_extension": False,
        "parallel_workers": 1,
        "batch_raw_budget_bytes": 2 * 1024**3,
        "stop_when_free_below_bytes": 8 * 1024**3,
        "assembled_replay": file_evidence(REPLAY),
        "merchant_item_contract": contract,
        "live_policy_probe": file_evidence(LIVE_PROBE),
        "frozen_sources": [frozen_by_path[path] for path in sorted(frozen_by_path)],
    }
    OUT.mkdir(parents=True)
    write(OUT / "PROTOCOL.json", protocol, exclusive=True)
    write(
        OUT / "public-status.json",
        {"phase": "prepared", "planned": 1, "completed": 0, "invalid": 0},
    )
    print(json.dumps({"prepared": True, "games": 1, "label": LABEL}), flush=True)


def run():
    modules = runtime_modules()
    protocol = read(OUT / "PROTOCOL.json")
    require(not (OUT / "STARTED.json").exists(), "Never restart the smoke allocation")

    def unchanged():
        return all(file_evidence(item["path"]) == item for item in protocol["frozen_sources"])

    require(unchanged(), "Frozen source drift before smoke")
    job = protocol["job"]
    folder = modules["OUTPUT_ROOT"] / "outputs" / job["label"]
    require(not folder.exists(), "Never retry the smoke seed")
    require(shutil.disk_usage(BRIDGE_ROOT).free > protocol["stop_when_free_below_bytes"], "Cloud disk below reserve")
    write(
        OUT / "STARTED.json",
        {"pid": os.getpid(), "at": time.time(), "automatic_retry": False},
        exclusive=True,
    )
    write(
        OUT / "public-status.json",
        {"phase": "natural_integration_smoke", "planned": 1, "completed": 0, "invalid": 0},
    )
    try:
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
            maps = verify_maps(
                records,
                policies,
                traces,
                modules["policy_input"],
                modules["validate_map_observation"],
            )
            modules["validate_merchant_lifecycle"](traces)
            modules["validate_previews"](traces)
            merchant_packets = validate_merchant_packets(
                records,
                policies,
                modules["VERSION"],
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
            and manifest["provenance"]["id"] == modules["VERSION"]
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
            "report": report,
            "goal": goal,
            "issues": issues,
            "explicit_map_readback": maps,
            "merchant_policy_readback": merchant_packets,
            "policy_bound": bound,
            "integration_passed": valid,
            "invalid_failure_retained": not valid,
            "goal_success": bool(valid and goal["natural_goal_success"]),
            "integration_gate_only": True,
            "natural_outcome_used_for_fit_or_selection": False,
            "refit_or_selection_eligible": False,
            "automatic_deployment": False,
        }
        write(OUT / "AUDIT.json", receipt, exclusive=True)
        result = {
            "passed": valid,
            "games": 1,
            "integration_passed": valid,
            "goal_success_observed": receipt["goal_success"],
            "shop_decisions": (merchant_packets or {}).get("shop_decisions", 0),
            "merchant_applied_rows": (merchant_packets or {}).get("applied_rows", 0),
            "performance_improvement_claimed": False,
            "candidate_selected": False,
            "automatic_deployment": False,
            "automatic_retry": False,
        }
        write(OUT / "RESULT.json", result, exclusive=True)
        raw_sources = [
            file_evidence(path) for path in folder.rglob("*") if path.is_file()
        ]
        write(
            OUT / "SOURCE_CLOSURE.json",
            {
                "passed": valid,
                "games": 1,
                "protocol": file_evidence(OUT / "PROTOCOL.json"),
                "result": file_evidence(OUT / "RESULT.json"),
                "raw_sources": raw_sources,
                "raw_originals_retained": True,
                "automatic_deployment": False,
            },
            exclusive=True,
        )
        write(
            OUT / "public-status.json",
            {"phase": "complete" if valid else "failed", "planned": 1, "completed": 1, "invalid": 0 if valid else 1},
        )
        require(valid, "Merchant-item smoke failed integration audit")
    except BaseException:
        if not (OUT / "RUNNER_ERROR.json").exists():
            write(
                OUT / "RUNNER_ERROR.json",
                {"error": traceback.format_exc(), "automatic_retry": False},
                exclusive=True,
            )
        write(
            OUT / "public-status.json",
            {"phase": "failed", "planned": 1, "completed": int((OUT / "AUDIT.json").exists()), "invalid": 1},
        )
        raise


def main():
    require(len(sys.argv) == 2 and sys.argv[1] in ("prepare", "run"), "Use prepare or run")
    prepare() if sys.argv[1] == "prepare" else run()


if __name__ == "__main__":
    main()
