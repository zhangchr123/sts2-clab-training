"""Fixed public reward semantics layered over the validated parent score."""
from __future__ import annotations

import copy
import math

from decision_data import DataContractError, enumerate_candidates, materialize_candidate
from functional_role_features import roles
from initial_policy import card_id, card_mechanisms
from reward_mechanism_facts import FACTS, REMAINING_MISSING, CONTRACT, validate_card


VERSION = "current-reward-mechanism-features-v2"
PARAMETERS = (
    "new_draw_per_cost", "new_immediate_energy_per_cost", "new_next_energy_per_cost",
    "weak_amount", "vulnerable_amount", "lightning_per_cost", "frost_per_cost",
    "dark_per_cost", "plasma_per_cost", "aoe", "generated_status_burden",
    "exhaust_control", "orb_slots", "strength_dexterity", "lost_orb_slots",
    "fixed_multihit_extra_damage_per_cost", "self_cost_reduction", "random_attack",
    "random_power", "discard_retrieval", "next_power_free", "claw_scaling",
    "orb_scaled_attack_support", "unique_orb_draw_support", "lightning_hook_support",
    "power_hook_support", "status_hook_support", "zero_cost_attack_hook_support",
    "orb_passive_support", "status_cost_reduction_support", "lightning_history_support",
    "energy_multiplier_support", "sustained_focus_support", "conditional_effect",
)
PRIOR = dict.fromkeys(PARAMETERS, 0.0)
PRIOR.update(
    new_draw_per_cost=.30, new_immediate_energy_per_cost=.42,
    new_next_energy_per_cost=.28, weak_amount=.10, vulnerable_amount=.12,
    lightning_per_cost=.18, frost_per_cost=.24, dark_per_cost=.16,
    plasma_per_cost=.34, aoe=.10, generated_status_burden=-.18,
    exhaust_control=.18, orb_slots=.10, strength_dexterity=.07,
    lost_orb_slots=-.16, fixed_multihit_extra_damage_per_cost=.18,
    self_cost_reduction=.10, random_attack=.18, random_power=.16,
    discard_retrieval=.22, next_power_free=.16, claw_scaling=.12,
    orb_scaled_attack_support=.22, unique_orb_draw_support=.24,
    lightning_hook_support=.24, power_hook_support=.22,
    status_hook_support=.24, zero_cost_attack_hook_support=.25,
    orb_passive_support=.22, status_cost_reduction_support=.18,
    lightning_history_support=.26, energy_multiplier_support=.24,
    sustained_focus_support=.20, conditional_effect=-.03,
)
FEATURE_CONTRACT = {
    "version": VERSION,
    "facts_contract": CONTRACT,
    "candidate_adjustment_abs_cap": 1.25,
    "policy_weights_fitted": False,
    "natural_outcomes_used_for_weight_selection": False,
    "description_and_current_stats_required": True,
    "future_condition_probabilities_assumed": False,
}


def require(condition, message):
    if not condition:
        raise DataContractError(message)


def _number(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) else 0.0


def _energy_cost(card, action):
    value = card.get("card_cost") if action == "buy_card" else card.get("cost")
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            "Covered reward requires current public energy cost")
    return float(value)


def _cards_for_candidate(state, packet, row, candidate):
    action = row["request"]["action"]
    if action in ("select_card_reward", "buy_card"):
        return [candidate["evidence"]]
    if action == "select_bundle":
        cards = candidate["evidence"].get("cards")
        require(isinstance(cards, list), "Reward bundle cards differ")
        return cards
    if action == "select_cards" and packet.get("selection_purpose") == "acquire":
        cards = candidate["evidence"].get("cards")
        require(isinstance(cards, list), "Reward selection cards differ")
        return cards
    return []


def _deck_context(state):
    deck = (state.get("player") or {}).get("deck")
    require(isinstance(deck, list) and deck, "Reward semantics require public deck")
    role_sets = [roles(card) for card in deck]
    mechanisms = [card_mechanisms(card) for card in deck]
    orb_types = set()
    for tags in mechanisms:
        for tag, orb in (("lightning_source", "lightning"), ("frost_source", "frost"),
                         ("dark_source", "dark"), ("plasma_source", "plasma")):
            if tag in tags:
                orb_types.add(orb)
    return {
        "size": len(deck),
        "orb_source_density": sum(bool(tags & {"lightning_source", "frost_source", "dark_source", "random_orb_source", "plasma_source"}) for tags in mechanisms) / len(deck),
        "lightning_density": sum("lightning_source" in tags for tags in mechanisms) / len(deck),
        "power_density": sum(card.get("type") == "Power" for card in deck) / len(deck),
        "status_density": sum("status_source" in tags or card.get("type") in ("Status", "Curse") for card, tags in zip(deck, mechanisms)) / len(deck),
        "zero_cost_attack_density": sum(card.get("type") == "Attack" and card.get("cost") == 0 for card in deck) / len(deck),
        "orb_types": len(orb_types),
        "claws": sum(card_id(card) == "CLAW" for card in deck),
        "draw_density": sum("draw" in role_set for role_set in role_sets) / len(deck),
        "energy_density": sum(bool(role_set & {"immediate_energy", "next_energy", "plasma", "energy_multiplier"}) for role_set in role_sets) / len(deck),
    }


def candidate_features(state, packet, row, candidate):
    result = dict.fromkeys(PARAMETERS, 0.0)
    cards = _cards_for_candidate(state, packet, row, candidate)
    if not cards:
        return result, [], [], []
    context = _deck_context(state)
    covered, cleared, remaining = [], set(), set()
    original_missing = set(row.get("missing") or [])
    newly_covered_mechanism = "mechanism_coverage" in original_missing
    for card in cards:
        fact = validate_card(card)
        if fact is None:
            continue
        cid = card_id(card)
        effects = fact["effects"]
        stats = {str(key).lower(): value for key, value in (card.get("stats") or {}).items()}
        action = row["request"]["action"]
        cost = _energy_cost(card, action)
        divisor = 1.0 + cost
        covered.append(cid)
        cleared.add("mechanism_coverage")
        if not fact["covered_stats"]:
            cleared.add("current_card_stats")
        cleared.update("unmodeled_stats:" + name for name in fact["covered_stats"])
        if "draw" in effects and "cards_effect_semantics" in original_missing:
            result["new_draw_per_cost"] += _number(stats.get(effects["draw"])) / divisor
            cleared.add("cards_effect_semantics")
        if "conditional_draw" in effects:
            result["new_draw_per_cost"] += .5 * _number(stats.get(effects["conditional_draw"])) / divisor
            result["conditional_effect"] += 1
            cleared.add("cards_effect_semantics")
        if "immediate_energy" in effects and "energy_effect_semantics" in original_missing:
            result["new_immediate_energy_per_cost"] += _number(stats.get(effects["immediate_energy"])) / divisor
            cleared.add("energy_effect_semantics")
        if "next_energy" in effects:
            result["new_next_energy_per_cost"] += _number(stats.get(effects["next_energy"])) / divisor
            cleared.add("energy_effect_semantics")
        for effect, feature in (("weak", "weak_amount"), ("conditional_weak", "weak_amount"),
                                ("vulnerable", "vulnerable_amount")):
            if effect in effects:
                result[feature] += _number(stats.get(effects[effect]))
                result["conditional_effect"] += float(effect == "conditional_weak")
        if newly_covered_mechanism:
            for effect, feature in (("lightning", "lightning_per_cost"),
                                    ("frost", "frost_per_cost"),
                                    ("dark", "dark_per_cost"),
                                    ("plasma", "plasma_per_cost")):
                if effect in effects:
                    result[feature] += _number(effects[effect]) / divisor
            if effects.get("frost_per_enemy"):
                # Enemy count is future information.  Give Chill credit for one
                # guaranteed target and retain the explicit uncertainty marker.
                result["frost_per_cost"] += 1.0 / divisor
                result["conditional_effect"] += 1.0
        result["aoe"] += float(bool(effects.get("aoe")))
        if newly_covered_mechanism:
            result["generated_status_burden"] += _number(effects.get("generated_status_count"))
        result["exhaust_control"] += float(bool(effects.get("exhaust_control")))
        if "orb_slots" in effects:
            result["orb_slots"] += _number(stats.get(effects["orb_slots"]))
        if "strength" in effects:
            result["strength_dexterity"] += _number(stats.get(effects["strength"]))
        if "dexterity" in effects:
            result["strength_dexterity"] += _number(stats.get(effects["dexterity"]))
        if "lose_orb_slots" in effects:
            result["lost_orb_slots"] += _number(stats.get(effects["lose_orb_slots"]))
        if "fixed_hits" in effects:
            result["fixed_multihit_extra_damage_per_cost"] += max(
                0.0, _number(effects["fixed_hits"]) - 1
            ) * _number(stats.get("damage")) / divisor
        result["self_cost_reduction"] += float(bool(effects.get("self_cost_reduction")))
        result["random_attack"] += float(bool(effects.get("random_attack_from_draw")))
        result["random_power"] += float(bool(effects.get("random_zero_cost_power")))
        if newly_covered_mechanism:
            result["discard_retrieval"] += float(bool(effects.get("discard_retrieval")))
        result["next_power_free"] += float(bool(effects.get("next_power_free")))
        if "claw_increase" in effects:
            result["claw_scaling"] += _number(stats.get(effects["claw_increase"])) * (1 + context["claws"]) / divisor
        result["orb_scaled_attack_support"] += float(bool(effects.get("orb_scaled_attack"))) * context["orb_source_density"]
        result["unique_orb_draw_support"] += float(bool(effects.get("unique_orb_draw"))) * min(1.0, context["orb_types"] / 2)
        if "delayed_lightning" in effects:
            result["lightning_hook_support"] += _number(stats.get(effects["delayed_lightning"])) / divisor
        if "lightning_evoke_damage" in effects:
            result["lightning_hook_support"] += context["lightning_density"] * _number(stats.get(effects["lightning_evoke_damage"])) / 8
        if "power_lightning" in effects:
            result["power_hook_support"] += context["power_density"] * _number(stats.get(effects["power_lightning"]))
        if "status_aoe" in effects:
            result["status_hook_support"] += context["status_density"] * _number(stats.get(effects["status_aoe"])) / 5
        if "status_draw" in effects:
            result["status_hook_support"] += context["status_density"] * _number(stats.get(effects["status_draw"]))
        if "zero_cost_attack_return" in effects:
            result["zero_cost_attack_hook_support"] += context["zero_cost_attack_density"] * _number(stats.get(effects["zero_cost_attack_return"]))
        if "orb_passive_repeat" in effects:
            result["orb_passive_support"] += context["orb_source_density"] * _number(stats.get(effects["orb_passive_repeat"]))
        result["status_cost_reduction_support"] += float(bool(effects.get("status_cost_reduction"))) * context["status_density"]
        result["lightning_history_support"] += float(bool(effects.get("lightning_history_scaling"))) * context["lightning_density"]
        result["energy_multiplier_support"] += float(bool(effects.get("energy_multiplier"))) * (context["draw_density"] + context["energy_density"])
        if newly_covered_mechanism and "sustained_focus" in effects:
            result["sustained_focus_support"] += _number(stats.get(effects["sustained_focus"])) * context["orb_source_density"]
        remaining.update(REMAINING_MISSING.get(cid, ()))
    require(all(math.isfinite(value) and value >= 0 for name, value in result.items()
                if name != "generated_status_burden"), "Reward feature is invalid")
    return result, covered, sorted(cleared & original_missing), sorted(remaining)


def score(values, parameters=PRIOR):
    require(set(values) == set(PARAMETERS) and set(parameters) == set(PARAMETERS),
            "Reward parameter schema differs")
    raw = sum(float(values[name]) * float(parameters[name]) for name in PARAMETERS)
    require(math.isfinite(raw), "Reward semantic score is non-finite")
    cap = FEATURE_CONTRACT["candidate_adjustment_abs_cap"]
    return max(-cap, min(cap, raw))


def adjust(state, packet, parameters=PRIOR):
    result = copy.deepcopy(packet)
    space = enumerate_candidates(state)
    by_id = None if space.get("representation") == "ordered_selection_implicit_v1" else {
        candidate["candidate_id"]: candidate for candidate in space["candidates"]
    }
    for row in result.get("scores") or []:
        candidate = materialize_candidate(space, row["request"]) if by_id is None else by_id[row["candidate_id"]]
        values, covered, cleared, remaining = candidate_features(state, result, row, candidate)
        adjustment = score(values, parameters) if covered else 0.0
        row["reward_mechanism_features"] = values
        row["reward_mechanism_adjustment"] = adjustment
        row["reward_mechanism_detail"] = {
            "applied": bool(covered),
            "covered_cards": covered,
            "cleared_missing": cleared,
            "remaining_future_uncertainty": remaining,
        }
        row["missing"] = [item for item in row.get("missing") or [] if item not in cleared]
        row["missing"].extend(item for item in remaining if item not in row["missing"])
        row["score"] += adjustment
    result["reward_mechanism_contract"] = copy.deepcopy(FEATURE_CONTRACT)
    return result
