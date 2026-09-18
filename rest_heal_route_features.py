"""Exact public rest healing combined with latched public route damage."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

from decision_data import DataContractError, enumerate_candidates, materialize_candidate, state_hash
import encounter_damage_features
import full_route_features
from map_observation import validate_map_observation


VERSION = "public-rest-heal-route-v1"
ROOT = Path(__file__).resolve().parent
RELIC_TABLE_PATH = ROOT / "current_relics_eng.json"
RELIC_TABLE_SHA256 = "7379d2f141bc507fad392fd38d6d718667c6f55df5d2f6ce50ed0f5649403183"
BASE_HEAL_FRACTION = 0.30
PILLOW_ID = "RELIC.REGAL_PILLOW"
HUMIDIFIER_ID = "RELIC.STONE_HUMIDIFIER"
PARAMETERS = (
    "actual_heal_fraction",
    "current_hp_fraction",
    "projected_hp_fraction",
    "damage_q75_to_stop",
    "damage_q90_to_stop",
    "damage_q75_to_boss",
    "q75_bridge_to_stop",
    "q90_bridge_to_stop",
    "q75_bridge_to_boss",
    "route_unknowns_to_stop",
)
PRIOR = dict.fromkeys(PARAMETERS, 0.0)
PRIOR.update(
    q75_bridge_to_stop=1.00,
    q90_bridge_to_stop=.70,
    q75_bridge_to_boss=.20,
)


def require(condition, message):
    if not condition:
        raise DataContractError(message)


def _load_relic_table():
    raw = RELIC_TABLE_PATH.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == RELIC_TABLE_SHA256,
            "Current English relic table differs")
    value = json.loads(raw)
    require(isinstance(value, dict), "Current English relic table schema differs")
    expected = {
        "REGAL_PILLOW.description": (
            "Whenever you [gold]Rest[/gold], heal an additional "
            "[blue]{Heal}[/blue] HP."
        ),
        "STONE_HUMIDIFIER.description": (
            "Whenever you [gold]Rest[/gold] at a [gold]Rest Site[/gold], "
            "raise your Max HP by [blue]{MaxHp}[/blue]."
        ),
    }
    require(all(value.get(key) == text for key, text in expected.items()),
            "Current rest relic descriptions differ")
    return value


RELIC_TABLE = _load_relic_table()
CONTRACT = {
    "version": VERSION,
    "base_heal_fraction": BASE_HEAL_FRACTION,
    "base_heal_rounding": "floor_old_max_hp_times_fraction",
    "regal_pillow_amount_source": "public_relic_vars.Heal",
    "stone_humidifier_amount_source": "public_relic_vars.MaxHp",
    "stone_humidifier_semantics": "increase_max_and_current_hp_before_cap",
    "heal_cap": "new_max_hp",
    "relic_table_sha256": RELIC_TABLE_SHA256,
    "route_source": "latched_audited_public_map_selected_rest_node_and_frozen_damage_catalog",
    "hidden_encounter_or_reward_used": False,
    "future_route_choice_probability_assumed": False,
    "natural_outcomes_used_for_weight_selection": False,
    "candidate_adjustment_abs_cap": 1.0,
}


def relic_var(state, relic_id, name):
    relics = (state.get("player") or {}).get("relics") or []
    matched = [relic for relic in relics
               if isinstance(relic, dict) and relic.get("id") == relic_id]
    require(len(matched) <= 1, f"Duplicate public relic: {relic_id}")
    if not matched:
        return 0.0
    value = (matched[0].get("vars") or {}).get(name)
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            f"Public relic variable is missing: {relic_id}.{name}")
    return float(value)


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
        "hp_before": float(hp),
        "max_hp_before": float(maximum),
        "base_heal": float(base),
        "regal_pillow_heal": pillow,
        "stone_humidifier_max_hp": humidifier,
        "uncapped_hp_gain": float(uncapped_gain),
        "hp_gain": float(hp_after - hp),
        "hp_after": float(hp_after),
        "max_hp_after": float(maximum_after),
    }


def _route_aggregate(public_map, position, act, catalog):
    graph, boss = full_route_features._public_graph(public_map)
    if position not in graph or graph[position]["type"] != "RestSite":
        return None
    children = graph[position]["children"]
    summaries = [encounter_damage_features._route_summary(
        graph, boss, child, act, catalog["final_table"]
    ) for child in children]
    summaries = [summary for summary in summaries
                 if summary and summary["path_available"]]
    if not summaries:
        return None
    quantitative = [name for name in encounter_damage_features.SUMMARY_NAMES
                    if name != "path_available"]
    return {
        "outgoing_nodes": len(children),
        "available_outgoing_nodes": len(summaries),
        "best_achievable": {
            name: min(summary[name] for summary in summaries)
            for name in quantitative
        },
        "worst_available": {
            name: max(summary[name] for summary in summaries)
            for name in quantitative
        },
    }


def make_context(map_state, observation, selected_request, catalog):
    if map_state.get("decision") != "map_select":
        raise DataContractError("Rest route context requires a map decision")
    validate_map_observation(map_state, observation)
    encounter_damage_features.validate_catalog(catalog)
    space = enumerate_candidates(map_state)
    candidate = (materialize_candidate(space, selected_request)
                 if space.get("representation") == "ordered_selection_implicit_v1"
                 else next((row for row in space["candidates"]
                            if row["request"] == selected_request), None))
    require(candidate is not None, "Selected public map request is no longer legal")
    if selected_request.get("action") != "select_map_node":
        return None
    position = full_route_features._coordinate(selected_request.get("args"))
    act = (map_state.get("context") or {}).get("act")
    require(type(act) is int and act in (1, 2, 3),
            "Rest route context requires public act")
    route = _route_aggregate(observation.get("public_map"), position, act, catalog)
    if route is None:
        return None
    result = {
        "version": VERSION,
        "source_map_state_hash": state_hash(map_state),
        "public_map_hash": observation.get("public_map_hash"),
        "catalog_schema": catalog["schema_version"],
        "act": act,
        "selected_rest_position": list(position),
        "route": route,
    }
    validate_context(result)
    return result


def validate_context(value, rest_state=None):
    require(isinstance(value, dict) and set(value) == {
        "version", "source_map_state_hash", "public_map_hash", "catalog_schema",
        "act", "selected_rest_position", "route",
    }, "Rest route context schema differs")
    require(value["version"] == VERSION
            and isinstance(value["source_map_state_hash"], str)
            and isinstance(value["public_map_hash"], str)
            and isinstance(value["catalog_schema"], str)
            and value["act"] in (1, 2, 3)
            and isinstance(value["selected_rest_position"], list)
            and len(value["selected_rest_position"]) == 2
            and all(type(number) is int for number in value["selected_rest_position"]),
            "Rest route context identity differs")
    route = value["route"]
    require(isinstance(route, dict) and set(route) == {
        "outgoing_nodes", "available_outgoing_nodes",
        "best_achievable", "worst_available",
    }, "Rest route aggregate schema differs")
    require(type(route["outgoing_nodes"]) is int and route["outgoing_nodes"] > 0
            and type(route["available_outgoing_nodes"]) is int
            and 0 < route["available_outgoing_nodes"] <= route["outgoing_nodes"],
            "Rest route outgoing counts differ")
    expected = set(encounter_damage_features.SUMMARY_NAMES) - {"path_available"}
    for name in ("best_achievable", "worst_available"):
        summary = route[name]
        require(isinstance(summary, dict) and set(summary) == expected
                and all(type(number) in (int, float) and math.isfinite(number)
                        and number >= 0 for number in summary.values()),
                "Rest route summary differs")
    require(all(route["best_achievable"][name]
                <= route["worst_available"][name] + 1e-12 for name in expected),
            "Rest route best/worst bounds differ")
    if rest_state is not None:
        require(rest_state.get("decision") == "rest_site"
                and (rest_state.get("context") or {}).get("act") == value["act"],
                "Rest route context is stale")
    return True


def _option_identity(candidate):
    evidence = candidate["evidence"]
    return str(evidence.get("option_id", evidence.get("name", ""))).upper()


def candidate_features(state, candidate, context):
    values = dict.fromkeys(PARAMETERS, 0.0)
    if _option_identity(candidate) != "HEAL":
        return values, None
    projection = heal_projection(state)
    current = projection["hp_before"] / projection["max_hp_before"]
    projected = projection["hp_after"] / projection["max_hp_after"]
    route = context["route"]["best_achievable"]
    q75_stop = route["damage_q75_to_stop_min"]
    q90_stop = route["damage_q90_to_stop_min"]
    q75_boss = route["damage_q75_to_boss_min"]

    def bridge(damage):
        return max(0.0, damage - current) - max(0.0, damage - projected)

    values.update(
        actual_heal_fraction=projection["hp_gain"] / projection["max_hp_after"],
        current_hp_fraction=current,
        projected_hp_fraction=projected,
        damage_q75_to_stop=q75_stop,
        damage_q90_to_stop=q90_stop,
        damage_q75_to_boss=q75_boss,
        q75_bridge_to_stop=bridge(q75_stop),
        q90_bridge_to_stop=bridge(q90_stop),
        q75_bridge_to_boss=bridge(q75_boss),
        route_unknowns_to_stop=context["route"]["worst_available"][
            "unknowns_to_stop_max"
        ],
    )
    return values, projection


def score(values, parameters=PRIOR):
    require(set(values) == set(PARAMETERS) and set(parameters) == set(PARAMETERS),
            "Rest route parameter schema differs")
    raw = sum(float(values[name]) * float(parameters[name]) for name in PARAMETERS)
    require(math.isfinite(raw), "Rest route score is non-finite")
    cap = CONTRACT["candidate_adjustment_abs_cap"]
    return max(-cap, min(cap, raw))


def adjust(state, packet, context, parameters=PRIOR):
    result = copy.deepcopy(packet)
    applies = state.get("decision") == "rest_site" and context is not None
    if applies:
        validate_context(context, state)
        space = enumerate_candidates(state)
        by_id = {candidate["candidate_id"]: candidate
                 for candidate in space["candidates"]}
    else:
        require(context is None,
                "Rest route context supplied to a non-rest decision")
        by_id = {}
    for row in result.get("scores") or []:
        candidate = by_id.get(row.get("candidate_id"))
        values, projection = (candidate_features(state, candidate, context)
                              if candidate is not None
                              else (dict.fromkeys(PARAMETERS, 0.0), None))
        adjustment = score(values, parameters) if projection is not None else 0.0
        cleared = []
        remaining = []
        if projection is not None:
            for marker in ("actual_rest_heal_amount",
                           "future_route_damage_distribution"):
                if marker in (row.get("missing") or []):
                    cleared.append(marker)
            row["missing"] = [marker for marker in row.get("missing") or []
                              if marker not in cleared]
            if values["route_unknowns_to_stop"] > 0:
                remaining.append("unknown_room_outcomes")
                if "unknown_room_outcomes" not in row["missing"]:
                    row["missing"].append("unknown_room_outcomes")
        row["rest_heal_route_features"] = values
        row["rest_heal_route_adjustment"] = adjustment
        row["rest_heal_route_detail"] = {
            "applied": projection is not None,
            "heal_projection": projection,
            "cleared_missing": cleared,
            "remaining_uncertainty": remaining,
        }
        row["score"] += adjustment
    result["rest_heal_route_contract"] = copy.deepcopy(CONTRACT)
    result["rest_heal_route_applied"] = applies
    if applies:
        result["rest_heal_route_input"] = copy.deepcopy(context)
    return result
