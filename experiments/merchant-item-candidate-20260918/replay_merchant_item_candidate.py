"""Replay the frozen 95-run public corpus without using outcomes for selection."""
from __future__ import annotations

from collections import Counter
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

from decision_data import enumerate_candidates
import merchant_item_features
from run_metadata import file_evidence


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def completed_states(path):
    return {row["decision_id"]: row["state"] for row in read_jsonl(path)
            if row.get("record_type") == "decision_completed"}


def greedy_ids(rows):
    top = max(float(row["score"]) for row in rows)
    return {row["candidate_id"] for row in rows if abs(float(row["score"]) - top) <= 1e-12}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gap-result", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    gap = json.loads(Path(args.gap_result).read_text(encoding="utf-8"))
    sources = gap["sources"]["runs"]
    if len(sources) != 95:
        raise RuntimeError("Frozen replay requires exactly 95 clean runs")
    counts = Counter()
    by_action = Counter()
    by_item = Counter()
    changed_examples = []
    maximum = 0.0
    for source in sources:
        states = completed_states(source["decisions"]["path"])
        policies = read_jsonl(source["policy"]["path"])
        if len(states) != len(policies):
            raise RuntimeError("Frozen decision sequence differs")
        for recorded in policies:
            state = states[recorded["decision_id"]]
            if state.get("decision") != "shop":
                continue
            space = enumerate_candidates(state)
            if space.get("representation") == "ordered_selection_implicit_v1":
                continue
            candidates = {row["candidate_id"]: row for row in space["candidates"]}
            packet = recorded.get("scoring") or {}
            rows = packet.get("scores") or []
            if not rows or any(row["candidate_id"] not in candidates for row in rows):
                raise RuntimeError("Frozen score/candidate binding differs")
            before = greedy_ids(rows)
            adjusted = merchant_item_features.adjust(state, packet, candidates)
            after_rows = adjusted["scores"]
            after = greedy_ids(after_rows)
            counts["shop_decisions"] += 1
            counts["applied_rows"] += adjusted["merchant_item_applied_rows"]
            counts["changed_greedy_decisions"] += int(before != after)
            for row in after_rows:
                adjustment = float(row["merchant_item_adjustment"])
                if not math.isfinite(adjustment):
                    raise RuntimeError("Nonfinite merchant adjustment")
                maximum = max(maximum, abs(adjustment))
                detail = row["merchant_item_detail"]
                if not detail.get("applied"):
                    continue
                action = row["request"]["action"]
                item_id = detail["item_id"]
                by_action[action + ":applied"] += 1
                by_item[action + ":" + item_id + ":applied"] += 1
                if row["score"] > 0:
                    by_action[action + ":positive"] += 1
                    by_item[action + ":" + item_id + ":positive"] += 1
                if row["candidate_id"] in after:
                    by_action[action + ":greedy"] += 1
                    by_item[action + ":" + item_id + ":greedy"] += 1
                if "item_effect_model" in (row.get("missing") or []) or (
                    action == "discard_potion" and "potion_replacement_utility" in (row.get("missing") or [])
                ):
                    raise RuntimeError("Covered merchant marker was not cleared")
            if before != after and len(changed_examples) < 40:
                changed_examples.append({
                    "run_id": source["run_id"],
                    "decision_id": recorded["decision_id"],
                    "act": (state.get("context") or {}).get("act"),
                    "floor": (state.get("context") or {}).get("floor"),
                    "before": sorted(before),
                    "after": sorted(after),
                    "after_actions": [row["request"] for row in after_rows
                                      if row["candidate_id"] in after],
                })
    for required in ("buy_relic", "buy_potion"):
        if by_action[required + ":greedy"] <= 0:
            raise RuntimeError(f"Candidate never makes {required} greedy")
    if maximum > merchant_item_features.CONTRACT["candidate_adjustment_abs_cap"] + 1e-12:
        raise RuntimeError("Merchant replay exceeded cap")
    result = {
        "schema_version": "merchant-item-policy-replay-v1",
        "passed": True,
        "interpretation": {
            "natural_outcomes_used_for_parameter_selection": False,
            "frozen_states_and_parent_scores_used": True,
            "candidate_selected_before_replay": True,
            "automatic_deployment": False,
        },
        "sources": {
            "gap_result": file_evidence(Path(args.gap_result).resolve()),
            "runs": sources,
            "merchant_item_facts": file_evidence(merchant_item_features.FACTS_PATH),
        },
        "counts": dict(counts),
        "by_action": dict(sorted(by_action.items())),
        "by_item": dict(sorted(by_item.items())),
        "maximum_absolute_adjustment": maximum,
        "contract": merchant_item_features.CONTRACT,
        "changed_examples": changed_examples,
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                      encoding="utf-8")
    print(json.dumps({"output": str(output), "counts": result["counts"],
                      "by_action": result["by_action"],
                      "maximum_absolute_adjustment": maximum}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

