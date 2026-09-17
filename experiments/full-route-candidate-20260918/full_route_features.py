"""Fixed utility from complete public paths to the exported act boss.

The input is derived only from the already audited public map observation.  It
does not identify encounters, predict damage, open rooms, or use run outcomes.
"""
from __future__ import annotations

import copy
from functools import lru_cache
import math

from decision_data import DataContractError, enumerate_candidates, state_hash
from map_observation import validate_map_observation


VERSION = "public-full-route-effects-v1"
SUMMARY_NAMES = (
    "path_available",
    "min_steps",
    "max_steps",
    "min_known_fights",
    "max_known_fights",
    "min_elites",
    "max_elites",
    "min_rests",
    "max_rests",
    "min_unknowns",
    "max_unknowns",
    "path_flexibility",
    "branch_density",
)
PARAMETERS = (
    "route_min_known_fights",
    "route_max_known_fights",
    "route_min_elites",
    "route_max_rests",
    "route_no_rest_possible",
    "route_all_paths_rest",
    "route_optional_elite",
    "route_path_flexibility",
    "route_branch_density",
    "low_hp_route_min_known_fights",
    "low_hp_route_min_elites",
    "low_hp_route_no_rest_possible",
    "low_hp_route_max_rests",
    "healthy_route_optional_elite",
    "late_act_route_min_elites",
)
PRIOR = {
    "route_min_known_fights": -0.03,
    "route_max_known_fights": -0.01,
    "route_min_elites": -0.10,
    "route_max_rests": 0.05,
    "route_no_rest_possible": -0.15,
    "route_all_paths_rest": 0.08,
    "route_optional_elite": 0.04,
    "route_path_flexibility": 0.12,
    "route_branch_density": 0.08,
    "low_hp_route_min_known_fights": -0.08,
    "low_hp_route_min_elites": -0.30,
    "low_hp_route_no_rest_possible": -0.50,
    "low_hp_route_max_rests": 0.18,
    "healthy_route_optional_elite": 0.08,
    "late_act_route_min_elites": -0.10,
}
CONTRACT = {
    "version": VERSION,
    "source": "audited public full-map topology already exposed before the map choice",
    "natural_outcomes_used": False,
    "hidden_rooms_or_encounters_used": False,
    "encounter_damage_distribution_claimed": False,
    "future_player_choices_assumed_random": False,
    "path_ranges_are_public_topology_not_probabilities": True,
    "path_count_cap": 1_000_000,
    "candidate_adjustment_abs_cap": 2.0,
}
COUNT_TYPES = {
    "known_fights": {"Monster", "Elite"},
    "elites": {"Elite"},
    "rests": {"RestSite"},
    "unknowns": {"Unknown", "Unassigned"},
}


def require(condition, message):
    if not condition:
        raise DataContractError(message)


def _coordinate(value):
    require(isinstance(value, dict) and type(value.get("col")) is int
            and type(value.get("row")) is int, "Full route needs explicit coordinates")
    return value["col"], value["row"]


def _public_graph(public_map):
    require(isinstance(public_map, dict) and isinstance(public_map.get("nodes"), list),
            "Full route needs the whitelisted public map")
    boss_value = public_map.get("boss")
    require(isinstance(boss_value, list) and len(boss_value) == 2
            and all(type(value) is int for value in boss_value), "Public boss coordinate differs")
    boss = tuple(boss_value)
    graph = {}
    for item in public_map["nodes"]:
        position = _coordinate(item)
        require(position not in graph and isinstance(item.get("type"), str)
                and isinstance(item.get("children"), list), "Malformed public route node")
        children = []
        for child in item["children"]:
            require(isinstance(child, list) and len(child) == 2
                    and all(type(value) is int for value in child), "Malformed public route edge")
            children.append(tuple(child))
        require(len(children) == len(set(children)), "Duplicate public route edge")
        graph[position] = {"type": item["type"], "children": tuple(children)}
    require(boss in graph and graph[boss] == {"type": "Boss", "children": ()},
            "Public route boss differs")
    require(all(child in graph for node in graph.values() for child in node["children"]),
            "Public route has dangling edge")
    return graph, boss


def _summary(graph, boss, start):
    cap = CONTRACT["path_count_cap"]

    @lru_cache(None)
    def walk(position):
        node = graph[position]
        if position == boss:
            zeros = {name: 0 for name in COUNT_TYPES}
            return {"paths": 1, "min_steps": 0, "max_steps": 0,
                    "mins": zeros, "maxs": zeros}
        children = [walk(child) for child in node["children"]]
        children = [child for child in children if child is not None]
        if not children:
            return None
        own = {name: int(node["type"] in types) for name, types in COUNT_TYPES.items()}
        return {
            "paths": min(cap, sum(child["paths"] for child in children)),
            "min_steps": 1 + min(child["min_steps"] for child in children),
            "max_steps": 1 + max(child["max_steps"] for child in children),
            "mins": {
                name: own[name] + min(child["mins"][name] for child in children)
                for name in COUNT_TYPES
            },
            "maxs": {
                name: own[name] + max(child["maxs"][name] for child in children)
                for name in COUNT_TYPES
            },
        }

    route = walk(start)
    if route is None:
        return dict.fromkeys(SUMMARY_NAMES, 0.0)
    reachable = set()
    stack = [start]
    while stack:
        position = stack.pop()
        if position in reachable or walk(position) is None:
            continue
        reachable.add(position)
        stack.extend(graph[position]["children"])
    branch_nodes = sum(len(graph[position]["children"]) >= 2 for position in reachable)
    return {
        "path_available": 1.0,
        "min_steps": float(route["min_steps"]),
        "max_steps": float(route["max_steps"]),
        "min_known_fights": float(route["mins"]["known_fights"]),
        "max_known_fights": float(route["maxs"]["known_fights"]),
        "min_elites": float(route["mins"]["elites"]),
        "max_elites": float(route["maxs"]["elites"]),
        "min_rests": float(route["mins"]["rests"]),
        "max_rests": float(route["maxs"]["rests"]),
        "min_unknowns": float(route["mins"]["unknowns"]),
        "max_unknowns": float(route["maxs"]["unknowns"]),
        "path_flexibility": min(1.0, math.log2(route["paths"] + 1) / 8.0),
        "branch_density": branch_nodes / max(1, len(reachable)),
    }


def policy_input(state, observation):
    validate_map_observation(state, observation)
    candidates = enumerate_candidates(state)
    public_map = observation.get("public_map")
    rows = []
    if public_map is None:
        for candidate in candidates["candidates"]:
            rows.append({"candidate_id": candidate["candidate_id"],
                         "summary": dict.fromkeys(SUMMARY_NAMES, 0.0)})
        status = "unavailable"
    else:
        graph, boss = _public_graph(public_map)
        for candidate in candidates["candidates"]:
            request = candidate["request"]
            if request.get("action") != "select_map_node":
                summary = dict.fromkeys(SUMMARY_NAMES, 0.0)
            else:
                position = _coordinate(request.get("args"))
                summary = _summary(graph, boss, position) if position in graph else dict.fromkeys(SUMMARY_NAMES, 0.0)
            rows.append({"candidate_id": candidate["candidate_id"], "summary": summary})
        available = sum(row["summary"]["path_available"] == 1 for row in rows)
        status = "available" if available == len(rows) else "partial" if available else "unavailable"
    value = {
        "version": VERSION,
        "decision_state_hash": state_hash(state),
        "candidate_set_hash": state_hash(candidates),
        "public_map_hash": observation.get("public_map_hash"),
        "status": status,
        "per_candidate": rows,
    }
    validate_input(state, value)
    return value


def validate_input(state, value):
    require(state.get("decision") == "map_select", "Full route input requires map_select")
    require(isinstance(value, dict) and set(value) == {
        "version", "decision_state_hash", "candidate_set_hash", "public_map_hash", "status", "per_candidate"
    }, "Full route input has unapproved fields")
    candidates = enumerate_candidates(state)
    require(value["version"] == VERSION
            and value["decision_state_hash"] == state_hash(state)
            and value["candidate_set_hash"] == state_hash(candidates), "Full route input is stale")
    require(value["status"] in ("available", "partial", "unavailable")
            and isinstance(value["per_candidate"], list), "Full route status differs")
    require([row.get("candidate_id") for row in value["per_candidate"]]
            == [candidate["candidate_id"] for candidate in candidates["candidates"]],
            "Full route candidates differ")
    for row in value["per_candidate"]:
        require(set(row) == {"candidate_id", "summary"} and isinstance(row["summary"], dict)
                and set(row["summary"]) == set(SUMMARY_NAMES), "Full route summary schema differs")
        for number in row["summary"].values():
            require(type(number) in (int, float) and math.isfinite(number) and number >= 0,
                    "Full route summary value differs")
        if row["summary"]["path_available"] == 0:
            require(all(number == 0 for number in row["summary"].values()),
                    "Unavailable full route must remain zero")
    return True


def candidate_features(state, summary):
    require(set(summary) == set(SUMMARY_NAMES), "Full route summary differs")
    result = dict.fromkeys(PARAMETERS, 0.0)
    if not summary["path_available"]:
        return result
    player = state.get("player") or {}
    hp, maximum = player.get("hp"), player.get("max_hp")
    act = (state.get("context") or {}).get("act")
    require(type(hp) in (int, float) and type(maximum) in (int, float)
            and math.isfinite(hp) and math.isfinite(maximum) and maximum > 0 and 0 <= hp <= maximum,
            "Full route utility requires public HP")
    require(type(act) is int and act in (1, 2, 3), "Full route utility requires public act")
    deficit = 1.0 - hp / maximum
    healthy = hp / maximum
    no_rest = float(summary["max_rests"] == 0)
    all_paths_rest = float(summary["min_rests"] > 0)
    optional_elite = float(summary["max_elites"] > summary["min_elites"])
    result.update(
        route_min_known_fights=summary["min_known_fights"],
        route_max_known_fights=summary["max_known_fights"],
        route_min_elites=summary["min_elites"],
        route_max_rests=summary["max_rests"],
        route_no_rest_possible=no_rest,
        route_all_paths_rest=all_paths_rest,
        route_optional_elite=optional_elite,
        route_path_flexibility=summary["path_flexibility"],
        route_branch_density=summary["branch_density"],
        low_hp_route_min_known_fights=deficit * summary["min_known_fights"],
        low_hp_route_min_elites=deficit * summary["min_elites"],
        low_hp_route_no_rest_possible=deficit * no_rest,
        low_hp_route_max_rests=deficit * summary["max_rests"],
        healthy_route_optional_elite=healthy * optional_elite,
        late_act_route_min_elites=float(act == 3) * summary["min_elites"],
    )
    return result


def score(values, parameters=PRIOR):
    require(set(values) == set(PARAMETERS) and set(parameters) == set(PARAMETERS),
            "Full route parameter schema differs")
    raw = sum(float(parameters[name]) * float(values[name]) for name in PARAMETERS)
    require(math.isfinite(raw), "Full route score is non-finite")
    cap = CONTRACT["candidate_adjustment_abs_cap"]
    return max(-cap, min(cap, raw))


def adjust(state, packet, route_input, parameters=PRIOR):
    result = copy.deepcopy(packet)
    applies = state.get("decision") == "map_select"
    if applies:
        validate_input(state, route_input)
        summaries = {row["candidate_id"]: row["summary"] for row in route_input["per_candidate"]}
    else:
        require(route_input is None, "Non-map decision cannot use full route input")
        summaries = {}
    for row in result.get("scores") or []:
        if applies:
            summary = summaries.get(row.get("candidate_id"))
            require(summary is not None, "Full route score row is absent from input")
            values = candidate_features(state, summary)
            adjustment = score(values, parameters)
            detail = {"applied": True, "summary": copy.deepcopy(summary),
                      "natural_outcomes_used": False, "hidden_rooms_or_encounters_used": False}
            row["missing"] = [item for item in row.get("missing") or []
                              if item != "full_route_evaluation"]
        else:
            values = dict.fromkeys(PARAMETERS, 0.0)
            adjustment = 0.0
            detail = {"applied": False, "reason": "not_map_select"}
        row["full_route_features"] = values
        row["full_route_adjustment"] = adjustment
        row["full_route_detail"] = detail
        row["score"] += adjustment
    result["full_route_contract"] = copy.deepcopy(CONTRACT)
    result["full_route_applied"] = applies
    if applies:
        result["full_route_input"] = copy.deepcopy(route_input)
    return result
