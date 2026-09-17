"""Read-only decision-structure diagnostics for audited CLab natural runs.

Natural outcomes are used only to stratify descriptive diagnostics.  This script
does not fit, select, edit, or deploy a policy and never treats score margins as
calibrated probabilities or causal effects.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import argparse
import hashlib
import json
from pathlib import Path
import statistics


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evidence(path):
    path = Path(path)
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def category(audit):
    goal = audit["goal"]
    if audit.get("integration_passed") and goal.get("natural_goal_success"):
        return "target_success"
    if (audit.get("integration_passed") and goal.get("max_act_observed") == 3 and
            (goal.get("max_floor_in_max_act") or 0) >= 15):
        return "near_target_failure"
    return "earlier_failure" if audit.get("integration_passed") else "invalid"


def decision_states(path):
    rows = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        packet = json.loads(line)
        decision_id = packet.get("decision_id")
        if decision_id and (decision_id not in rows or "execution" in packet):
            rows[decision_id] = packet
    return rows


def positive_names(mapping, prefix):
    return sorted(name for name, value in (mapping or {}).items()
                  if name.startswith(prefix) and isinstance(value, (int, float)) and value > 0)


def parse_run(audit_path, outputs):
    audit = read(audit_path)
    job = audit.get("job") or {}
    run_id = job.get("name") or audit.get("run_id")
    require(run_id, "Audit has no run id")
    folder = Path(outputs) / run_id
    policy_path, decisions_path = folder / "policy.jsonl", folder / "decisions.jsonl"
    require(policy_path.is_file() and decisions_path.is_file(), f"Decision evidence missing: {run_id}")
    states = decision_states(decisions_path)
    rows, versions = [], set()
    for line in policy_path.read_text(encoding="utf-8").splitlines():
        packet = json.loads(line)
        decision_id = packet["decision_id"]
        require(decision_id in states, f"Policy decision has no state: {decision_id}")
        scoring = packet["scoring"]
        scores = scoring["scores"]
        complete = scoring["evaluated_candidates_complete"] is True
        declared_count = scoring["candidate_count"]
        if complete:
            require(declared_count == len(scores) and scores, "Complete candidate space differs")
        else:
            require(scoring.get("candidate_space_representation") == "ordered_selection_implicit_v1" and
                    scoring.get("evaluated_candidate_count") == len(scores) and
                    declared_count > len(scores) > 0 and scoring.get("selection_search"),
                    "Truncated ordered-selection evidence differs")
        chosen = [row for row in scores if row["candidate_id"] == packet["candidate_id"]]
        require(len(chosen) == 1, "Chosen candidate missing or duplicated")
        chosen = chosen[0]
        alternatives = [row["score"] for row in scores if row["candidate_id"] != packet["candidate_id"]]
        margin = chosen["score"] - max(alternatives) if alternatives else None
        require(margin is None or margin >= -1e-9, "Chosen candidate was not score-maximal")
        guarded = any(abs(row["score"]) >= 1e90 for row in scores)
        if guarded:
            extreme = [row for row in scores if abs(row["score"]) >= 1e90]
            require(all(any(reason.get("source") == "known-event-nominal-cost-guard-v1" and
                            abs(reason.get("score", 0)) >= 1e90 for reason in row.get("reasons", []))
                        for row in extreme), "Extreme score lacks the nominal-cost guard evidence")
        state = states[decision_id].get("state") or {}
        context = state.get("context") or {}
        action = state.get("decision") or packet.get("request", {}).get("action") or packet["request"]["cmd"]
        features = chosen.get("features") or {}
        versions.add(scoring["policy_version"])
        rows.append({
            "run_id": run_id,
            "decision_id": decision_id,
            "category": category(audit),
            "action": action,
            "request_action": packet.get("request", {}).get("action"),
            "act": context.get("act"),
            "floor": context.get("floor"),
            "room_type": context.get("room_type"),
            "candidate_count": declared_count,
            "evaluated_candidate_count": len(scores),
            "candidate_space_complete": complete,
            "chosen_score": chosen["score"],
            "score_margin": margin,
            "guarded_sentinel_score": guarded,
            "is_skip": bool(chosen.get("is_skip")),
            "deck_size": features.get("deck_size"),
            "health_deficit": features.get("health_deficit"),
            "missing_hp": features.get("missing_hp"),
            "uncertainty": chosen.get("uncertainty"),
            "missing": sorted(chosen.get("missing") or []),
            "mechanisms": positive_names(features, "mechanism_"),
            "card_tags": positive_names(chosen.get("search_features"), "card_tag_"),
            "map_choice": positive_names(features, "map_"),
            "rest_choice": positive_names(features, "rest_"),
            "policy_version": scoring["policy_version"],
        })
    require(len(rows) == audit["report"]["decisions"], "Policy row count differs from audited report")
    return {
        "run_id": run_id,
        "category": category(audit),
        "max_act": audit["goal"].get("max_act_observed"),
        "max_floor": audit["goal"].get("max_floor_in_max_act"),
        "audit": evidence(audit_path),
        "policy": evidence(policy_path),
        "decisions": evidence(decisions_path),
        "policy_versions": sorted(versions),
        "rows": rows,
    }


def margin_metrics(rows):
    multi = [row for row in rows if row["score_margin"] is not None]
    numeric = [row for row in multi if not row["guarded_sentinel_score"]]
    margins = [row["score_margin"] for row in numeric]
    return {
        "decisions": len(rows),
        "multi_candidate_decisions": len(multi),
        "numeric_margin_decisions": len(numeric),
        "guarded_sentinel_decisions": len(multi) - len(numeric),
        "truncated_candidate_spaces": sum(not row["candidate_space_complete"] for row in rows),
        "ties": sum(abs(value) <= 1e-12 for value in margins),
        "margin_at_most_0_05": sum(value <= 0.05 + 1e-12 for value in margins),
        "margin_at_most_0_10": sum(value <= 0.10 + 1e-12 for value in margins),
        "margin_at_most_0_25": sum(value <= 0.25 + 1e-12 for value in margins),
        "margin_mean": statistics.fmean(margins) if margins else None,
        "margin_median": statistics.median(margins) if margins else None,
    }


def per_action(rows):
    result = {}
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["action"]].append(row)
    for action, selected in sorted(grouped.items()):
        result[action] = {
            **margin_metrics(selected),
            "skips": sum(row["is_skip"] for row in selected),
            "missing_signal_decisions": sum(bool(row["missing"]) for row in selected),
        }
    return result


def group_summary(runs):
    rows = [row for run in runs for row in run["rows"]]
    missing, mechanisms, tags, maps, rests, uncertainty = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()
    for row in rows:
        missing.update(row["missing"])
        mechanisms.update(row["mechanisms"])
        tags.update(row["card_tags"])
        maps.update(row["map_choice"])
        rests.update(row["rest_choice"])
        if row["uncertainty"]:
            uncertainty[row["uncertainty"]] += 1
    per_run = Counter(run["run_id"] for run in runs)
    return {
        "runs": len(runs),
        **margin_metrics(rows),
        "decisions_per_run_mean": statistics.fmean(per_run.values()) if per_run else None,
        "actions": per_action(rows),
        "missing_signal_counts": dict(missing.most_common()),
        "uncertainty_counts": dict(uncertainty.most_common()),
        "chosen_mechanism_counts": dict(mechanisms.most_common()),
        "chosen_card_tag_counts": dict(tags.most_common()),
        "chosen_map_type_counts": dict(maps.most_common()),
        "chosen_rest_action_counts": dict(rests.most_common()),
    }


def summarize(runs):
    by_category = {name: [run for run in runs if run["category"] == name]
                   for name in ("target_success", "near_target_failure", "earlier_failure", "invalid")}
    all_rows = [row for run in runs for row in run["rows"]]
    critical = [row for row in all_rows if row["category"] == "near_target_failure" and
                row["score_margin"] is not None and
                (row["score_margin"] <= 0.25 + 1e-12 or row["missing"])]
    critical.sort(key=lambda row: (row["score_margin"], row["run_id"], row["decision_id"]))
    # Keep a bounded, reproducible review queue; aggregate counts retain the full denominator.
    review = [{key: row[key] for key in (
        "run_id", "decision_id", "action", "request_action", "act", "floor", "room_type",
        "candidate_count", "evaluated_candidate_count", "candidate_space_complete",
        "chosen_score", "score_margin", "guarded_sentinel_score", "is_skip", "deck_size",
        "health_deficit", "missing_hp", "uncertainty", "missing", "mechanisms", "card_tags",
        "map_choice", "rest_choice", "policy_version")}
        for row in critical[:250]]
    versions = Counter(version for run in runs for version in run["policy_versions"])
    return {
        "schema_version": "cloud-natural-policy-decision-diagnostics-v1",
        "samples": len(runs),
        "category_counts": {name: len(selected) for name, selected in by_category.items()},
        "policy_versions_by_run": dict(versions),
        "all_audited": group_summary(runs),
        "by_category": {name: group_summary(selected) for name, selected in by_category.items()},
        "near_target_review_queue_total": len(critical),
        "near_target_review_queue_retained": len(review),
        "near_target_review_queue": review,
        "run_evidence": [{key: run[key] for key in (
            "run_id", "category", "max_act", "max_floor", "audit", "policy", "decisions",
            "policy_versions")} for run in runs],
        "interpretation": {
            "score_margin": "uncalibrated policy score gap, not probability or causal effect",
            "guarded_sentinel_score": "known nominal-cost safety guard; excluded from numeric margin summaries",
            "natural_outcomes_used_for_fitting": False,
            "candidate_selection_or_refit_performed": False,
            "running_model_modified": False,
            "review_queue_purpose": "prioritize new controlled branch acquisitions and feature coverage audits",
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sampling", type=Path, required=True)
    parser.add_argument("--goal", type=Path, required=True)
    parser.add_argument("--outputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audits = sorted(args.sampling.glob("*-audit.json")) + sorted(args.goal.glob("batches/*/*-audit.json"))
    runs = [parse_run(path, args.outputs) for path in audits]
    result = summarize(runs)
    atomic(args.output, result)
    compact = {
        "samples": result["samples"],
        "category_counts": result["category_counts"],
        "policy_versions_by_run": result["policy_versions_by_run"],
        "near_target_review_queue_total": result["near_target_review_queue_total"],
        "all_margin_metrics": {key: result["all_audited"][key] for key in (
            "decisions", "multi_candidate_decisions", "ties", "margin_at_most_0_10")},
    }
    print(json.dumps(compact, ensure_ascii=False))


if __name__ == "__main__":
    main()
