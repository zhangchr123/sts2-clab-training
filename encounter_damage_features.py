"""Known-encounter damage burden over the already-audited public map."""
from __future__ import annotations

import copy
from functools import lru_cache
import math

from decision_data import DataContractError, enumerate_candidates, state_hash
import full_route_features
from map_observation import validate_map_observation
from train_encounter_damage_catalog import CONTRACT as CATALOG_CONTRACT, NODE_TYPES, QUANTILES, SCHEMA


VERSION = "public-encounter-damage-route-v1"
Q_NAMES = {0.5: "q50", 0.75: "q75", 0.9: "q90"}
SUMMARY_NAMES = (
    "path_available",
    *(f"damage_{name}_to_stop_min" for name in Q_NAMES.values()),
    *(f"damage_{name}_to_stop_max" for name in Q_NAMES.values()),
    *(f"damage_{name}_to_boss_min" for name in Q_NAMES.values()),
    *(f"damage_{name}_to_boss_max" for name in Q_NAMES.values()),
    "unknowns_to_stop_min",
    "unknowns_to_stop_max",
    "any_rest_before_boss",
    "all_paths_rest_before_boss",
)
PARAMETERS = (
    "damage_q50_to_stop_min",
    "damage_q75_to_stop_min",
    "damage_q90_to_stop_min",
    "damage_q75_to_stop_max",
    "damage_q75_to_boss_min",
    "damage_q75_to_stop_excess_hp",
    "damage_q90_to_stop_excess_hp",
    "damage_q75_to_boss_excess_hp",
    "low_hp_damage_q75_to_stop_min",
)
PRIOR = {
    "damage_q50_to_stop_min": -0.08,
    "damage_q75_to_stop_min": -0.16,
    "damage_q90_to_stop_min": -0.16,
    "damage_q75_to_stop_max": -0.04,
    "damage_q75_to_boss_min": -0.03,
    "damage_q75_to_stop_excess_hp": -0.80,
    "damage_q90_to_stop_excess_hp": -1.10,
    "damage_q75_to_boss_excess_hp": -0.20,
    "low_hp_damage_q75_to_stop_min": -0.24,
}
CONTRACT = {
    "version": VERSION,
    "input": "audited_public_map_plus_frozen_public_act_node_type_damage_catalog",
    "known_node_types": list(NODE_TYPES),
    "unknown_room_damage_assumed": False,
    "encounter_identity_used": False,
    "future_deck_or_reward_simulation_used": False,
    "damage_units": "gross_hp_lost_divided_by_max_hp",
    "stop_semantics": "first_public_rest_or_exported_act_boss_on_each_path",
    "path_ranges_are_topology_not_probabilities": True,
    "candidate_adjustment_abs_cap": 2.0,
}


def require(condition, message):
    if not condition:
        raise DataContractError(message)


def validate_catalog(catalog):
    require(isinstance(catalog, dict) and catalog.get("schema_version") == SCHEMA
            and catalog.get("passed") is True and catalog.get("contract") == CATALOG_CONTRACT,
            "Encounter damage catalog identity differs")
    require(catalog.get("automatic_deployment") is False
            and catalog.get("win_rate_claim_permitted") is False
            and catalog.get("final_fit_scope") == "train_plus_validation_only_after_smoothing_selected",
            "Encounter damage catalog deployment or fit scope differs")
    require((catalog.get("held_out_test") or {}).get("rows", 0) > 0,
            "Encounter damage catalog lacks a held-out test")
    table = catalog.get("final_table")
    expected = {f"act{act}:{node_type}" for act in (1, 2, 3) for node_type in NODE_TYPES}
    require(isinstance(table, dict) and set(table) == expected,
            "Encounter damage catalog cells differ")
    for cell in table.values():
        require(set(cell) == {"support", "quantiles", "cell_weight"}
                and type(cell["support"]) is int and cell["support"] >= 0
                and type(cell["cell_weight"]) in (int, float)
                and 0 <= cell["cell_weight"] <= 1,
                "Encounter damage catalog cell schema differs")
        quantiles = cell["quantiles"]
        require(set(quantiles) == {str(value) for value in QUANTILES},
                "Encounter damage quantiles differ")
        values = [quantiles[str(value)] for value in QUANTILES]
        require(all(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 4
                    for value in values) and values == sorted(values),
                "Encounter damage quantiles are invalid")
    return True


def _zero_summary():
    return dict.fromkeys(SUMMARY_NAMES, 0.0)


def _route_summary(graph, boss, start, act, table):
    @lru_cache(None)
    def walk(position):
        node = graph[position]
        kind = node["type"]
        own = {name: 0.0 for name in Q_NAMES.values()}
        if kind in NODE_TYPES:
            cell = table[f"act{act}:{kind}"]["quantiles"]
            own = {Q_NAMES[probability]: float(cell[str(probability)]) for probability in QUANTILES}
        unknown = int(kind in ("Unknown", "Unassigned"))
        if position == boss:
            return {
                "boss_min": own, "boss_max": own,
                "stop_min": own, "stop_max": own,
                "unknown_stop_min": float(unknown), "unknown_stop_max": float(unknown),
                "any_rest": False, "all_rest": False,
            }
        children = [walk(child) for child in node["children"]]
        if not children:
            return None
        children = [child for child in children if child is not None]
        if not children:
            return None
        boss_min = {name: own[name] + min(child["boss_min"][name] for child in children)
                    for name in Q_NAMES.values()}
        boss_max = {name: own[name] + max(child["boss_max"][name] for child in children)
                    for name in Q_NAMES.values()}
        if kind == "RestSite":
            stop_min = stop_max = {name: 0.0 for name in Q_NAMES.values()}
            unknown_min = unknown_max = 0.0
            any_rest = all_rest = True
        else:
            stop_min = {name: own[name] + min(child["stop_min"][name] for child in children)
                        for name in Q_NAMES.values()}
            stop_max = {name: own[name] + max(child["stop_max"][name] for child in children)
                        for name in Q_NAMES.values()}
            unknown_min = unknown + min(child["unknown_stop_min"] for child in children)
            unknown_max = unknown + max(child["unknown_stop_max"] for child in children)
            any_rest = any(child["any_rest"] for child in children)
            all_rest = all(child["all_rest"] for child in children)
        return {
            "boss_min": boss_min, "boss_max": boss_max,
            "stop_min": stop_min, "stop_max": stop_max,
            "unknown_stop_min": float(unknown_min), "unknown_stop_max": float(unknown_max),
            "any_rest": any_rest, "all_rest": all_rest,
        }

    route = walk(start)
    if route is None:
        return _zero_summary()
    result = {"path_available": 1.0}
    for name in Q_NAMES.values():
        result[f"damage_{name}_to_stop_min"] = route["stop_min"][name]
        result[f"damage_{name}_to_stop_max"] = route["stop_max"][name]
        result[f"damage_{name}_to_boss_min"] = route["boss_min"][name]
        result[f"damage_{name}_to_boss_max"] = route["boss_max"][name]
    result.update(
        unknowns_to_stop_min=route["unknown_stop_min"],
        unknowns_to_stop_max=route["unknown_stop_max"],
        any_rest_before_boss=float(route["any_rest"]),
        all_paths_rest_before_boss=float(route["all_rest"]),
    )
    return result


def policy_input(state, observation, catalog):
    validate_catalog(catalog)
    validate_map_observation(state, observation)
    candidates = enumerate_candidates(state)
    act = (state.get("context") or {}).get("act")
    require(type(act) is int and act in (1, 2, 3), "Encounter damage route requires public act")
    public_map = observation.get("public_map")
    rows = []
    if public_map is None:
        rows = [{"candidate_id": candidate["candidate_id"], "summary": _zero_summary()}
                for candidate in candidates["candidates"]]
        status = "unavailable"
    else:
        graph, boss = full_route_features._public_graph(public_map)
        for candidate in candidates["candidates"]:
            request = candidate["request"]
            if request.get("action") != "select_map_node":
                summary = _zero_summary()
            else:
                position = full_route_features._coordinate(request.get("args"))
                summary = _route_summary(graph, boss, position, act, catalog["final_table"]) \
                    if position in graph else _zero_summary()
            rows.append({"candidate_id": candidate["candidate_id"], "summary": summary})
        available = sum(row["summary"]["path_available"] == 1 for row in rows)
        status = "available" if available == len(rows) else "partial" if available else "unavailable"
    value = {
        "version": VERSION,
        "decision_state_hash": state_hash(state),
        "candidate_set_hash": state_hash(candidates),
        "public_map_hash": observation.get("public_map_hash"),
        "catalog_schema": catalog["schema_version"],
        "status": status,
        "per_candidate": rows,
    }
    validate_input(state, value)
    return value


def validate_input(state, value):
    require(state.get("decision") == "map_select", "Encounter damage input requires map_select")
    require(isinstance(value, dict) and set(value) == {
        "version", "decision_state_hash", "candidate_set_hash", "public_map_hash",
        "catalog_schema", "status", "per_candidate",
    }, "Encounter damage input has unapproved fields")
    candidates = enumerate_candidates(state)
    require(value["version"] == VERSION and value["catalog_schema"] == SCHEMA
            and value["decision_state_hash"] == state_hash(state)
            and value["candidate_set_hash"] == state_hash(candidates),
            "Encounter damage input is stale")
    require(value["status"] in ("available", "partial", "unavailable")
            and isinstance(value["per_candidate"], list), "Encounter damage status differs")
    require([row.get("candidate_id") for row in value["per_candidate"]]
            == [candidate["candidate_id"] for candidate in candidates["candidates"]],
            "Encounter damage candidates differ")
    for row in value["per_candidate"]:
        require(set(row) == {"candidate_id", "summary"} and isinstance(row["summary"], dict)
                and set(row["summary"]) == set(SUMMARY_NAMES),
                "Encounter damage summary schema differs")
        values = list(row["summary"].values())
        require(all(type(number) in (int, float) and math.isfinite(number) and number >= 0
                    for number in values), "Encounter damage summary value differs")
        if row["summary"]["path_available"] == 0:
            require(all(number == 0 for number in values),
                    "Unavailable encounter damage route must remain zero")
    return True


def candidate_features(state, summary):
    require(set(summary) == set(SUMMARY_NAMES), "Encounter damage summary differs")
    result = dict.fromkeys(PARAMETERS, 0.0)
    if not summary["path_available"]:
        return result
    player = state.get("player") or {}
    hp, maximum = player.get("hp"), player.get("max_hp")
    require(type(hp) in (int, float) and type(maximum) in (int, float)
            and math.isfinite(hp) and math.isfinite(maximum) and maximum > 0 and 0 <= hp <= maximum,
            "Encounter damage utility requires public HP")
    hp_ratio = hp / maximum
    deficit = 1.0 - hp_ratio
    result.update(
        damage_q50_to_stop_min=summary["damage_q50_to_stop_min"],
        damage_q75_to_stop_min=summary["damage_q75_to_stop_min"],
        damage_q90_to_stop_min=summary["damage_q90_to_stop_min"],
        damage_q75_to_stop_max=summary["damage_q75_to_stop_max"],
        damage_q75_to_boss_min=summary["damage_q75_to_boss_min"],
        damage_q75_to_stop_excess_hp=max(0.0, summary["damage_q75_to_stop_min"] - hp_ratio),
        damage_q90_to_stop_excess_hp=max(0.0, summary["damage_q90_to_stop_min"] - hp_ratio),
        damage_q75_to_boss_excess_hp=max(0.0, summary["damage_q75_to_boss_min"] - hp_ratio),
        low_hp_damage_q75_to_stop_min=deficit * summary["damage_q75_to_stop_min"],
    )
    return result


def score(values, parameters=PRIOR):
    require(set(values) == set(PARAMETERS) and set(parameters) == set(PARAMETERS),
            "Encounter damage parameter schema differs")
    raw = sum(float(parameters[name]) * float(values[name]) for name in PARAMETERS)
    require(math.isfinite(raw), "Encounter damage score is non-finite")
    cap = CONTRACT["candidate_adjustment_abs_cap"]
    return max(-cap, min(cap, raw))


def adjust(state, packet, damage_input, parameters=PRIOR):
    result = copy.deepcopy(packet)
    applies = state.get("decision") == "map_select"
    if applies:
        validate_input(state, damage_input)
        summaries = {row["candidate_id"]: row["summary"] for row in damage_input["per_candidate"]}
    else:
        require(damage_input is None, "Non-map decision cannot use encounter damage input")
        summaries = {}
    for row in result.get("scores") or []:
        summary = summaries.get(row.get("candidate_id")) if applies else None
        covered = bool(summary and summary["path_available"])
        if covered:
            values = candidate_features(state, summary)
            adjustment = score(values, parameters)
            row["missing"] = [item for item in row.get("missing") or []
                              if item != "encounter_damage_distribution"]
            detail = {
                "applied": True,
                "known_encounter_distribution_covered": True,
                "unknown_room_damage_assumed": False,
                "summary": copy.deepcopy(summary),
            }
        else:
            values = dict.fromkeys(PARAMETERS, 0.0)
            adjustment = 0.0
            detail = {"applied": False, "reason": "unavailable_or_not_map_select"}
        row["encounter_damage_features"] = values
        row["encounter_damage_adjustment"] = adjustment
        row["encounter_damage_detail"] = detail
        row["score"] += adjustment
    result["encounter_damage_contract"] = copy.deepcopy(CONTRACT)
    result["encounter_damage_applied"] = applies
    if applies:
        result["encounter_damage_input"] = copy.deepcopy(damage_input)
    return result
