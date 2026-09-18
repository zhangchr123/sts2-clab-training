"""Audit exact public rest healing and downstream public route damage."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import statistics

from decision_data import DataContractError, enumerate_candidates, materialize_candidate
import encounter_damage_features
import full_route_features
from run_metadata import file_evidence


SCHEMA = "rest-heal-route-gap-audit-v1"
BASE_HEAL_FRACTION = 0.30
PILLOW_ID = "RELIC.REGAL_PILLOW"
HUMIDIFIER_ID = "RELIC.STONE_HUMIDIFIER"


def require(condition, message):
    if not condition:
        raise DataContractError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def relic_var(state, relic_id, name):
    relics = (state.get("player") or {}).get("relics") or []
    matched = [relic for relic in relics
               if isinstance(relic, dict) and relic.get("id") == relic_id]
    require(len(matched) <= 1, f"Duplicate public relic: {relic_id}")
    if not matched:
        return 0
    value = (matched[0].get("vars") or {}).get(name)
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            f"Public relic variable is missing: {relic_id}.{name}")
    return value


def heal_projection(state):
    player = state.get("player") or {}
    hp, maximum = player.get("hp"), player.get("max_hp")
    require(type(hp) in (int, float) and type(maximum) in (int, float)
            and math.isfinite(hp) and math.isfinite(maximum)
            and maximum > 0 and 0 <= hp <= maximum,
            "Rest healing requires public HP")
    pillow = relic_var(state, PILLOW_ID, "Heal")
    humidifier = relic_var(state, HUMIDIFIER_ID, "MaxHp")
    base = math.floor(BASE_HEAL_FRACTION * maximum)
    maximum_after = maximum + humidifier
    uncapped_gain = base + pillow + humidifier
    hp_after = min(maximum_after, hp + uncapped_gain)
    return {
        "hp_before": hp,
        "max_hp_before": maximum,
        "base_heal": base,
        "regal_pillow_heal": pillow,
        "stone_humidifier_max_hp": humidifier,
        "uncapped_hp_gain": uncapped_gain,
        "hp_gain": hp_after - hp,
        "hp_after": hp_after,
        "max_hp_after": maximum_after,
    }


def option_identity(state, request):
    space = enumerate_candidates(state)
    candidate = (materialize_candidate(space, request)
                 if space.get("representation") == "ordered_selection_implicit_v1"
                 else next((row for row in space["candidates"]
                            if row["request"] == request), None))
    require(candidate is not None, "Recorded rest request is no longer legal")
    evidence = candidate["evidence"]
    return str(evidence.get("option_id", evidence.get("name", ""))).upper()


def _best_route_summary(observation, selected_position, act, catalog):
    public_map = observation.get("public_map")
    require(public_map is not None, "Pre-rest public map is unavailable")
    graph, boss = full_route_features._public_graph(public_map)
    require(selected_position in graph
            and graph[selected_position]["type"] == "RestSite",
            "Selected pre-rest node is not a public RestSite")
    children = graph[selected_position]["children"]
    require(children, "Public rest node has no downstream path")
    summaries = [encounter_damage_features._route_summary(
        graph, boss, child, act, catalog["final_table"]
    ) for child in children]
    summaries = [summary for summary in summaries if summary["path_available"]]
    require(summaries, "No public downstream damage route is available")
    quantitative = [name for name in encounter_damage_features.SUMMARY_NAMES
                    if name != "path_available"]
    best = {name: min(summary[name] for summary in summaries)
            for name in quantitative}
    worst = {name: max(summary[name] for summary in summaries)
             for name in quantitative}
    return {
        "status": "available",
        "outgoing_nodes": len(children),
        "available_outgoing_nodes": len(summaries),
        "best_achievable": best,
        "worst_available": worst,
    }


def _quantiles(values):
    ordered = sorted(values)
    if not ordered:
        return {"minimum": None, "median": None, "q75": None,
                "q90": None, "maximum": None}
    pick = lambda probability: ordered[math.ceil(probability * len(ordered)) - 1]
    return {
        "minimum": ordered[0],
        "median": statistics.median(ordered),
        "q75": pick(.75),
        "q90": pick(.90),
        "maximum": ordered[-1],
    }


def analyze(run_root, prefixes, expected_runs, catalog_path):
    run_root = Path(run_root).resolve()
    catalog_path = Path(catalog_path).resolve()
    catalog = read(catalog_path)
    encounter_damage_features.validate_catalog(catalog)
    run_dirs, excluded = [], []
    for directory in sorted(run_root.iterdir()):
        if not directory.is_dir() or not any(directory.name.startswith(p) for p in prefixes):
            continue
        paths = [directory / name for name in
                 ("status.json", "decisions.jsonl", "policy.jsonl")]
        if not all(path.is_file() for path in paths):
            excluded.append({"run_id": directory.name, "reason": "incomplete_evidence"})
            continue
        status = read(paths[0])
        if status.get("status") != "finished" or status.get("error") is not None:
            excluded.append({"run_id": directory.name, "reason": "not_clean_terminal",
                             "status": status.get("status"),
                             "error_present": status.get("error") is not None})
            continue
        run_dirs.append(directory)
    require(len(run_dirs) == expected_runs,
            f"Expected {expected_runs} clean runs, found {len(run_dirs)}")

    sources, details = [], []
    option_counts = Counter()
    missing = Counter()
    exact_heal = observed_heal = smith_unchanged = 0
    pre_post_map_exact = 0
    for directory in run_dirs:
        decisions_path = directory / "decisions.jsonl"
        policy_path = directory / "policy.jsonl"
        decisions = [row for row in read_jsonl(decisions_path)
                     if row.get("record_type") == "decision_completed"]
        policies = read_jsonl(policy_path)
        require(len(decisions) == len(policies),
                f"Policy/state count differs: {directory}")
        require(all(decision["decision_id"] == policy["decision_id"]
                    for decision, policy in zip(decisions, policies)),
                f"Policy/state order differs: {directory}")
        sources.extend((file_evidence(decisions_path), file_evidence(policy_path)))
        last_map = None
        for index, (decision, policy) in enumerate(zip(decisions, policies)):
            state = decision["state"]
            observation = policy.get("map_observation")
            if observation is not None:
                require(state.get("decision") == "map_select",
                        "Map observation attached to non-map state")
                last_map = {
                    "observation": observation,
                    "selected_request": policy["request"],
                }
            if state.get("decision") != "rest_site":
                continue
            require(last_map is not None, "Rest decision lacks prior public map")
            selected_request = last_map["selected_request"]
            require(selected_request.get("action") == "select_map_node",
                    "Prior map action does not select a node")
            position = full_route_features._coordinate(selected_request.get("args"))
            act = (state.get("context") or {}).get("act")
            require(type(act) is int and act in (1, 2, 3),
                    "Rest decision lacks public act")
            route = _best_route_summary(
                last_map["observation"], position, act, catalog
            )

            post_map = next((later.get("map_observation") for later in policies[index + 1:]
                             if later.get("map_observation") is not None), None)
            require(post_map is not None, "Rest decision lacks a later map observation")
            raw = post_map.get("raw_response") or {}
            require(full_route_features._coordinate(raw.get("current_coord")) == position,
                    "Pre-rest selected node differs from post-rest current node")
            require(post_map.get("public_map_hash") ==
                    last_map["observation"].get("public_map_hash"),
                    "Public map topology changed across rest")
            pre_post_map_exact += 1

            scoring_rows = (policy.get("scoring") or {}).get("scores") or []
            for score_row in scoring_rows:
                missing.update(score_row.get("missing") or [])
            chosen_identity = option_identity(state, policy["request"])
            option_counts[chosen_identity] += 1
            projection = heal_projection(state)
            next_player = (decision.get("next_state") or {}).get("player") or {}
            if chosen_identity == "HEAL":
                observed_heal += 1
                exact = (next_player.get("hp") == projection["hp_after"]
                         and next_player.get("max_hp") == projection["max_hp_after"])
                exact_heal += int(exact)
                require(exact, f"Observed rest heal differs: {decision['decision_id']}")
            elif chosen_identity == "SMITH":
                unchanged = (next_player.get("hp") == projection["hp_before"]
                             and next_player.get("max_hp") == projection["max_hp_before"])
                smith_unchanged += int(unchanged)
                require(unchanged, f"Smith changed immediate HP: {decision['decision_id']}")

            by_request = {json.dumps(row["request"], sort_keys=True): row
                          for row in scoring_rows}
            option_rows = []
            for candidate in enumerate_candidates(state)["candidates"]:
                identity = str(candidate["evidence"].get(
                    "option_id", candidate["evidence"].get("name", "")
                )).upper()
                score_row = by_request[json.dumps(candidate["request"], sort_keys=True)]
                option_rows.append({
                    "identity": identity,
                    "candidate_id": candidate["candidate_id"],
                    "score": score_row["score"],
                    "missing": score_row.get("missing") or [],
                    "chosen": candidate["request"] == policy["request"],
                })
            details.append({
                "run_id": directory.name,
                "decision_id": decision["decision_id"],
                "act": act,
                "floor": (state.get("context") or {}).get("floor"),
                "chosen_option": chosen_identity,
                "heal_projection": projection,
                "route": route,
                "options": option_rows,
            })

    require(details and observed_heal and exact_heal == observed_heal,
            "No exact observed heal evidence")
    q75_stop = [row["route"]["best_achievable"]["damage_q75_to_stop_min"]
                for row in details]
    q90_stop = [row["route"]["best_achievable"]["damage_q90_to_stop_min"]
                for row in details]
    q75_boss = [row["route"]["best_achievable"]["damage_q75_to_boss_min"]
                for row in details]
    return {
        "schema_version": SCHEMA,
        "passed": True,
        "interpretation": {
            "descriptive_not_causal": True,
            "natural_outcomes_used_for_parameter_fitting": False,
            "candidate_selected": False,
            "automatic_deployment": False,
        },
        "selection": {
            "run_prefixes": list(prefixes),
            "runs": len(run_dirs),
            "run_ids": [directory.name for directory in run_dirs],
            "excluded_runs": excluded,
        },
        "counts": {
            "rest_decisions": len(details),
            "chosen_options": dict(option_counts),
            "observed_heal_executions": observed_heal,
            "exact_heal_formula_matches": exact_heal,
            "smith_immediate_hp_unchanged": smith_unchanged,
            "pre_rest_to_post_rest_map_topology_exact": pre_post_map_exact,
        },
        "heal_contract_evidence": {
            "base_fraction": BASE_HEAL_FRACTION,
            "rounding": "floor_old_max_hp_times_fraction",
            "regal_pillow": "public_relic_vars.Heal",
            "stone_humidifier": "public_relic_vars.MaxHp_added_to_max_and_current_hp",
            "cap": "new_max_hp",
        },
        "missing_signal": {
            "actual_rest_heal_amount": missing["actual_rest_heal_amount"],
            "future_route_damage_distribution": missing[
                "future_route_damage_distribution"
            ],
        },
        "route_distribution": {
            "best_q75_damage_to_next_stop": _quantiles(q75_stop),
            "best_q90_damage_to_next_stop": _quantiles(q90_stop),
            "best_q75_damage_to_boss": _quantiles(q75_boss),
        },
        "details": details,
        "sources": {
            "decision_and_policy_files": sources,
            "catalog": file_evidence(catalog_path),
            "analysis_source": file_evidence(Path(__file__).resolve()),
            "encounter_damage_source": file_evidence(
                Path(encounter_damage_features.__file__).resolve()
            ),
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--run-prefix", action="append", required=True)
    parser.add_argument("--expected-runs", type=int, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(
        args.run_root, args.run_prefix, args.expected_runs, args.catalog
    )
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "passed": result["passed"],
        "counts": result["counts"],
        "missing_signal": result["missing_signal"],
        "route_distribution": result["route_distribution"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
