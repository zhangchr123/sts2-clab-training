"""Source-bound deterministic event outcomes layered on the full candidate.

The module only uses the current public state and exact current-engine facts.
It does not use recorded outcomes, hidden RNG state, or future states. Random
event branches remain explicitly unresolved.
"""
from __future__ import annotations

import copy
import hashlib
import itertools
import json
import math
from pathlib import Path
from typing import Any

from decision_data import DataContractError
import event_effect_features
import reward_mechanism_features


ROOT = Path(__file__).resolve().parent
FACTS_PATH = ROOT / "event_outcome_facts.json"
FACTS_SCHEMA = "current-engine-event-outcome-facts-v2"
ENGINE_SHA256 = event_effect_features.ENGINE_SHA256
SOURCE_HASHES = {
    "Bugslayer.cs": "772fd742b0fefeb21a2f849a9d78524e5b7291bf99306cc71c9cd71fe34ce11b",
    "Exterminate.cs": "307cf98977f462c7d7dc66f0f9fbd2275b7bd108f2aa37ca3f0b43ed1c9ba3d9",
    "Squash.cs": "9cb71457028fd46cb215b872850fe3f3178e84867467f6546e69ef9bca024d0d",
    "SelfHelpBook.cs": "efaa3eeaf96fb3ca30477b12e1598bdb8374d58b87880f8129efa888ee6ed46e",
    "Sharp.cs": "1de8537303cbb6860d4f55b117c0a8cd6179f3c455456b87393c0a7d135339c5",
    "Nimble.cs": "5b1e5a9075e3f0cff0e39b644dae1a749cc6460721a13423c62231ec93f75142",
    "Swift.cs": "d8fd0ca9b8a13b21c409f2a281633b04f97cb6d303a48457e44d768c83ca1ad5",
    "ThisOrThat.cs": "4402a2f72326ffecc103ea1f2bd246cd86f07bb63df929bd362f44dc12dc70d3",
    "TheFutureOfPotions.cs": "d41b850f9c988274803a7fdac9ce15c5ed372d35fd1a8f5c69e481a8fef1989a",
    "CardFactory.cs": "6e404e3de100d5477dd77cc91d54b251da3f089468ae685097964cb4ef16a95e",
    "CardCreationOptions.cs": "c87c4b261686d2b1c54c578aa425734c4ea17eac84b4e19049e41278647b6a73",
    "CardReward.cs": "352e40b1010d2388ed8d1581e527a92bbdf7b9d9a258cfa5ddf9b2f3f62ba40a",
}
BRIDGE_HASHES = {
    "defect-current-public-reward-pool-v1.json": "5d9ff0baedfff3e8d6988db48ee6e6be387d06606b06a84108a0df3d833f1d7f",
    "DefectRewardPoolProbe.cs": "ec81c7b0e39b6b60705925a3b64fd4ba71e47a56fe3a5114cb68768798d46310",
    "event-option-vars-live-probe-input.jsonl": "59fe905bdf542bc6a6d7336630b33da3d8f6ce63b23ba98f7b302c056434e0df",
    "event-option-vars-live-probe-output.jsonl": "262cabea0e4946691978be7fca55ab29bea94eebf1a3670edbe75ac04717d404",
    "RunSimulator.EventOptionVars.cs": "84257d083fde432b8fbe329e72d1cf5f6366bb02ecfc486736d67460be94638c",
    "cards_eng.json": "c469a0be87d57c1476b75a5d0d3031cebf47e65d380a4646aae0028a20c993c0",
}
REWARD_POOL_PATH = ROOT / "reference_facts" / "bridge" / "defect-current-public-reward-pool-v1.json"
CARD_LOCALIZATION_PATH = ROOT / "reference_facts" / "bridge" / "cards_eng.json"

CONTRACT = {
    "version": "public-current-engine-event-outcomes-v2",
    "engine_sha256": ENGINE_SHA256,
    "facts_schema": FACTS_SCHEMA,
    "natural_outcomes_used": False,
    "hidden_runtime_state_used": False,
    "other_random_options_resolved": False,
    "source_bound_random_distribution_options": ["THE_FUTURE_OF_POTIONS:POTION"],
    "card_value_probability_calibrated": False,
    "parent_event_prior_replaced_for_exact_options": True,
    "future_potions_reward_pool_schema": "defect-current-public-reward-pool-v1",
    "future_potions_reward_count": 3,
    "future_potions_public_relic_hooks_fail_closed": True,
    # The exact all-pool live probe peaks at 4.06023 for a Rare Power offer.
    # Keep a narrow guard above that verified range so malformed synthetic
    # rewards still fail closed instead of silently dominating a decision.
    "candidate_adjustment_abs_cap": 4.5,
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
    bridge_root = ROOT / "reference_facts" / "bridge"
    for name, expected in BRIDGE_HASHES.items():
        path = bridge_root / name
        _require(path.is_file(), f"Event outcome bridge evidence missing: {name}")
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        _require(actual == expected, f"Event outcome bridge evidence hash differs: {name}")
        result["bridge/" + name] = {
            "path": str(path.resolve()), "sha256": actual, "bytes": len(raw)
        }
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


def _load_reward_pool() -> tuple[list[dict[str, Any]], dict[str, str]]:
    pool = json.loads(REWARD_POOL_PATH.read_text(encoding="utf-8"))
    localization = json.loads(CARD_LOCALIZATION_PATH.read_text(encoding="utf-8"))
    _require(pool.get("schema_version") == CONTRACT["future_potions_reward_pool_schema"],
             "Future of Potions reward pool schema differs")
    _require(pool.get("engine_sha256") == ENGINE_SHA256,
             "Future of Potions reward pool engine differs")
    _require(pool.get("character") == "Defect" and pool.get("ascension") == 10
             and pool.get("multiplayer_constraint") == "SingleplayerOnly",
             "Future of Potions reward pool scope differs")
    cards = pool.get("cards")
    _require(isinstance(cards, list) and pool.get("count") == len(cards) == 86,
             "Future of Potions reward pool count differs")
    seen = set()
    for card in cards:
        _require(isinstance(card, dict) and isinstance(card.get("id"), str)
                 and card["id"].startswith("CARD.") and card["id"] not in seen,
                 "Future of Potions reward card identity differs")
        seen.add(card["id"])
        _require(card.get("rarity") in {"Basic", "Common", "Uncommon", "Rare", "Ancient"}
                 and card.get("type") in {"Attack", "Skill", "Power"},
                 "Future of Potions reward card class differs")
        _require(card.get("upgrade_preview_status") == "available"
                 and isinstance(card.get("after_upgrade"), dict),
                 "Future of Potions reward card lacks exact upgrade preview")
    _require(isinstance(localization, dict), "Card localization is not an object")
    return cards, localization


REWARD_POOL, CARD_LOCALIZATION = _load_reward_pool()


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


def _stable_option_symbol(value: Any, prefix: str, suffix: str | None = None) -> str | None:
    if not isinstance(value, str) or not value.startswith(prefix):
        return None
    result = value[len(prefix):]
    if suffix is not None:
        if not result.endswith(suffix):
            return None
        result = result[:-len(suffix)]
    return result if result and result == result.upper() else None


def _upgraded_reward_card(card: dict[str, Any], index: int) -> dict[str, Any]:
    result = copy.deepcopy(card)
    after = result.get("after_upgrade")
    _require(isinstance(after, dict), "Reward pool card lacks upgrade preview")
    card_key = result["id"].split(".", 1)[1]
    result.update(
        index=index,
        name=CARD_LOCALIZATION.get(card_key + ".title", card_key),
        description=CARD_LOCALIZATION.get(card_key + ".description", card_key + ".description"),
        upgraded=True,
        current_upgrade_level=1,
        is_upgradable=False,
        upgrade_preview_status="not_upgradable",
        after_upgrade=None,
    )
    if "cost" in after:
        result["cost"] = after["cost"]
    if "stats" in after:
        result["stats"] = copy.deepcopy(after["stats"])
    keywords = set(result.get("keywords") or [])
    keywords.update(after.get("added_keywords") or [])
    keywords.difference_update(after.get("removed_keywords") or [])
    result["keywords"] = sorted(keywords) or None
    return result


def _expected_best_of_three(values: list[float]) -> float:
    _require(len(values) >= CONTRACT["future_potions_reward_count"],
             "Future of Potions filtered pool has fewer than three cards")
    combinations = list(itertools.combinations(values, CONTRACT["future_potions_reward_count"]))
    return sum(max(0.0, *group) for group in combinations) / len(combinations)


def _future_potions_value(
    policy: Any,
    fact: dict[str, Any],
    state: dict[str, Any],
    row: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[float | None, dict[str, Any]]:
    evidence = candidate.get("evidence") or {}
    variables = evidence.get("vars")
    if not isinstance(variables, dict):
        # Historical states from before the bridge fix remain unresolved. Never
        # infer the already-drawn card type from the option index or outcome.
        return None, {"applied": False, "reason": "public_option_variables_missing"}
    potion_id = _stable_option_symbol(variables.get("Potion"), "", ".title")
    rarity_key = _stable_option_symbol(variables.get("Rarity"), "CARD_RARITY.")
    type_key = _stable_option_symbol(variables.get("Type"), "CARD_TYPE.")
    if potion_id is None or rarity_key not in {"COMMON", "UNCOMMON", "RARE"} \
            or type_key not in {"ATTACK", "SKILL", "POWER"}:
        return None, {"applied": False, "reason": "public_option_variables_unrecognized"}

    option_index = (row.get("request") or {}).get("args", {}).get("option_index")
    _require(type(option_index) is int and evidence.get("index") == option_index,
             "Future of Potions option index binding differs")
    potions = (state.get("player") or {}).get("potions")
    _require(isinstance(potions, list), "Future of Potions public potion inventory missing")
    ordered = sorted((p for p in potions if isinstance(p, dict)), key=lambda p: p.get("index", -1))
    _require(option_index < len(ordered), "Future of Potions option lacks matching potion")
    held_id = ordered[option_index].get("id")
    _require(held_id in {potion_id, "POTION." + potion_id},
             "Future of Potions public potion identity differs")

    blockers = set(fact["unsupported_public_relic_modifiers"])
    held_relics = {relic.get("id") for relic in ((state.get("player") or {}).get("relics") or [])
                   if isinstance(relic, dict)}
    active_blockers = sorted(blockers & held_relics)
    if active_blockers:
        return None, {
            "applied": False,
            "reason": "public_card_reward_modifier_present",
            "blocking_relics": active_blockers,
        }

    rarity = rarity_key.title()
    card_type = type_key.title()
    pool = [card for card in REWARD_POOL
            if card["rarity"] == rarity and card["type"] == card_type]
    _require(len(pool) >= fact["reward_count"], "Future of Potions filtered reward pool is too small")
    upgraded = [_upgraded_reward_card(card, index) for index, card in enumerate(pool)]
    values = policy._score_public_future_reward(state, upgraded)
    _require(isinstance(values, dict) and set(values) == {card["id"] for card in upgraded},
             "Future of Potions public reward scoring differs")
    ordered_values = []
    for card in upgraded:
        value = _number(values[card["id"]])
        _require(value is not None, "Future of Potions card value is not finite")
        ordered_values.append(value)
    expected_reward = _expected_best_of_three(ordered_values)
    potion_loss = float(fact["potion_loss_utility_by_target_rarity"][rarity])
    exact_score = expected_reward - potion_loss
    return exact_score, {
        "applied": True,
        "potion_id": potion_id,
        "target_rarity": rarity,
        "target_type": card_type,
        "filtered_pool_size": len(upgraded),
        "reward_count": fact["reward_count"],
        "distinct_uniform_without_replacement": True,
        "all_rewards_upgraded": True,
        "expected_best_card_delta_from_skip": expected_reward,
        "potion_loss_utility": potion_loss,
        "card_values": [
            {"card_id": card["id"], "delta_from_skip": values[card["id"]]}
            for card in upgraded
        ],
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
    elif fact["kind"] == "public_precommitted_random_card_reward":
        exact_score, value_detail = _future_potions_value(
            policy, fact, state, row, candidate
        )
        if exact_score is None:
            return 0.0, {"identity": identity, **value_detail}
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
            if detail["kind"] == "public_precommitted_random_card_reward":
                missing.add("future_potions_card_reward_hook_calibration")
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
