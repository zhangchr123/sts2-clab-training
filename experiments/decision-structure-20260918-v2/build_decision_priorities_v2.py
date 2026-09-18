"""Build a bounded controlled-acquisition plan from descriptive natural-run diagnostics."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path


AREA_SPECS = (
    ("event_effect_and_probability", "event_choice",
     ["known_events", "hidden_rewards", "crystal_sphere_minigame"],
     "new controlled event branches with explicit effects, costs, probabilities and terminal public outcomes"),
    ("ordered_card_selection_and_transform_effects", "card_select",
     ["selection_effects", "upgrade_instance_modifications", "transform_outcomes"],
     "new controlled ordered-selection branches retaining evaluated-subset search receipts"),
    ("route_damage_and_full_path_evaluation", "map_select",
     ["encounter_damage_distribution", "full_route_evaluation"],
     "new route branch acquisitions with encounter distributions and downstream path summaries"),
    ("card_reward_mechanism_and_current_stats", "card_reward",
     ["mechanism_coverage", "current_card_stats", "energy_effect_semantics"],
     "controlled reward gates emphasizing functional substitutes, rarity and current-cost semantics"),
    ("rest_heal_and_future_route_damage", "rest_site",
     ["actual_rest_heal_amount", "future_route_damage_distribution"],
     "controlled rest-versus-smith gates with actual heal and downstream damage evidence"),
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def evidence(path):
    path = Path(path)
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def build(result, source):
    require(result["schema_version"] == "cloud-natural-policy-decision-diagnostics-v1", "Result schema differs")
    counts = result["category_counts"]
    require(sum(counts.values()) == result["samples"], "Category denominator differs")
    require(result["interpretation"]["natural_outcomes_used_for_fitting"] is False, "Natural outcomes entered fitting")
    near = result["by_category"]["near_target_failure"]
    actions = near["actions"]
    priorities = []
    for rank, (area, action, subsystems, next_evidence) in enumerate(AREA_SPECS, 1):
        row = actions.get(action, {})
        priorities.append({
            "rank": rank,
            "area": area,
            "near_target_decisions": row.get("decisions", 0),
            "missing_signal_decisions": row.get("missing_signal_decisions", 0),
            "margin_at_most_0_10": row.get("margin_at_most_0_10", 0),
            "include_subsystems": subsystems,
            "next_evidence": next_evidence,
        })
    late = [
        row for row in result["near_target_review_queue"]
        if row.get("act") == 3 and (row.get("floor") or 0) >= 10
    ]
    return {
        "schema_version": "cloud-controlled-acquisition-priorities-v2",
        "source": source,
        "audited_natural_runs": result["samples"],
        "target_successes": counts["target_success"],
        "near_target_failures": counts["near_target_failure"],
        "earlier_failures": counts["earlier_failure"],
        "invalid_runs": counts["invalid"],
        "late_act3_review_decisions": len(late),
        "late_act3_review_actions": dict(Counter(row["action"] for row in late)),
        "near_target_review_queue_total": result["near_target_review_queue_total"],
        "near_target_review_queue_retained": result["near_target_review_queue_retained"],
        "priorities": priorities,
        "interpretation": {
            "descriptive_not_causal": True,
            "natural_outcomes_used_for_fitting": False,
            "candidate_selection_or_refit_performed": False,
            "running_model_modified": False,
            "score_margins_are_probabilities": False,
            "purpose": "prioritize new controlled branch acquisition and public feature coverage work",
        },
    }


def report(plan, result):
    margins = result["all_audited"]
    areas = "、".join(row["area"] for row in plan["priorities"])
    return (
        "# CLab 自然局决策结构诊断 v2\n\n"
        f"冻结快照覆盖 {plan['audited_natural_runs']} 局鸡煲 A10 自然局："
        f"{plan['target_successes']} 局击败第三幕首个 Boss，"
        f"{plan['near_target_failures']} 局到达目标附近但未通过，"
        f"{plan['earlier_failures']} 局更早失败，{plan['invalid_runs']} 局无效并保留。\n\n"
        f"共核验 {margins['decisions']} 个策略决策；"
        f"{margins['multi_candidate_decisions']} 个为多候选决策，"
        f"其中 {margins['margin_at_most_0_10']} 个未校准分差不超过 0.10。"
        "分差不是概率或因果效应；自然结局只用于描述分层，没有进入拟合、选模或部署。\n\n"
        f"近目标复核队列共有 {plan['near_target_review_queue_total']} 个决策，"
        f"结果文件保留稳定排序的 {plan['near_target_review_queue_retained']} 个；"
        f"其中第三幕第 10 层及以后有 {plan['late_act3_review_decisions']} 个。"
        f"下一轮受控采样重点依次为：{areas}。\n"
    )


def main():
    base = Path(__file__).resolve().parent
    result_path = base / "RESULT.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    plan = build(result, evidence(result_path))
    (base / "PRIORITIES.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (base / "REPORT.md").write_text(report(plan, result), encoding="utf-8")
    print(json.dumps({
        "audited_natural_runs": plan["audited_natural_runs"],
        "target_successes": plan["target_successes"],
        "near_target_failures": plan["near_target_failures"],
        "late_act3_review_decisions": plan["late_act3_review_decisions"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
