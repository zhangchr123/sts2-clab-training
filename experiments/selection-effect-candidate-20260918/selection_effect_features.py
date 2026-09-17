"""Fixed utility for public, canonical card-upgrade previews.

The scorer describes only the delta shown by the current public card and its
public ``after_upgrade`` preview.  It does not infer instance modifiers,
simulate future combats, or use run outcomes.
"""
from __future__ import annotations

import copy
import math

from decision_data import DataContractError


VERSION = "public-selection-upgrade-effects-v1"
PARAMETERS = (
    "upgrade_cost_reduction",
    "upgrade_damage_gain",
    "upgrade_block_gain",
    "upgrade_draw_gain",
    "upgrade_energy_gain",
    "upgrade_weak_gain",
    "upgrade_vulnerable_gain",
    "upgrade_focus_gain",
    "upgrade_strength_gain",
    "upgrade_dexterity_gain",
    "upgrade_buffer_gain",
    "upgrade_repeat_gain",
    "upgrade_loop_gain",
    "upgrade_scaling_gain",
    "upgrade_remove_exhaust",
    "upgrade_remove_ethereal",
    "upgrade_add_retain",
    "upgrade_add_innate",
)
PRIOR = {
    "upgrade_cost_reduction": 0.65,
    "upgrade_damage_gain": 0.035,
    "upgrade_block_gain": 0.04,
    "upgrade_draw_gain": 0.45,
    "upgrade_energy_gain": 0.60,
    "upgrade_weak_gain": 0.22,
    "upgrade_vulnerable_gain": 0.22,
    "upgrade_focus_gain": 0.60,
    "upgrade_strength_gain": 0.40,
    "upgrade_dexterity_gain": 0.40,
    "upgrade_buffer_gain": 0.50,
    "upgrade_repeat_gain": 0.30,
    "upgrade_loop_gain": 0.45,
    "upgrade_scaling_gain": 0.12,
    "upgrade_remove_exhaust": 0.40,
    "upgrade_remove_ethereal": 0.20,
    "upgrade_add_retain": 0.25,
    "upgrade_add_innate": 0.15,
}
CONTRACT = {
    "version": VERSION,
    "natural_outcomes_used": False,
    "hidden_reward_or_future_state_used": False,
    "instance_upgrade_modifiers_assumed": False,
    "applies_only_to_selection_purpose": "upgrade",
    "source": "public current card plus canonical after_upgrade preview",
    "score_semantics": "fixed_expert_relative_upgrade_utility_not_win_probability",
    "candidate_adjustment_abs_cap": 3.0,
}

STAT_FEATURES = {
    "damage": "upgrade_damage_gain",
    "block": "upgrade_block_gain",
    "cards": "upgrade_draw_gain",
    "energy": "upgrade_energy_gain",
    "weakpower": "upgrade_weak_gain",
    "vulnerablepower": "upgrade_vulnerable_gain",
    "focuspower": "upgrade_focus_gain",
    "strengthpower": "upgrade_strength_gain",
    "dexteritypower": "upgrade_dexterity_gain",
    "bufferpower": "upgrade_buffer_gain",
    "repeat": "upgrade_repeat_gain",
    "loop": "upgrade_loop_gain",
}
SCALING_STATS = {"increase", "iterationpower", "playmax"}


def _keywords(value, field):
    if value is None:
        return set()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise DataContractError(f"Malformed public {field}")
    return {item.lower() for item in value}


def _stats(value, field):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise DataContractError(f"Malformed public {field}")
    result = {}
    for name, number in value.items():
        if not isinstance(name, str) or type(number) not in (int, float) or not math.isfinite(number):
            raise DataContractError(f"Malformed public {field} entry")
        result[name.lower()] = float(number)
    return result


def card_features(card):
    if not isinstance(card, dict) or not isinstance(card.get("id"), str) or not card["id"]:
        raise DataContractError("Upgrade candidate needs an identified public card")
    result = dict.fromkeys(PARAMETERS, 0.0)
    detail = {
        "card_id": card["id"],
        "preview_status": card.get("upgrade_preview_status"),
        "preview_basis": card.get("upgrade_preview_basis"),
        "instance_modifiers_copied": card.get("upgrade_preview_instance_modifiers_copied"),
        "unmodeled_stat_deltas": {},
    }
    if card.get("upgrade_preview_status") != "available":
        return result, {**detail, "applied": False, "reason": "preview_not_available"}
    after = card.get("after_upgrade")
    if not isinstance(after, dict):
        raise DataContractError("Available upgrade candidate lacks public preview")
    before_cost, after_cost = card.get("cost"), after.get("cost")
    if type(before_cost) is int and type(after_cost) is int:
        result["upgrade_cost_reduction"] = float(before_cost - after_cost)
    elif before_cost != after_cost:
        raise DataContractError("Malformed public upgrade cost")
    before_stats = _stats(card.get("stats"), "current stats")
    after_stats = _stats(after.get("stats"), "upgrade stats")
    for name in set(before_stats) | set(after_stats):
        delta = after_stats.get(name, 0.0) - before_stats.get(name, 0.0)
        if not delta:
            continue
        feature = STAT_FEATURES.get(name)
        if feature:
            result[feature] += delta
        elif name in SCALING_STATS:
            result["upgrade_scaling_gain"] += delta
        else:
            detail["unmodeled_stat_deltas"][name] = delta
    current_keywords = _keywords(card.get("keywords"), "current keywords")
    added = _keywords(after.get("added_keywords"), "added keywords")
    removed = _keywords(after.get("removed_keywords"), "removed keywords")
    result["upgrade_remove_exhaust"] = float("exhaust" in removed and "exhaust" in current_keywords)
    result["upgrade_remove_ethereal"] = float("ethereal" in removed and "ethereal" in current_keywords)
    result["upgrade_add_retain"] = float("retain" in added and "retain" not in current_keywords)
    result["upgrade_add_innate"] = float("innate" in added and "innate" not in current_keywords)
    return result, {
        **detail,
        "applied": True,
        "natural_outcomes_used": False,
        "hidden_reward_or_future_state_used": False,
    }


def candidate_features(candidate):
    cards = (candidate.get("evidence") or {}).get("cards")
    if not isinstance(cards, list) or not cards:
        raise DataContractError("Upgrade selection candidate lacks public cards")
    result = dict.fromkeys(PARAMETERS, 0.0)
    details = []
    for card in cards:
        values, detail = card_features(card)
        for name in PARAMETERS:
            result[name] += values[name]
        details.append(detail)
    return result, details


def score(values, parameters=PRIOR):
    if set(values) != set(PARAMETERS) or set(parameters) != set(PARAMETERS):
        raise DataContractError("Upgrade effect schema differs")
    raw = sum(float(parameters[name]) * float(values[name]) for name in PARAMETERS)
    if not math.isfinite(raw):
        raise DataContractError("Upgrade effect score is non-finite")
    cap = CONTRACT["candidate_adjustment_abs_cap"]
    return max(-cap, min(cap, raw))


def adjust(state, packet, candidates, parameters=PRIOR):
    result = copy.deepcopy(packet)
    purpose = result.get("selection_purpose")
    applies = state.get("decision") == "card_select" and purpose == "upgrade"
    for row in result.get("scores") or []:
        candidate = candidates.get(row.get("candidate_id"))
        if candidate is None or row.get("request") != candidate.get("request"):
            raise DataContractError("Upgrade score row/candidate mismatch")
        if applies:
            values, details = candidate_features(candidate)
            adjustment = score(values, parameters)
            row["missing"] = [
                item for item in row.get("missing") or [] if item != "selection_effect_model"
            ]
            detail = {
                "applied": True,
                "cards": details,
                "natural_outcomes_used": False,
                "hidden_reward_or_future_state_used": False,
            }
        else:
            values = dict.fromkeys(PARAMETERS, 0.0)
            adjustment = 0.0
            detail = {"applied": False, "reason": "not_upgrade_selection"}
        row["selection_effect_features"] = values
        row["selection_effect_adjustment"] = adjustment
        row["selection_effect_detail"] = detail
        row["score"] += adjustment
    result["selection_effect_contract"] = copy.deepcopy(CONTRACT)
    result["selection_effect_applied"] = applies
    return result
