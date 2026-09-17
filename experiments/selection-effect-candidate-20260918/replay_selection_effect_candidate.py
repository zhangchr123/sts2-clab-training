"""Replay fixed public upgrade-preview utility on audited natural decisions.

Recorded actions and outcomes are immutable.  Outcome categories are used only
for diagnostic strata; they do not fit or select the fixed expert prior.
"""

from __future__ import annotations

from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import statistics
from typing import Any

from decision_data import enumerate_candidates, materialize_candidate
from selection_effect_features import CONTRACT, PARAMETERS, PRIOR, candidate_features, score


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
            require(bool(run_id), f"Audit lacks run id: {path}")
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


def candidates_for_scoring(state: dict[str, Any], scoring: dict[str, Any]) -> dict[str, dict[str, Any]]:
    space = enumerate_candidates(state)
    require(space.get("complete") is True, "Upgrade candidate space must be complete")
    explicit = None
    if space.get("representation") != "ordered_selection_implicit_v1":
        explicit = {candidate["candidate_id"]: candidate for candidate in space["candidates"]}
    result: dict[str, dict[str, Any]] = {}
    for row in scoring.get("scores") or []:
        candidate = (
            materialize_candidate(space, row.get("request"))
            if explicit is None
            else explicit.get(row.get("candidate_id"))
        )
        require(candidate is not None, "Scored upgrade candidate is absent from fresh enumeration")
        require(candidate.get("candidate_id") == row.get("candidate_id"), "Upgrade candidate id differs")
        require(candidate.get("request") == row.get("request"), "Upgrade candidate request differs")
        result[candidate["candidate_id"]] = candidate
    return result


def greedy_ids(rows: list[dict[str, Any]], key: str) -> set[str]:
    best = max(row[key] for row in rows)
    return {row["candidate_id"] for row in rows if abs(row[key] - best) <= 1e-12}


def top_margin(rows: list[dict[str, Any]], key: str) -> float:
    values = sorted((row[key] for row in rows), reverse=True)
    return values[0] - values[1] if len(values) > 1 else 0.0


def compare_decision(
    policy: dict[str, Any], scoring: dict[str, Any], candidates: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    chosen_id = policy.get("candidate_id")
    for original in scoring.get("scores") or []:
        candidate = candidates.get(original.get("candidate_id"))
        require(candidate is not None, "Fresh upgrade candidate missing")
        values, details = candidate_features(candidate)
        adjustment = score(values)
        old_score = original.get("score")
        require(type(old_score) in (int, float), "Upgrade score is not numeric")
        new_score = old_score + adjustment
        rows.append(
            {
                "candidate_id": original["candidate_id"],
                "request": original["request"],
                "card_ids": [card.get("card_id") for card in details],
                "old_score": old_score,
                "adjustment": adjustment,
                "new_score": new_score,
                "features": {name: value for name, value in values.items() if value},
                "details": details,
                "exact_additivity": abs(new_score - (old_score + adjustment)) <= 1e-12,
            }
        )
    require(rows and any(row["candidate_id"] == chosen_id for row in rows), "Chosen upgrade missing")
    require(all(row["exact_additivity"] for row in rows), "Upgrade score is not exactly additive")
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
        "old_top_margin": top_margin(rows, "old_score"),
        "new_top_margin": top_margin(rows, "new_score"),
        "rows": rows,
    }


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    old_sizes = [len(row["comparison"]["old_greedy"]) for row in rows]
    new_sizes = [len(row["comparison"]["new_greedy"]) for row in rows]
    old_margins = [row["comparison"]["old_top_margin"] for row in rows]
    new_margins = [row["comparison"]["new_top_margin"] for row in rows]
    feature_counts = Counter(
        name
        for row in rows
        for candidate in row["comparison"]["rows"]
        for name, value in candidate["features"].items()
        if value
    )
    chosen_cards = Counter(
        card_id
        for row in rows
        for candidate in row["comparison"]["rows"]
        if candidate["candidate_id"] == row["comparison"]["chosen_id"]
        for card_id in candidate["card_ids"]
        if card_id
    )
    return {
        "decisions": len(rows),
        "candidate_rows": sum(len(row["comparison"]["rows"]) for row in rows),
        "exact_additivity_decisions": sum(
            all(candidate["exact_additivity"] for candidate in row["comparison"]["rows"])
            for row in rows
        ),
        "old_uniform": sum(row["comparison"]["old_uniform"] for row in rows),
        "new_uniform": sum(row["comparison"]["new_uniform"] for row in rows),
        "greedy_set_changed": sum(row["comparison"]["greedy_set_changed"] for row in rows),
        "recorded_choice_no_longer_greedy": sum(
            not row["comparison"]["chosen_remains_new_greedy"] for row in rows
        ),
        "old_greedy_size_mean": statistics.fmean(old_sizes) if old_sizes else None,
        "new_greedy_size_mean": statistics.fmean(new_sizes) if new_sizes else None,
        "old_top_margin_median": statistics.median(old_margins) if old_margins else None,
        "new_top_margin_median": statistics.median(new_margins) if new_margins else None,
        "feature_instance_counts": dict(feature_counts.most_common()),
        "recorded_choice_card_counts": dict(chosen_cards.most_common()),
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
        for decision_id, policy in policies.items():
            scoring = policy.get("scoring") or {}
            if scoring.get("selection_purpose") != "upgrade":
                continue
            state_packet = states.get(decision_id)
            require(state_packet is not None, f"Upgrade policy decision has no state: {decision_id}")
            state = state_packet.get("state") or {}
            require(state.get("decision") == "card_select", "Upgrade purpose has wrong decision type")
            candidates = candidates_for_scoring(state, scoring)
            comparison = compare_decision(policy, scoring, candidates)
            rows.append(
                {
                    "run_id": run_id,
                    "decision_id": decision_id,
                    "category": run_category,
                    "act": (state.get("context") or {}).get("act"),
                    "floor": (state.get("context") or {}).get("floor"),
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
        "schema_version": "selection-effect-offline-replay-v1",
        "contract": CONTRACT,
        "parameters": list(PARAMETERS),
        "fixed_expert_prior": PRIOR,
        "runs": {"audits": len(audits), "invalid_excluded": invalid, "missing_outputs": missing},
        "all": summary(rows),
        "by_category": by_category,
        "changed_review_total": len(review),
        "changed_review": review,
        "sources": {"audits": audit_sources, "decision_and_policy_files": run_sources},
        "interpretation": {
            "recorded_actions_changed": False,
            "natural_outcomes_used_for_fitting_or_weight_selection": False,
            "new_scores_executed_in_game": False,
            "win_rate_claimed": False,
            "purpose": "upgrade-preview contract and score-impact audit before prospective evaluation",
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
