"""Fit and hold out a public act/node-type encounter damage distribution.

The target is gross HP lost in the actual combat divided by public max HP.  The
model sees only the act and the map's already-public node type.  Unknown nodes,
encounter identity, terminal run outcome, future rewards, and hidden map data
are never model inputs.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import statistics

from decision_data import DataContractError, split_by_seed
from run_metadata import file_evidence


SCHEMA = "public-encounter-damage-catalog-v1"
NODE_TYPES = ("Monster", "Elite", "Boss")
QUANTILES = (0.5, 0.75, 0.9)
SMOOTHING_CANDIDATES = (0.0, 5.0, 10.0, 20.0, 40.0, 80.0)
SPLIT_SALT = "sts2-encounter-damage-catalog-v1"
CONTRACT = {
    "schema_version": SCHEMA,
    "scope": "Defect A10 actual combats under the frozen solver policy",
    "target": "gross_live_hp_lost_during_combat_divided_by_public_max_hp",
    "inputs": ["public_act", "public_map_node_type"],
    "public_node_types": list(NODE_TYPES),
    "unknown_nodes_used_as_known_encounters": False,
    "encounter_identity_used_as_input": False,
    "terminal_run_outcome_used_as_input": False,
    "test_split_used_for_selection": False,
    "counterfactual_damage_claimed": False,
}


def require(condition, message):
    if not condition:
        raise DataContractError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def quantile(values, probability):
    require(values and 0 <= probability <= 1, "Quantile input differs")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * probability
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def pinball(actual, predicted, probability):
    residual = actual - predicted
    return probability * residual if residual >= 0 else (probability - 1) * residual


def known_room_resolution(public_type, state, next_state):
    after_context = next_state.get("context") or {}
    if after_context.get("room_type") == public_type:
        return "ordinary_known_room"
    before_context = state.get("context") or {}
    boss = before_context.get("boss") or {}
    second = before_context.get("second_boss")
    if (
        public_type == "Boss"
        and before_context.get("act") == 3
        and before_context.get("floor") == 14
        and next_state.get("decision") == "map_select"
        and after_context.get("act") == 3
        and after_context.get("floor") == 15
        and after_context.get("room_type") == "Map"
        and isinstance(boss.get("id"), str)
        and isinstance(second, str)
        and boss["id"] != second
    ):
        return "act3_first_boss_to_second_boss_map"
    return None


def combat_rows(directory):
    manifest_path = directory / "manifest.json"
    status_path = directory / "status.json"
    decisions_path = directory / "decisions.jsonl"
    require(manifest_path.is_file() and status_path.is_file() and decisions_path.is_file(),
            f"Run evidence is incomplete: {directory}")
    manifest, status = read(manifest_path), read(status_path)
    require(status.get("status") == "finished" and status.get("error") is None,
            f"Run is not clean and terminal: {directory}")
    require(manifest.get("character") == "Defect" and manifest.get("ascension") == 10
            and manifest.get("mode") == "standard", "Encounter run scope differs")
    rows, public_unknown_combats = [], 0
    for line in decisions_path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        state = record.get("state") or {}
        if record.get("record_type") != "decision_completed" or state.get("decision") != "map_select":
            continue
        chosen = record.get("chosen") or {}
        evidence = chosen.get("evidence") or {}
        public_type = evidence.get("type")
        next_state = record.get("next_state") or {}
        before_player, after_player = state.get("player") or {}, next_state.get("player") or {}
        before_metrics = before_player.get("combat_metrics") or {}
        after_metrics = after_player.get("combat_metrics") or {}
        before_id, after_id = before_metrics.get("combat_id"), after_metrics.get("combat_id")
        combat_happened = type(before_id) is int and type(after_id) is int and after_id == before_id + 1
        if public_type == "Unknown" and combat_happened:
            public_unknown_combats += 1
            continue
        if public_type not in NODE_TYPES:
            require(not combat_happened, "Known noncombat public node started combat")
            continue
        require(combat_happened, "Known public fight did not produce exactly one combat")
        act = (state.get("context") or {}).get("act")
        hp, maximum = before_player.get("hp"), before_player.get("max_hp")
        lost, recovered = after_metrics.get("hp_lost"), after_metrics.get("hp_recovered")
        require(type(act) is int and act in (1, 2, 3), "Combat act differs")
        require(all(type(value) in (int, float) and math.isfinite(value)
                    for value in (hp, maximum, lost, recovered))
                and maximum > 0 and 0 <= hp <= maximum and lost >= 0 and recovered >= 0,
                "Combat HP metrics differ")
        require(len(record.get("solver_calls") or []) >= 1, "Combat lacks frozen solver evidence")
        resolution = known_room_resolution(public_type, state, next_state)
        require(resolution is not None, "Resolved room type differs from public known node")
        rows.append({
            "metadata": {
                "seed": manifest["seed"],
                "run_id": manifest["run_id"],
                **({"lineage_root_seed": manifest["lineage_root_seed"]}
                   if manifest.get("lineage_root_seed") else {}),
            },
            "decision_id": record["decision_id"],
            "act": act,
            "node_type": public_type,
            "floor": (state.get("context") or {}).get("floor"),
            "start_hp_ratio": hp / maximum,
            "gross_loss_ratio": lost / maximum,
            "recovery_ratio": recovered / maximum,
            "lethal_transition": next_state.get("decision") == "game_over"
            and next_state.get("victory") is False,
            "resolution": resolution,
        })
    return rows, public_unknown_combats, [
        file_evidence(manifest_path), file_evidence(status_path), file_evidence(decisions_path)
    ]


def group_values(rows):
    cells, acts, types = defaultdict(list), defaultdict(list), defaultdict(list)
    all_values = []
    for row in rows:
        value = row["gross_loss_ratio"]
        cells[(row["act"], row["node_type"])].append(value)
        acts[row["act"]].append(value)
        types[row["node_type"]].append(value)
        all_values.append(value)
    return cells, acts, types, all_values


def fit(rows, smoothing):
    require(rows, "Encounter training split is empty")
    cells, acts, types, all_values = group_values(rows)
    table = {}
    for act in (1, 2, 3):
        for node_type in NODE_TYPES:
            values = cells.get((act, node_type), [])
            prior_parts = []
            for pool in (acts.get(act), types.get(node_type)):
                if pool:
                    prior_parts.append(pool)
            cell = {"support": len(values), "quantiles": {}}
            for probability in QUANTILES:
                prior = statistics.fmean(quantile(pool, probability) for pool in prior_parts) \
                    if prior_parts else quantile(all_values, probability)
                if values:
                    weight = len(values) / (len(values) + smoothing) if smoothing else 1.0
                    estimate = weight * quantile(values, probability) + (1 - weight) * prior
                else:
                    weight, estimate = 0.0, prior
                cell["quantiles"][str(probability)] = estimate
                cell.setdefault("cell_weight", weight)
            table[f"act{act}:{node_type}"] = cell
    return table


def fit_baseline(rows, mode):
    require(mode in ("global", "act", "node_type"), "Damage baseline mode differs")
    cells, acts, types, all_values = group_values(rows)
    del cells
    table = {}
    for act in (1, 2, 3):
        for node_type in NODE_TYPES:
            pool = all_values if mode == "global" else acts.get(act, []) if mode == "act" else types.get(node_type, [])
            if not pool:
                pool = all_values
            table[f"act{act}:{node_type}"] = {
                "support": len(pool),
                "cell_weight": 0.0,
                "quantiles": {str(probability): quantile(pool, probability)
                              for probability in QUANTILES},
            }
    return table


def evaluate(rows, table):
    result = {"rows": len(rows), "pinball": {}, "coverage": {}, "mae_median": None}
    if not rows:
        return result
    median_errors = []
    for probability in QUANTILES:
        losses, covered = [], 0
        for row in rows:
            predicted = table[f"act{row['act']}:{row['node_type']}"]["quantiles"][str(probability)]
            actual = row["gross_loss_ratio"]
            losses.append(pinball(actual, predicted, probability))
            covered += actual <= predicted + 1e-12
            if probability == 0.5:
                median_errors.append(abs(actual - predicted))
        result["pinball"][str(probability)] = statistics.fmean(losses)
        result["coverage"][str(probability)] = covered / len(rows)
    result["mae_median"] = statistics.fmean(median_errors)
    result["mean_pinball"] = statistics.fmean(result["pinball"].values())
    return result


def evaluate_by_cell(rows, table):
    grouped = defaultdict(list)
    for row in rows:
        grouped[f"act{row['act']}:{row['node_type']}"] .append(row)
    return {key: evaluate(selected, table) for key, selected in sorted(grouped.items())}


def raw_summary(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[f"act{row['act']}:{row['node_type']}"] .append(row)
    return {
        key: {
            "support": len(selected),
            "gross_loss_ratio_mean": statistics.fmean(row["gross_loss_ratio"] for row in selected),
            "gross_loss_ratio_quantiles": {
                str(probability): quantile([row["gross_loss_ratio"] for row in selected], probability)
                for probability in QUANTILES
            },
            "lethal_transitions": sum(row["lethal_transition"] for row in selected),
            "recovery_present": sum(row["recovery_ratio"] > 0 for row in selected),
        }
        for key, selected in sorted(grouped.items())
    }


def train(run_root, prefixes, expected_runs):
    run_root = Path(run_root).resolve()
    directories, excluded, rows, sources = [], [], [], []
    unknown_combats = 0
    for directory in sorted(run_root.iterdir()):
        if not directory.is_dir() or not any(directory.name.startswith(prefix) for prefix in prefixes):
            continue
        try:
            selected, unknown, evidence = combat_rows(directory)
        except (DataContractError, OSError, ValueError, KeyError) as exc:
            excluded.append({"run_id": directory.name, "reason": type(exc).__name__})
            continue
        directories.append(directory)
        rows.extend(selected)
        unknown_combats += unknown
        sources.extend(evidence)
    require(len(directories) == expected_runs,
            f"Expected {expected_runs} clean runs, found {len(directories)}")
    require(rows, "No known public encounter transitions")
    splits = split_by_seed(rows, validation_fraction=0.2, test_fraction=0.1, salt=SPLIT_SALT)
    require(all(splits.values()), "Encounter split is empty")

    trials = []
    for smoothing in SMOOTHING_CANDIDATES:
        table = fit(splits["train"], smoothing)
        trials.append({
            "smoothing": smoothing,
            "validation": evaluate(splits["validation"], table),
        })
    selected = min(trials, key=lambda row: (row["validation"]["mean_pinball"], row["smoothing"]))
    smoothing = selected["smoothing"]
    test_table = fit(splits["train"], smoothing)
    test_evaluation = evaluate(splits["test"], test_table)
    validation_baselines = {
        mode: evaluate(splits["validation"], fit_baseline(splits["train"], mode))
        for mode in ("global", "act", "node_type")
    }
    test_baselines = {
        mode: evaluate(splits["test"], fit_baseline(splits["train"], mode))
        for mode in ("global", "act", "node_type")
    }
    final_fit_rows = splits["train"] + splits["validation"]
    final_table = fit(final_fit_rows, smoothing)
    return {
        "schema_version": SCHEMA,
        "passed": True,
        "contract": CONTRACT,
        "selection": {
            "run_prefixes": list(prefixes),
            "clean_runs": len(directories),
            "excluded_runs": excluded,
            "known_encounter_rows": len(rows),
            "unknown_node_combats_excluded": unknown_combats,
            "split_rows": {name: len(value) for name, value in splits.items()},
            "split_runs": {name: len({row["metadata"]["run_id"] for row in value})
                           for name, value in splits.items()},
            "split_salt": SPLIT_SALT,
        },
        "tuning": {
            "candidates": trials,
            "selected_smoothing": smoothing,
            "selection_metric": "validation_mean_pinball_across_q50_q75_q90",
            "validation_baselines": validation_baselines,
        },
        "held_out_test": test_evaluation,
        "held_out_test_by_cell": evaluate_by_cell(splits["test"], test_table),
        "held_out_test_baselines": test_baselines,
        "final_fit_scope": "train_plus_validation_only_after_smoothing_selected",
        "final_table": final_table,
        "raw_all_rows_summary": raw_summary(rows),
        "sources": {
            "run_files": sources,
            "trainer": file_evidence(Path(__file__).resolve()),
        },
        "automatic_deployment": False,
        "win_rate_claim_permitted": False,
    }


def write_new(path, value):
    path = Path(path).resolve()
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                         encoding="utf-8")
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--run-prefix", action="append", required=True)
    parser.add_argument("--expected-runs", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = train(args.run_root, args.run_prefix, args.expected_runs)
    write_new(args.output, result)
    print(json.dumps({
        "passed": result["passed"],
        "selection": result["selection"],
        "selected_smoothing": result["tuning"]["selected_smoothing"],
        "held_out_test": result["held_out_test"],
        "final_table": result["final_table"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
