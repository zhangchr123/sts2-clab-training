"""Read-only structural analysis of completed CLab Defect natural samples."""
from __future__ import annotations

from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import statistics


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


def deck_from_state(state):
    player = state.get("player") or {}
    deck = player.get("deck") or []
    return [{"id": card.get("id"), "name": card.get("name"), "upgraded": bool(card.get("upgraded"))} for card in deck]


def card_counts(rows):
    counts = Counter()
    for row in rows:
        counts.update(card["id"] for card in row["final_deck"] if card.get("id"))
    return dict(counts.most_common())


def group_metrics(rows):
    if not rows:
        return {"runs": 0}
    return {
        "runs": len(rows),
        "final_deck_mean": statistics.fmean(row["final_deck_size"] for row in rows),
        "final_deck_median": statistics.median(row["final_deck_size"] for row in rows),
        "max_observed_deck_mean": statistics.fmean(row["max_observed_deck_size"] for row in rows),
        "upgraded_cards_mean": statistics.fmean(row["upgraded_cards"] for row in rows),
        "card_rewards_taken_mean": statistics.fmean(row["card_rewards_taken"] for row in rows),
        "card_rewards_skipped_mean": statistics.fmean(row["card_rewards_skipped"] for row in rows),
    }


def parse_sample(audit_path, outputs):
    audit = read(audit_path)
    job = audit.get("job") or {}
    name = job.get("name") or audit.get("run_id")
    require = lambda ok, message: None if ok else (_ for _ in ()).throw(ValueError(message))
    require(name, f"Audit has no run id: {audit_path}")
    folder = outputs / name
    require(folder.exists(), f"Raw folder missing: {name}")
    state = read(folder / "state.json")
    report = audit["report"]
    goal = audit["goal"]
    final_deck = deck_from_state(state)
    max_deck = len(final_deck)
    reward_taken = reward_skipped = 0
    special_builds = set()
    decisions_path = folder / "decisions.jsonl"
    if decisions_path.exists():
        decisions = {}
        for line in decisions_path.read_text(encoding="utf-8").splitlines():
            packet = json.loads(line)
            for candidate_state in (packet.get("state"), packet.get("next_state")):
                if isinstance(candidate_state, dict):
                    max_deck = max(max_deck, len(deck_from_state(candidate_state)))
            decision_id = packet.get("decision_id")
            if decision_id and (decision_id not in decisions or "execution" in packet):
                decisions[decision_id] = packet
        for packet in decisions.values():
            candidate_set = packet.get("candidate_set") or {}
            if candidate_set.get("decision") == "card_reward":
                if (packet.get("chosen") or {}).get("is_skip"):
                    reward_skipped += 1
                else:
                    reward_taken += 1
    policy_path = folder / "policy.jsonl"
    if policy_path.exists():
        for line in policy_path.read_text(encoding="utf-8").splitlines():
            packet = json.loads(line)
            for score in (packet.get("scoring") or {}).get("scores", []):
                discipline = score.get("deck_discipline") or {}
                special_builds.update(discipline.get("special_builds") or [])
    return {
        "run_id": name,
        "seed": job.get("seed") or report.get("seed"),
        "audit": evidence(audit_path),
        "integration_passed": bool(audit.get("integration_passed")),
        "target_success": bool(audit.get("integration_passed") and goal.get("natural_goal_success")),
        "outcome": report.get("outcome"),
        "max_act": goal.get("max_act_observed"),
        "max_floor": goal.get("max_floor_in_max_act"),
        "final_hp": report.get("final_hp"),
        "decisions": report.get("decisions"),
        "seconds": report.get("seconds"),
        "final_deck_size": len(final_deck),
        "max_observed_deck_size": max_deck,
        "upgraded_cards": sum(card["upgraded"] for card in final_deck),
        "final_deck": final_deck,
        "special_builds": sorted(special_builds),
        "card_rewards_taken": reward_taken,
        "card_rewards_skipped": reward_skipped,
        "relics": [relic.get("id") for relic in (state.get("player") or {}).get("relics", [])],
    }


def summarize(rows):
    valid = [row for row in rows if row["integration_passed"]]
    successes = [row for row in valid if row["target_success"]]
    near = [row for row in valid if not row["target_success"] and row["max_act"] == 3 and row["max_floor"] >= 15]
    early = [row for row in valid if row["max_act"] < 3 or (row["max_act"] == 3 and row["max_floor"] < 15)]
    sizes = [row["final_deck_size"] for row in valid]
    return {
        "samples": len(rows),
        "valid": len(valid),
        "invalid": len(rows) - len(valid),
        "target_successes": len(successes),
        "near_target_failures": len(near),
        "earlier_failures": len(early),
        "progress_distribution": dict(Counter(f"A{row['max_act']}F{row['max_floor']}" for row in valid)),
        "deck_size": {
            "minimum": min(sizes) if sizes else None,
            "median": statistics.median(sizes) if sizes else None,
            "mean": statistics.fmean(sizes) if sizes else None,
            "maximum": max(sizes) if sizes else None,
            "at_most_25": sum(size <= 25 for size in sizes),
            "26_to_36": sum(26 <= size <= 36 for size in sizes),
            "over_36": sum(size > 36 for size in sizes),
        },
        "max_observed_deck_over_36_without_special_build": [
            row["run_id"] for row in valid if row["max_observed_deck_size"] > 36 and not row["special_builds"]
        ],
        "success_rows": successes,
        "near_target_rows": near,
        "category_metrics": {
            "target_success": group_metrics(successes),
            "near_target_failure": group_metrics(near),
            "earlier_failure": group_metrics(early),
        },
        "success_card_counts": card_counts(successes),
        "near_target_card_counts": card_counts(near),
        "all_valid_card_counts": card_counts(valid),
        "card_reward_totals": {
            "taken": sum(row["card_rewards_taken"] for row in valid),
            "skipped": sum(row["card_rewards_skipped"] for row in valid),
        },
        "natural_outcomes_used_for_fitting": False,
        "running_model_modified": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sampling", type=Path, required=True)
    parser.add_argument("--goal", type=Path, required=True)
    parser.add_argument("--outputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audits = sorted(args.sampling.glob("*-audit.json")) + sorted(args.goal.glob("batches/*/*-audit.json"))
    rows = [parse_sample(path, args.outputs) for path in audits]
    result = summarize(rows)
    result["audits"] = [evidence(path) for path in audits]
    atomic(args.output, result)
    print(json.dumps({k: result[k] for k in ("samples", "valid", "invalid", "target_successes", "near_target_failures", "earlier_failures", "deck_size", "card_reward_totals")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
