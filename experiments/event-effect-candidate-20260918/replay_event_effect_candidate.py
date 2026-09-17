"""Replay a fixed event-effect score extension on audited policy evidence.

This changes no recorded action or model.  Outcome categories are used only to
stratify diagnostics; they never fit or select the fixed expert prior.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import argparse
import hashlib
import json
from pathlib import Path
import statistics
from typing import Any

from decision_data import enumerate_candidates, materialize_candidate
from event_effect_features import CONTRACT, PARAMETERS, PRIOR, features, score


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def evidence(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def category(audit: dict[str, Any]) -> str:
    goal = audit.get("goal") or {}
    if audit.get("integration_passed") and goal.get("natural_goal_success"):
        return "target_success"
    if (
        audit.get("integration_passed")
        and goal.get("max_act_observed") == 3
        and (goal.get("max_floor_in_max_act") or 0) >= 15
    ):
        return "near_target_failure"
    return "earlier_failure" if audit.get("integration_passed") else "invalid"


def load_audits(roots: list[Path]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    result: dict[str, dict[str, Any]] = {}
    sources: list[dict[str, Any]] = []
    for root in roots:
        for path in sorted(root.rglob("*-audit.json")):
            audit = read(path)
            run_id = (audit.get("job") or {}).get("name") or audit.get("run_id")
            require(run_id, f"Audit lacks run id: {path}")
            if run_id in result:
                require(result[run_id] == audit, f"Conflicting audit: {run_id}")
                continue
            result[run_id] = audit
            sources.append(evidence(path))
    return result, sources


def jsonl_map(path: Path, *, prefer_execution: bool = False) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        decision_id = row.get("decision_id")
        if not decision_id:
            continue
        if decision_id not in result or (prefer_execution and "execution" in row):
            result[decision_id] = row
        elif not prefer_execution:
            require(False, f"Duplicate policy decision: {decision_id}")
    return result


def greedy_ids(rows: list[dict[str, Any]], key: str) -> set[str]:
    best = max(row[key] for row in rows)
    return {row["candidate_id"] for row in rows if abs(row[key] - best) <= 1e-12}


def compare_decision(
    state: dict[str, Any], policy: dict[str, Any], candidates: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    rows = []
    chosen_id = policy.get("candidate_id")
    for original in policy.get("scoring", {}).get("scores") or []:
        candidate = candidates.get(original.get("candidate_id"))
        require(candidate is not None, "Policy candidate is absent from fresh enumeration")
        values, detail = features(state, original, candidate)
        adjustment = score(values)
        old_score = original.get("score")
        require(type(old_score) in (int, float), "Policy score is not numeric")
        rows.append(
            {
                "candidate_id": original["candidate_id"],
                "request": original["request"],
                "text_key": candidate["evidence"].get("text_key"),
                "old_score": old_score,
                "adjustment": adjustment,
                "new_score": old_score + adjustment,
                "features": {name: value for name, value in values.items() if value},
                "detail": detail,
            }
        )
    require(rows and any(row["candidate_id"] == chosen_id for row in rows), "Chosen candidate missing")
    old_greedy = greedy_ids(rows, "old_score")
    new_greedy = greedy_ids(rows, "new_score")
    return {
        "chosen_id": chosen_id,
        "old_greedy": sorted(old_greedy),
        "new_greedy": sorted(new_greedy),
        "greedy_set_changed": old_greedy != new_greedy,
        "chosen_was_old_greedy": chosen_id in old_greedy,
        "chosen_remains_new_greedy": chosen_id in new_greedy,
        "old_uniform": len(old_greedy) == len(rows),
        "new_uniform": len(new_greedy) == len(rows),
        "rows": rows,
    }


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    old_sizes = [len(row["comparison"]["old_greedy"]) for row in rows]
    new_sizes = [len(row["comparison"]["new_greedy"]) for row in rows]
    effect_counts = Counter(
        name
        for row in rows
        for candidate in row["comparison"]["rows"]
        for name, value in candidate["features"].items()
        if value and name != "event_effect_unknown"
    )
    return {
        "decisions": len(rows),
        "old_uniform": sum(row["comparison"]["old_uniform"] for row in rows),
        "new_uniform": sum(row["comparison"]["new_uniform"] for row in rows),
        "greedy_set_changed": sum(row["comparison"]["greedy_set_changed"] for row in rows),
        "recorded_choice_no_longer_greedy": sum(
            not row["comparison"]["chosen_remains_new_greedy"] for row in rows
        ),
        "old_greedy_size_mean": statistics.fmean(old_sizes) if old_sizes else None,
        "new_greedy_size_mean": statistics.fmean(new_sizes) if new_sizes else None,
        "feature_instance_counts": dict(effect_counts.most_common()),
    }


def analyze(outputs: Path, audit_roots: list[Path]) -> dict[str, Any]:
    audits, audit_sources = load_audits(audit_roots)
    rows: list[dict[str, Any]] = []
    run_sources: list[dict[str, Any]] = []
    invalid = 0
    missing: list[str] = []
    for run_id, audit in sorted(audits.items()):
        run_category = category(audit)
        if run_category == "invalid":
            invalid += 1
            continue
        decision_path = outputs / run_id / "decisions.jsonl"
        policy_path = outputs / run_id / "policy.jsonl"
        if not decision_path.is_file() or not policy_path.is_file():
            missing.append(run_id)
            continue
        run_sources.extend((evidence(decision_path), evidence(policy_path)))
        states = jsonl_map(decision_path, prefer_execution=True)
        policies = jsonl_map(policy_path)
        for decision_id, packet in policies.items():
            state_packet = states.get(decision_id)
            require(state_packet is not None, f"Policy decision has no state: {decision_id}")
            state = state_packet.get("state") or {}
            if state.get("decision") != "event_choice":
                continue
            space = enumerate_candidates(state)
            require(space.get("complete") is True, "Event candidate space must be complete")
            candidate_map = {candidate["candidate_id"]: candidate for candidate in space["candidates"]}
            comparison = compare_decision(state, packet, candidate_map)
            rows.append(
                {
                    "run_id": run_id,
                    "decision_id": decision_id,
                    "category": run_category,
                    "act": (state.get("context") or {}).get("act"),
                    "floor": (state.get("context") or {}).get("floor"),
                    "event_name": state.get("event_name"),
                    "comparison": comparison,
                }
            )

    by_category = {
        name: summary([row for row in rows if row["category"] == name])
        for name in ("target_success", "near_target_failure", "earlier_failure")
    }
    review = [row for row in rows if row["comparison"]["greedy_set_changed"]]
    review.sort(key=lambda row: (row["category"], row["run_id"], row["decision_id"]))
    return {
        "schema_version": "event-effect-offline-replay-v1",
        "contract": CONTRACT,
        "parameters": list(PARAMETERS),
        "fixed_expert_prior": PRIOR,
        "runs": {"audits": len(audits), "invalid_excluded": invalid, "missing_outputs": missing},
        "all": summary(rows),
        "by_category": by_category,
        "changed_review_total": len(review),
        "changed_review": review[:250],
        "sources": {"audits": audit_sources, "decision_and_policy_files": run_sources},
        "interpretation": {
            "recorded_actions_changed": False,
            "natural_outcomes_used_for_fitting_or_weight_selection": False,
            "new_scores_executed_in_game": False,
            "win_rate_claimed": False,
            "purpose": "contract and decision-impact audit before a separately predeclared paired run",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outputs", type=Path, required=True)
    parser.add_argument("--audits", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.outputs, args.audits)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({"all": result["all"], "by_category": result["by_category"]}, indent=2))


if __name__ == "__main__":
    main()
