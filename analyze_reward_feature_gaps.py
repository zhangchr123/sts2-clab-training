"""Audit card-reward feature gaps in frozen clean natural Defect A10 runs."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from decision_data import DataContractError
from initial_policy import card_id
from run_metadata import file_evidence


SCHEMA = "card-reward-feature-gap-audit-v1"


def require(condition, message):
    if not condition:
        raise DataContractError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def clean_runs(root, prefixes):
    selected, excluded = [], []
    for directory in sorted(Path(root).resolve().iterdir()):
        if not directory.is_dir() or not any(directory.name.startswith(p) for p in prefixes):
            continue
        paths = [directory / name for name in
                 ("status.json", "decisions.jsonl", "policy.jsonl")]
        if not all(path.is_file() for path in paths):
            excluded.append({"run_id": directory.name, "reason": "incomplete_evidence"})
            continue
        status = read(paths[0])
        if status.get("status") != "finished" or status.get("error") is not None:
            excluded.append({
                "run_id": directory.name,
                "reason": "not_clean_terminal",
                "status": status.get("status"),
                "error_present": status.get("error") is not None,
            })
            continue
        selected.append(directory)
    return selected, excluded


def completed_records(path):
    result = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("record_type") == "decision_completed":
            result[row["decision_id"]] = row
    return result


def request_candidates(record):
    candidate_set = record.get("candidate_set") or {}
    require(candidate_set.get("representation") == "explicit_v1",
            "Card reward audit requires explicit candidate sets")
    rows = candidate_set.get("candidates")
    require(isinstance(rows, list) and rows, "Card reward candidates are absent")
    return rows


def evidence_for_request(record, request):
    matches = [candidate for candidate in request_candidates(record)
               if candidate.get("request") == request]
    require(len(matches) == 1, "Card reward request binding differs")
    return matches[0].get("evidence") or {}


def normalize_missing(items):
    return [str(item) for item in (items or [])]


def audit(run_root, prefixes, expected_runs, diagnostics_path):
    run_dirs, excluded = clean_runs(run_root, prefixes)
    require(len(run_dirs) == expected_runs,
            f"Expected {expected_runs} clean runs, found {len(run_dirs)}")
    diagnostics = read(diagnostics_path)
    require(diagnostics.get("schema_version") ==
            "cloud-natural-policy-decision-diagnostics-v1",
            "Natural-run diagnostics identity differs")
    near_target = {
        row["run_id"] for row in diagnostics.get("run_evidence") or []
        if row.get("category") == "near_target_failure"
    }
    sources = []
    decision_counts = Counter()
    candidate_counts = Counter()
    missing = Counter()
    missing_near = Counter()
    missing_by_card = defaultdict(Counter)
    offered = Counter()
    chosen = Counter()
    offered_near = Counter()
    chosen_near = Counter()
    card_types = defaultdict(Counter)
    rarities = defaultdict(Counter)
    costs = defaultdict(Counter)
    stat_shapes = defaultdict(Counter)
    mechanism_sets = defaultdict(Counter)
    unknown_identity = Counter()
    examples = []

    for directory in run_dirs:
        decisions_path = directory / "decisions.jsonl"
        policy_path = directory / "policy.jsonl"
        sources.extend((file_evidence(decisions_path), file_evidence(policy_path)))
        records = completed_records(decisions_path)
        is_near = directory.name in near_target
        for line in policy_path.read_text(encoding="utf-8").splitlines():
            policy = json.loads(line)
            scoring = policy.get("scoring") or {}
            scores = scoring.get("scores") or []
            card_rows = [row for row in scores
                         if (row.get("request") or {}).get("action") ==
                         "select_card_reward"]
            if not card_rows:
                continue
            decision_id = policy.get("decision_id")
            record = records.get(decision_id)
            require(record is not None, f"Missing card reward record: {decision_id}")
            decision_counts["all"] += 1
            decision_counts["near_target"] += int(is_near)
            skip_rows = [row for row in scores
                         if (row.get("request") or {}).get("action") ==
                         "skip_card_reward"]
            require(len(skip_rows) == 1, "Card reward decision lacks one skip")
            for row in card_rows:
                evidence = evidence_for_request(record, row["request"])
                cid = card_id(evidence) or "UNKNOWN"
                is_chosen = row.get("candidate_id") == policy.get("candidate_id")
                gaps = normalize_missing(row.get("missing"))
                detail = row.get("card_detail") or {}
                mechanisms = tuple(sorted(detail.get("mechanisms") or ()))
                stats = evidence.get("stats")
                shape = tuple(sorted(str(key).lower() for key in stats)) \
                    if isinstance(stats, dict) else ()
                candidate_counts["all"] += 1
                candidate_counts["near_target"] += int(is_near)
                offered[cid] += 1
                chosen[cid] += int(is_chosen)
                offered_near[cid] += int(is_near)
                chosen_near[cid] += int(is_near and is_chosen)
                card_types[cid][str(evidence.get("type"))] += 1
                rarities[cid][str(evidence.get("rarity"))] += 1
                costs[cid][str(evidence.get("cost"))] += 1
                stat_shapes[cid][json.dumps(shape)] += 1
                mechanism_sets[cid][json.dumps(mechanisms)] += 1
                for gap in gaps:
                    missing[gap] += 1
                    missing_by_card[cid][gap] += 1
                    if is_near:
                        missing_near[gap] += 1
                features = row.get("search_features") or {}
                if features.get("card_identity_unknown") == 1:
                    unknown_identity[cid] += 1
                if gaps and len(examples) < 250:
                    state = record.get("state") or {}
                    context = state.get("context") or {}
                    examples.append({
                        "run_id": directory.name,
                        "decision_id": decision_id,
                        "act": context.get("act"),
                        "floor": context.get("floor"),
                        "near_target_run": is_near,
                        "card_id": cid,
                        "chosen": is_chosen,
                        "score": row.get("score"),
                        "delta_from_skip": row.get("score") - skip_rows[0].get("score"),
                        "type": evidence.get("type"),
                        "rarity": evidence.get("rarity"),
                        "cost": evidence.get("cost"),
                        "stats": stats,
                        "mechanisms": list(mechanisms),
                        "missing": gaps,
                    })

    all_cards = sorted(offered, key=lambda cid: (-offered[cid], cid))
    cards = {}
    for cid in all_cards:
        cards[cid] = {
            "offered": offered[cid],
            "chosen": chosen[cid],
            "near_target_offered": offered_near[cid],
            "near_target_chosen": chosen_near[cid],
            "types": dict(card_types[cid]),
            "rarities": dict(rarities[cid]),
            "costs": dict(costs[cid]),
            "stat_shapes": dict(stat_shapes[cid]),
            "mechanism_sets": dict(mechanism_sets[cid]),
            "missing": dict(missing_by_card[cid].most_common()),
            "unknown_identity_rows": unknown_identity[cid],
        }
    result = {
        "schema_version": SCHEMA,
        "passed": True,
        "scope": {
            "run_prefixes": list(prefixes),
            "clean_runs": len(run_dirs),
            "run_ids": [directory.name for directory in run_dirs],
            "excluded_runs": excluded,
            "near_target_run_ids_from_frozen_diagnostics": sorted(near_target),
        },
        "counts": {
            "reward_decisions": dict(decision_counts),
            "card_candidate_rows": dict(candidate_counts),
            "distinct_card_ids": len(cards),
        },
        "missing": {
            "all_candidate_rows": dict(missing.most_common()),
            "near_target_candidate_rows": dict(missing_near.most_common()),
        },
        "cards": cards,
        "examples": examples,
        "sources": {
            "decision_and_policy_files": sources,
            "diagnostics": file_evidence(diagnostics_path),
            "analyzer": file_evidence(Path(__file__).resolve()),
        },
        "interpretation": {
            "descriptive_not_causal": True,
            "natural_outcomes_used_for_fitting": False,
            "candidate_selected_or_deployed": False,
            "near_target_label_used_only_for_audit_stratum": True,
        },
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--run-prefix", action="append", required=True)
    parser.add_argument("--expected-runs", type=int, required=True)
    parser.add_argument("--diagnostics", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(
        args.run_root, args.run_prefix, args.expected_runs, args.diagnostics
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.write_text(json.dumps(
        result, ensure_ascii=False, indent=2, allow_nan=False
    ) + "\n", encoding="utf-8")
    print(json.dumps({
        "passed": result["passed"],
        "counts": result["counts"],
        "missing": result["missing"],
        "top_cards_with_gaps": [
            {"card_id": cid, **row}
            for cid, row in result["cards"].items() if row["missing"]
        ][:30],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
