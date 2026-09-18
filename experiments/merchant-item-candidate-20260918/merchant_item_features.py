"""Source-bound merchant relic and potion utility for public shop states."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from decision_data import DataContractError
from initial_policy import card_mechanisms
from reward_mechanism_features import PRIOR as REWARD_PRIOR
from run_metadata import file_evidence


VERSION = "public-source-bound-merchant-items-v1"
ROOT = Path(__file__).resolve().parent
FACTS_PATH = ROOT / "merchant_item_facts.json"
REFERENCE_ROOT = ROOT / "reference_facts"
DATABASE_PATH = REFERENCE_ROOT / "sts2_db.json"
RELIC_LOCALIZATION_PATH = REFERENCE_ROOT / "relics.json"
POTION_LOCALIZATION_PATH = REFERENCE_ROOT / "potions.json"

# These are fixed before replay. They reuse the parent's documented one-combat
# effect scales. A relic receives a conservative two-combat reuse factor.
PRIOR = {
    "persistent_relic_combat_uses": 2.0,
    "sustained_focus_per_orb_source": 0.32,
    "orb_slot_per_slot": REWARD_PRIOR["orb_slots"],
    "orb_capacity_per_orb_source": 0.12,
    "heal_hp": 0.10,
    "max_hp": 0.06,
    "energy": 0.50,
    "draw": 0.60,
    "temporary_focus_per_orb_source": 0.13,
    "block": 0.15,
    "block_at_full_deficit": 0.08,
    "damage": 0.18,
    "weak": REWARD_PRIOR["weak_amount"],
    "vulnerable": REWARD_PRIOR["vulnerable_amount"],
    "generated_attack_choice": 0.72,
    "generated_skill_choice": 0.72,
    "generated_power_choice": 0.64,
    "generated_colorless_choice": 0.55,
}

CONTRACT = {
    "version": VERSION,
    "public_state_only": True,
    "current_engine_source_bound": True,
    "natural_outcomes_used_for_parameter_selection": False,
    "policy_weights_fitted": False,
    "purchase_keeps_parent_gold_opportunity_cost": True,
    "discard_compares_affordable_visible_shop_potions": True,
    "unknown_items_keep_parent_score": True,
    "candidate_adjustment_abs_cap": 4.5,
    "prior": PRIOR,
}

RICH_TEXT_TAG = re.compile(
    r"\[/?(?:blue|gold|red|purple|green|shake)\]", re.IGNORECASE
)
ANY_SQUARE_TAG = re.compile(r"\[[^\]]+\]")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DataContractError(message)


def _number(value: Any) -> float | None:
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


FACTS = _read(FACTS_PATH)
DATABASE = _read(DATABASE_PATH)
RELIC_LOCALIZATION = _read(RELIC_LOCALIZATION_PATH)
POTION_LOCALIZATION = _read(POTION_LOCALIZATION_PATH)


def _plain(value: str) -> str:
    require(isinstance(value, str) and value, "Localization description is missing")
    result = RICH_TEXT_TAG.sub("", value)
    require(ANY_SQUARE_TAG.search(result) is None, "Unknown localization markup remains")
    return result


def _reference_record(table: str, item_id: str) -> dict[str, Any]:
    bare = item_id.split(".", 1)[1]
    matches = [row for row in DATABASE[table].values()
               if isinstance(row, dict) and row.get("id") == bare]
    require(len(matches) == 1, f"Engine item fact differs: {item_id}")
    return matches[0]


def _validate_facts() -> None:
    require(FACTS.get("schema_version") == VERSION, "Merchant item fact schema differs")
    require(FACTS.get("contract") == CONTRACT, "Merchant item fixed prior differs")
    expected_sources = {
        "sts2_db.json": file_evidence(DATABASE_PATH),
        "relics.json": file_evidence(RELIC_LOCALIZATION_PATH),
        "potions.json": file_evidence(POTION_LOCALIZATION_PATH),
    }
    require(FACTS.get("sources") == expected_sources, "Merchant item sources differ")
    for item_id, fact in FACTS.get("items", {}).items():
        prefix = item_id.split(".", 1)[0]
        table = "relics" if prefix == "RELIC" else "potions"
        require(prefix in ("RELIC", "POTION") and isinstance(fact, dict),
                "Merchant item identity differs")
        require(fact.get("engine") == _reference_record(table, item_id),
                f"Frozen engine item differs: {item_id}")


_validate_facts()


def source_evidence() -> dict[str, dict[str, Any]]:
    return {
        "merchant_item_facts.json": file_evidence(FACTS_PATH),
        "reference_facts/sts2_db.json": file_evidence(DATABASE_PATH),
        "reference_facts/relics.json": file_evidence(RELIC_LOCALIZATION_PATH),
        "reference_facts/potions.json": file_evidence(POTION_LOCALIZATION_PATH),
    }


def _description(item_id: str) -> str:
    prefix, bare = item_id.split(".", 1)
    table = RELIC_LOCALIZATION if prefix == "RELIC" else POTION_LOCALIZATION
    value = table.get(bare + ".description")
    return _plain(value)


def _validate_evidence(evidence: dict[str, Any], item_id: str) -> None:
    require(evidence.get("id") == item_id, "Merchant item candidate identity differs")
    require(evidence.get("description") == _description(item_id),
            f"Current item description differs: {item_id}")


def _deck_context(state: dict[str, Any]) -> dict[str, Any]:
    deck = (state.get("player") or {}).get("deck")
    require(isinstance(deck, list) and deck, "Merchant utility requires public deck")
    tags = [card_mechanisms(card) for card in deck]
    orb_sources = sum(bool(row & {
        "lightning_source", "frost_source", "dark_source",
        "random_orb_source", "plasma_source",
    }) for row in tags)
    return {"deck_size": len(deck), "orb_sources": orb_sources}


def _health_context(state: dict[str, Any]) -> tuple[float, float, float]:
    player = state.get("player") or {}
    hp, maximum = _number(player.get("hp")), _number(player.get("max_hp"))
    require(hp is not None and maximum is not None and maximum > 0 and 0 <= hp <= maximum,
            "Merchant utility requires public HP")
    return hp, maximum, max(0.0, 1.0 - hp / maximum)


def item_utility(state: dict[str, Any], item_id: str) -> tuple[float | None, dict[str, Any]]:
    fact = FACTS["items"].get(item_id)
    if fact is None:
        return None, {"covered": False, "item_id": item_id}
    hp, maximum, deficit = _health_context(state)
    deck = _deck_context(state)
    engine = fact["engine"]
    kind = fact["utility_kind"]
    detail: dict[str, Any] = {
        "covered": True,
        "item_id": item_id,
        "utility_kind": kind,
        "orb_sources": deck["orb_sources"],
        "deck_size": deck["deck_size"],
    }
    if kind == "data_disk":
        focus = float(engine["powers"]["FOCUS"])
        per_combat = PRIOR["sustained_focus_per_orb_source"] * focus * min(3, deck["orb_sources"])
        value = PRIOR["persistent_relic_combat_uses"] * per_combat
        detail.update(focus=focus, per_combat=per_combat)
    elif kind == "runic_capacitor":
        slots = float(engine["numbers"]["repeat"])
        per_combat = (PRIOR["orb_slot_per_slot"] * slots
                      + PRIOR["orb_capacity_per_orb_source"] * min(4, deck["orb_sources"]))
        value = PRIOR["persistent_relic_combat_uses"] * per_combat
        detail.update(slots=slots, per_combat=per_combat)
    elif kind == "lees_waffle":
        max_hp = float(engine["numbers"]["max_hp"])
        hp_gain = maximum + max_hp - hp
        value = min(3.5, PRIOR["heal_hp"] * hp_gain + PRIOR["max_hp"] * max_hp)
        detail.update(hp_gain=hp_gain, max_hp_gain=max_hp)
    elif kind == "energy":
        amount = float(engine["numbers"]["energy"])
        value = PRIOR["energy"] * amount
        detail["amount"] = amount
    elif kind == "draw":
        amount = float(engine["numbers"]["cards"])
        value = PRIOR["draw"] * amount
        detail["amount"] = amount
    elif kind == "temporary_focus":
        amount = float(engine["powers"]["FOCUS"])
        value = PRIOR["temporary_focus_per_orb_source"] * amount * min(3, deck["orb_sources"])
        detail["amount"] = amount
    elif kind == "block":
        amount = float(engine["numbers"]["block"])
        value = (PRIOR["block"] + PRIOR["block_at_full_deficit"] * deficit) * amount
        detail.update(amount=amount, health_deficit=deficit)
    elif kind == "damage":
        amount = float(engine["numbers"]["damage"])
        value = PRIOR["damage"] * amount
        detail["amount"] = amount
    elif kind == "weak":
        amount = float(engine["powers"]["WEAK"])
        value = PRIOR["weak"] * amount
        detail["amount"] = amount
    elif kind == "vulnerable":
        amount = float(engine["powers"]["VULNERABLE"])
        value = PRIOR["vulnerable"] * amount
        detail["amount"] = amount
    elif kind == "generated_attack_choice":
        value = PRIOR["generated_attack_choice"]
    elif kind == "generated_skill_choice":
        value = PRIOR["generated_skill_choice"]
    elif kind == "generated_power_choice":
        value = PRIOR["generated_power_choice"]
    elif kind == "generated_colorless_choice":
        value = PRIOR["generated_colorless_choice"]
    else:
        raise DataContractError(f"Unsupported merchant item utility: {kind}")
    require(math.isfinite(value) and 0 <= value <= 3.6,
            "Merchant item utility is outside the fixed bound")
    detail["utility"] = value
    detail["hp"] = hp
    detail["max_hp"] = maximum
    return value, detail


def _affordable_visible_replacement(state: dict[str, Any]) -> tuple[float, dict[str, Any] | None]:
    player = state.get("player") or {}
    gold = _number(player.get("gold"))
    require(gold is not None and gold >= 0, "Potion replacement requires public gold")
    best_net, best = 0.0, None
    potions = state.get("potions") or []
    require(isinstance(potions, list), "Public shop potion stock differs")
    for item in potions:
        if not isinstance(item, dict) or item.get("is_stocked") is not True:
            continue
        cost = _number(item.get("cost"))
        if cost is None or cost < 0 or cost > gold:
            continue
        item_id = item.get("id")
        utility, detail = item_utility(state, item_id)
        if utility is None:
            continue
        _validate_evidence(item, item_id)
        net = utility - 0.25 - cost / 150.0
        if net > best_net:
            best_net = net
            best = {"item_id": item_id, "cost": cost, "net": net, "detail": detail}
    return best_net, best


def candidate_adjustment(state: dict[str, Any], row: dict[str, Any],
                         candidate: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    request = row.get("request") or {}
    action = request.get("action")
    if state.get("decision") != "shop" or action not in {
        "buy_relic", "buy_potion", "discard_potion"
    }:
        return 0.0, {"applied": False, "reason": "not_merchant_item"}
    require(request == candidate.get("request"), "Merchant score row/candidate binding differs")
    evidence = candidate.get("evidence") or {}
    item_id = evidence.get("id")
    utility, detail = item_utility(state, item_id)
    if utility is None:
        return 0.0, {"applied": False, "reason": "unsupported_item", "item_id": item_id}
    _validate_evidence(evidence, item_id)
    before = _number(row.get("score"))
    require(before is not None, "Merchant parent score is not finite")
    if action in {"buy_relic", "buy_potion"}:
        cost = _number(evidence.get("cost"))
        require(cost is not None and cost >= 0 and evidence.get("can_purchase") is True,
                "Covered purchase must be publicly purchasable")
        exact_score = before + utility
        detail.update(cost=cost, parent_gold_score=before)
    else:
        replacement_net, replacement = _affordable_visible_replacement(state)
        exact_score = replacement_net - utility
        detail.update(replacement_net=replacement_net, replacement=replacement)
    adjustment = exact_score - before
    require(abs(adjustment) <= CONTRACT["candidate_adjustment_abs_cap"] + 1e-12,
            "Merchant item adjustment exceeds fixed cap")
    return adjustment, {
        "applied": True,
        "action": action,
        "item_id": item_id,
        "parent_score": before,
        "exact_score": exact_score,
        "value_detail": detail,
        "natural_outcomes_used": False,
        "hidden_runtime_state_used": False,
    }


def adjust(state: dict[str, Any], packet: dict[str, Any],
           candidates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result = copy.deepcopy(packet)
    applied = 0
    for row in result.get("scores") or []:
        candidate = candidates.get(row.get("candidate_id"))
        require(candidate is not None, "Merchant item candidate missing")
        adjustment, detail = candidate_adjustment(state, row, candidate)
        row["merchant_item_adjustment"] = adjustment
        row["merchant_item_detail"] = detail
        row["score"] += adjustment
        if detail.get("applied"):
            applied += 1
            missing = set(row.get("missing") or [])
            missing.discard("item_effect_model")
            missing.discard("potion_replacement_utility")
            missing.add("merchant_item_value_calibration")
            if detail["value_detail"]["utility_kind"].startswith("generated_"):
                missing.add("generated_card_distribution_utility")
            row["missing"] = sorted(missing)
            row.setdefault("reasons", []).append({
                "source": VERSION,
                "score": adjustment,
                "explanation": "Current-engine item effect with fixed public-state utility",
            })
    skip = next((row["score"] for row in result.get("scores") or [] if row.get("is_skip")), None)
    for row in result.get("scores") or []:
        row["delta_from_skip"] = None if skip is None else row["score"] - skip
    result["merchant_item_contract"] = copy.deepcopy(CONTRACT)
    result["merchant_item_applied_rows"] = applied
    return result
