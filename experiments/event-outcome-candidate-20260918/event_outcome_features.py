"""Source-bound deterministic event outcomes layered on the full candidate.

The module only uses the current public state and exact current-engine facts.
It does not use recorded outcomes, hidden RNG state, or future states. Random
event branches remain explicitly unresolved.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from decision_data import DataContractError
import event_effect_features
import reward_mechanism_features


ROOT = Path(__file__).resolve().parent
FACTS_PATH = ROOT / "event_outcome_facts.json"
FACTS_SCHEMA = "current-engine-event-outcome-facts-v1"
ENGINE_SHA256 = event_effect_features.ENGINE_SHA256
SOURCE_HASHES = {
    "Bugslayer.cs": "772fd742b0fefeb21a2f849a9d78524e5b7291bf99306cc71c9cd71fe34ce11b",
    "Exterminate.cs": "307cf98977f462c7d7dc66f0f9fbd2275b7bd108f2aa37ca3f0b43ed1c9ba3d9",
    "Squash.cs": "9cb71457028fd46cb215b872850fe3f3178e84867467f6546e69ef9bca024d0d",
    "SelfHelpBook.cs": "efaa3eeaf96fb3ca30477b12e1598bdb8374d58b87880f8129efa888ee6ed46e",
    "Sharp.cs": "1de8537303cbb6860d4f55b117c0a8cd6179f3c455456b87393c0a7d135339c5",
    "Nimble.cs": "5b1e5a9075e3f0cff0e39b644dae1a749cc6460721a13423c62231ec93f75142",
    "Swift.cs": "d8fd0ca9b8a13b21c409f2a281633b04f97cb6d303a48457e44d768c83ca1ad5",
    "ThisOrThat.cs": "4402a2f72326ffecc103ea1f2bd246cd86f07bb63df929bd362f44dc12dc70d3"
}

CONTRACT = {
    "version": "public-current-engine-deterministic-event-outcomes-v1",
    "engine_sha256": ENGINE_SHA256,
    "facts_schema": FACTS_SCHEMA,
    "natural_outcomes_used": False,
    "hidden_runtime_state_used": False,
    "random_options_resolved": False,
    "card_value_probability_calibrated": False,
    "parent_event_prior_replaced_for_exact_options": True,
    "candidate_adjustment_abs_cap": 2.0,
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DataContractError(message)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_evidence() -> dict[str, dict[str, Any]]:
    result = {}
    source_root = ROOT / "reference_facts" / "current_engine"
    for name, expected in SOURCE_HASHES.items():
        path = source_root / name
        _require(path.is_file(), f"Event outcome source missing: {name}")
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        _require(actual == expected, f"Event outcome source hash differs: {name}")
        result[name] = {"path": str(path.resolve()), "sha256": actual, "bytes": len(raw)}
    return result


def _load_facts() -> dict[str, Any]:
    facts = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
    _require(facts.get("schema_version") == FACTS_SCHEMA, "Event outcome facts schema differs")
    _require(facts.get("engine_sha256") == ENGINE_SHA256, "Event outcome engine differs")
    _require(facts.get("natural_outcomes_used") is False, "Event outcome facts use natural outcomes")
    _require(facts.get("hidden_runtime_state_used") is False, "Event outcome facts use hidden state")
    _require(isinstance(facts.get("options"), dict), "Event outcome option facts missing")
    return facts


FACTS = _load_facts()


def _number(value: Any) -> float | None:
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    return float(value)


def _identity(candidate: dict[str, Any]) -> str | None:
    evidence = candidate.get("evidence") or {}
    identity = event_effect_features.option_identity(evidence.get("text_key"))
    return ":".join(identity) if identity else None


def _stats(card: dict[str, Any]) -> dict[str, float]:
    raw = card.get("stats")
    if raw is None:
        return {}
    _require(isinstance(raw, dict), "Public deck card stats must be an object or null")
    result = {}
    for key, value in raw.items():
        number = _number(value)
        _require(isinstance(key, str) and number is not None, "Malformed public deck card stat")
        result[key.lower()] = number
    return result


def _cost(card: dict[str, Any]) -> float:
    value = _number(card.get("cost"))
    return value if value is not None and value >= 0 else 2.0


def _attack_hits(policy: Any, card: dict[str, Any], state: dict[str, Any]) -> float:
    detail = policy._card_score(card, state)
    hits = _number((detail.get("features") or {}).get("attack_hit_count"))
    return hits if hits is not None and hits >= 1 else 1.0


def _self_help_value(policy: Any, fact: dict[str, Any], state: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    deck = (state.get("player") or {}).get("deck")
    _require(isinstance(deck, list), "Self Help Book requires a public deck")
    card_type = fact["card_type"]
    eligible = [card for card in deck if isinstance(card, dict) and card.get("type") == card_type]
    if fact.get("requires_positive_block"):
        eligible = [card for card in eligible if _stats(card).get("block", 0.0) > 0]
    _require(eligible, f"Source-bound Self Help option has no eligible {card_type}")
    amount = float(fact["amount"])
    target_values = []
    for card in eligible:
        if fact["effect"] == "powered_attack_damage_additive":
            # Reuse the parent card model's damage-per-cost scale. The exact
            # enchantment adds Amount to every powered attack hit.
            hits = _attack_hits(policy, card, state)
            value = 0.18 * amount * hits / (1.0 + _cost(card))
        elif fact["effect"] == "block_additive":
            deficit = 0.0
            player = state.get("player") or {}
            hp, maximum = _number(player.get("hp")), _number(player.get("max_hp"))
            if hp is not None and maximum is not None and maximum > 0:
                deficit = max(0.0, 1.0 - hp / maximum)
            value = (0.15 + 0.08 * deficit) * amount / (1.0 + _cost(card))
        elif fact["effect"] == "draw_once_on_first_play_each_combat":
            value = 0.60 * amount / (1.0 + _cost(card))
        else:
            raise DataContractError("Unsupported Self Help enchantment fact")
        target_values.append({"card_id": card.get("id"), "value": value})
    best = max(target_values, key=lambda row: row["value"])
    return best["value"], {
        "eligible_cards": len(eligible),
        "best_target": best,
        "target_values": target_values,
        "enchantment": fact["enchantment"],
        "amount": fact["amount"],
        "effect": fact["effect"],
    }


def _bugslayer_value(fact: dict[str, Any], state: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    card = fact["card"]
    divisor = 1.0 + float(card["cost"])
    damage_value = 0.18 * float(card["damage"]) * float(card["hits"]) / divisor
    vulnerable_value = reward_mechanism_features.PRIOR["vulnerable_amount"] * float(card["vulnerable"])
    aoe_value = reward_mechanism_features.PRIOR["aoe"] if card["target"] == "AllEnemies" else 0.0
    deck = (state.get("player") or {}).get("deck") or []
    copies = sum(isinstance(row, dict) and row.get("id") == card["id"] for row in deck)
    acquisition_cost = 0.75 + 0.12 * min(4, copies)
    value = damage_value + vulnerable_value + aoe_value - acquisition_cost
    return value, {
        "card": copy.deepcopy(card),
        "existing_copies": copies,
        "components": {
            "damage": damage_value,
            "vulnerable": vulnerable_value,
            "aoe": aoe_value,
            "acquisition_opportunity_cost": -acquisition_cost,
        },
    }


def candidate_adjustment(policy: Any, state: dict[str, Any], row: dict[str, Any], candidate: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    if state.get("decision") != "event_choice" or (row.get("request") or {}).get("action") != "choose_option":
        return 0.0, {"applied": False, "reason": "not_event_option"}
    _require(row.get("request") == candidate.get("request"), "Event outcome row/candidate binding differs")
    identity = _identity(candidate)
    fact = FACTS["options"].get(identity)
    if fact is None:
        return 0.0, {"applied": False, "reason": "random_or_unmodeled_option", "identity": identity}
    if fact["kind"] == "deterministic_add_card":
        exact_score, value_detail = _bugslayer_value(fact, state)
    elif fact["kind"] == "deterministic_select_enchant":
        exact_score, value_detail = _self_help_value(policy, fact, state)
    elif fact["kind"] == "deterministic_public_resolved":
        exact_score = float(row["score"])
        value_detail = {"parent_score_authoritative": True}
    else:
        raise DataContractError("Unsupported deterministic event fact")
    before = _number(row.get("score"))
    _require(before is not None, "Event outcome parent score is not finite")
    adjustment = exact_score - before
    cap = CONTRACT["candidate_adjustment_abs_cap"]
    _require(abs(adjustment) <= cap + 1e-12, "Event outcome adjustment exceeds fixed cap")
    return adjustment, {
        "applied": True,
        "identity": identity,
        "kind": fact["kind"],
        "source": fact["source"],
        "parent_score": before,
        "exact_score": exact_score,
        "value_detail": value_detail,
        "natural_outcomes_used": False,
        "hidden_runtime_state_used": False,
    }


def adjust(policy: Any, state: dict[str, Any], packet: dict[str, Any], candidates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result = copy.deepcopy(packet)
    applied = 0
    for row in result.get("scores") or []:
        candidate = candidates.get(row.get("candidate_id"))
        _require(candidate is not None, "Event outcome candidate missing")
        adjustment, detail = candidate_adjustment(policy, state, row, candidate)
        row["event_outcome_adjustment"] = adjustment
        row["event_outcome_detail"] = detail
        row["score"] += adjustment
        if detail.get("applied"):
            applied += 1
            missing = set(row.get("missing") or [])
            missing.discard("event_outcome_probability_model")
            missing.discard("unmodeled_event_effect")
            missing.add("event_card_value_calibration") if detail["kind"] != "deterministic_public_resolved" else None
            row["missing"] = sorted(missing)
            row.setdefault("reasons", []).append({
                "source": CONTRACT["version"],
                "score": adjustment,
                "explanation": "Current-engine deterministic event outcome with fixed public-state utility",
            })
    skip = next((row["score"] for row in result.get("scores") or [] if row.get("is_skip")), None)
    for row in result.get("scores") or []:
        row["delta_from_skip"] = None if skip is None else row["score"] - skip
    result["event_outcome_contract"] = copy.deepcopy(CONTRACT)
    result["event_outcome_applied_rows"] = applied
    return result
