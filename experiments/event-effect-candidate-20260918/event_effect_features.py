"""Public, source-bound event effect features for Defect A10 policy scoring.

Only the current option's exported title, description, variables and exact
engine-derived catalog facts are used.  No natural outcome labels, hidden
rewards, or future states enter these features.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any
import copy

from decision_data import DataContractError


ROOT = Path(__file__).resolve().parent
CATALOG_PATH = ROOT / "event_effect_catalog.json"
CATALOG_SHA256 = "e07aa9f039196b9cb4ba1fa6e45d010e2da4c2be9d796503704d2e7354ad6549"
ENGINE_SHA256 = "14b57dbaee1b58cb919625a662831054fd714b3b75b13b7449eac0e95b98a3e4"
CATALOG_SCHEMA = "event-effect-engine-catalog-v1"
TEXT_KEY = re.compile(
    r"^(?P<event>[A-Z0-9_]+)\.pages\.[^.]+\.options\.(?P<option>[A-Z0-9_]+)$"
)
PLACEHOLDER = re.compile(r"\{([A-Za-z][A-Za-z0-9_]*)(?::[^}]*)?\}")
OPTION_FIELDS = {"description", "index", "is_locked", "text_key", "title", "vars"}

PARAMETERS = (
    "event_heal_missing_fraction",
    "event_heal_unknown_amount",
    "event_max_hp_gain_fraction",
    "event_max_hp_loss_fraction",
    "event_card_remove",
    "event_card_upgrade",
    "event_card_transform",
    "event_card_enchant",
    "event_card_offer",
    "event_curse_gain",
    "event_relic_gain",
    "event_potion_gain",
    "event_potion_loss",
    "event_immediate_combat_health_deficit",
    "event_reward_offer",
    "ancient_relic_energy_each_turn",
    "ancient_relic_delayed_energy",
    "ancient_relic_draw_each_turn",
    "ancient_relic_strength_each_turn",
    "event_effect_unknown",
)

PRIOR = dict.fromkeys(PARAMETERS, 0.0)
PRIOR.update(
    event_heal_missing_fraction=3.0,
    event_heal_unknown_amount=0.20,
    event_max_hp_gain_fraction=2.0,
    event_max_hp_loss_fraction=-2.0,
    event_card_remove=0.70,
    event_card_upgrade=0.50,
    event_card_transform=0.30,
    event_card_enchant=0.45,
    event_card_offer=0.30,
    event_curse_gain=-1.20,
    event_relic_gain=0.60,
    event_potion_gain=0.25,
    event_potion_loss=-0.25,
    event_immediate_combat_health_deficit=-1.10,
    event_reward_offer=0.40,
    ancient_relic_energy_each_turn=0.80,
    ancient_relic_delayed_energy=0.45,
    ancient_relic_draw_each_turn=0.40,
    ancient_relic_strength_each_turn=0.20,
)

CONTRACT = {
    "version": "public-event-effects-v1",
    "catalog_sha256": CATALOG_SHA256,
    "engine_sha256": ENGINE_SHA256,
    "natural_outcomes_used": False,
    "hidden_reward_or_future_state_used": False,
    "gold_and_hp_cost_rescored": False,
    "score_semantics": "fixed_expert_relative_utility_not_win_probability",
    "unknown_effect_score": 0.0,
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DataContractError(message)


def _load_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    raw = path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == CATALOG_SHA256, "Event effect catalog hash differs")
    catalog = json.loads(raw.decode("utf-8"))
    _require(catalog.get("schema_version") == CATALOG_SCHEMA, "Event effect catalog schema differs")
    _require(
        catalog.get("sources", {}).get("engine", {}).get("sha256") == ENGINE_SHA256,
        "Event effect catalog engine differs",
    )
    _require(catalog.get("semantics", {}).get("natural_outcomes_used") is False, "Event catalog outcome scope differs")
    return catalog


CATALOG = _load_catalog()


def option_identity(text_key: Any) -> tuple[str, str] | None:
    if not isinstance(text_key, str):
        return None
    match = TEXT_KEY.fullmatch(text_key)
    if not match:
        return None
    option = match.group("option")
    while option.endswith("_LOCKED"):
        option = option[: -len("_LOCKED")]
    return match.group("event"), option


def _finite_positive(value: Any) -> float | None:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        return None
    return float(value)


def _public_variables(option: dict[str, Any], text: str) -> dict[str, float]:
    raw = option.get("vars")
    if raw is None:
        return {}
    _require(isinstance(raw, dict), "Event option variables must be an object or null")
    referenced = set(PLACEHOLDER.findall(text))
    result = {}
    for name in referenced:
        if name not in raw:
            continue
        value = _finite_positive(raw[name])
        if value is not None:
            result[name] = value
    return result


def _amount(variables: dict[str, float], names: tuple[str, ...]) -> float | None:
    values = [variables[name] for name in names if name in variables]
    return max(values) if values else None


def features(state: dict[str, Any], row: dict[str, Any], candidate: dict[str, Any]) -> tuple[dict[str, float], dict[str, Any]]:
    values = dict.fromkeys(PARAMETERS, 0.0)
    if state.get("decision") != "event_choice" or row.get("request", {}).get("action") != "choose_option":
        return values, {"applied": False, "reason": "not_event_choice"}
    _require(row["request"] == candidate.get("request"), "Event effect row/candidate binding differs")
    option = candidate.get("evidence")
    _require(isinstance(option, dict), "Event candidate evidence missing")
    _require(set(option) <= OPTION_FIELDS, "Event option exposes fields outside the public contract")
    _require(option.get("is_locked") is False, "Locked event option cannot be scored")
    identity = option_identity(option.get("text_key"))
    title = option.get("title") if isinstance(option.get("title"), str) else ""
    description = option.get("description") if isinstance(option.get("description"), str) else ""
    text = (title + ". " + description).strip()
    lower = text.lower()
    variables = _public_variables(option, text)
    event_fact = CATALOG["event_options"].get(f"{identity[0]}:{identity[1]}") if identity else None
    commands = set((event_fact or {}).get("raw_commands") or [])
    handler = str((event_fact or {}).get("handler") or "")
    ancient = CATALOG["ancient_relics"].get(identity[1]) if identity else None

    heal_signal = "CreatureCmd.Heal" in commands or "MimicRestSiteHeal" in " ".join(commands) or bool(re.search(r"\b(?:heal|recover)\b[^.]*\bhp\b", text, re.I))
    heal = _amount(variables, ("Heal", "HpHeal", "Healing"))
    player = state.get("player") or {}
    hp = _finite_positive(player.get("hp"))
    maximum = _finite_positive(player.get("max_hp"))
    _require(hp is not None and hp > 0 and maximum is not None and maximum > 0, "Event scoring requires positive public HP")
    missing_hp = max(0.0, maximum - hp)
    if heal_signal:
        if heal is None:
            values["event_heal_unknown_amount"] = 1.0
        else:
            values["event_heal_missing_fraction"] = min(heal, missing_hp) / maximum

    max_hp = _amount(variables, ("MaxHp", "MaxHP", "MaxHealth"))
    max_gain = "CreatureCmd.GainMaxHp" in commands or bool(re.search(r"\b(?:gain|raise|increase)\b[^.]*\bmax(?:imum)? hp\b", text, re.I))
    max_loss = "CreatureCmd.LoseMaxHp" in commands or bool(re.search(r"\b(?:lose|lower|decrease)\b[^.]*\bmax(?:imum)? hp\b", text, re.I))
    if max_hp is not None and max_gain:
        values["event_max_hp_gain_fraction"] = min(1.0, max_hp / maximum)
    if max_hp is not None and max_loss:
        values["event_max_hp_loss_fraction"] = min(1.0, max_hp / maximum)

    values["event_card_remove"] = float("CardPileCmd.RemoveFromDeck" in commands or bool(re.search(r"\bremove\b[^.]*\bcard", text, re.I)))
    values["event_card_upgrade"] = float("CardCmd.Upgrade" in commands or bool(re.search(r"\bupgrade\b", text, re.I)))
    values["event_card_transform"] = float(any(command.startswith("CardCmd.Transform") for command in commands) or bool(re.search(r"\btransform\b", text, re.I)))
    values["event_card_enchant"] = float("CardCmd.Enchant" in commands or bool(re.search(r"\benchant(?:ed|ment)?\b", text, re.I)))
    values["event_card_offer"] = float("RewardsCmd.OfferCustom" in commands or bool(re.search(r"\b(?:choose|see|receive|obtain|add)\b[^.]*\bcards?\b", text, re.I)))
    values["event_curse_gain"] = float(any("Curse" in command for command in commands) or bool(re.search(r"\b(?:gain|receive|add)\b[^.]*\b(?:curse|guilty)\b", text, re.I)))
    values["event_relic_gain"] = float("RelicCmd.Obtain" in commands or ancient is not None)
    values["event_potion_gain"] = float(bool(re.search(r"\b(?:gain|obtain|receive|choose)\b[^.]*\bpotion", text, re.I)))
    values["event_potion_loss"] = float("PotionCmd.Discard" in commands or bool(re.search(r"\b(?:lose|discard|insert)\b[^.]*\bpotion", text, re.I)))
    values["event_reward_offer"] = float("RewardsCmd.OfferCustom" in commands)

    immediate_combat = handler.lower() == "fight" or bool(re.fullmatch(r"\s*fight!?\s*", title, re.I)) or bool(re.search(r"(?:^|\.)\s*fight\b", description, re.I))
    values["event_immediate_combat_health_deficit"] = float(immediate_combat) * max(0.0, 1.0 - hp / maximum)

    if ancient is not None:
        numbers = ancient.get("numbers") or {}
        powers = ancient.get("powers") or {}
        energy = _finite_positive(numbers.get("energy"))
        cards = _finite_positive(numbers.get("cards"))
        strength = _finite_positive(powers.get("STRENGTH"))
        start_turn = bool(re.search(r"\bstart of (?:each|your) turn\b", lower))
        delayed_turn = "3rd turn" in lower and "every turn after" in lower
        if energy is not None and start_turn:
            values["ancient_relic_energy_each_turn"] = min(3.0, energy)
        elif energy is not None and delayed_turn:
            values["ancient_relic_delayed_energy"] = min(3.0, energy)
        if cards is not None and start_turn and "draw" in lower:
            values["ancient_relic_draw_each_turn"] = min(5.0, cards)
        if strength is not None and start_turn and "strength" in lower:
            values["ancient_relic_strength_each_turn"] = min(5.0, strength)

    modeled = any(value > 0 for name, value in values.items() if name != "event_effect_unknown")
    values["event_effect_unknown"] = float(not modeled)
    detail = {
        "applied": True,
        "text_key": option.get("text_key"),
        "identity": list(identity) if identity else None,
        "catalog_handler": handler or None,
        "catalog_commands": sorted(commands),
        "ancient_relic": identity[1] if ancient is not None and identity else None,
        "referenced_public_variables": variables,
        "features": {name: value for name, value in values.items() if value},
        "natural_outcomes_used": False,
        "hidden_reward_or_future_state_used": False,
    }
    return values, detail


def score(values: dict[str, float], weights: dict[str, float] = PRIOR) -> float:
    _require(set(values) == set(PARAMETERS), "Event feature schema differs")
    _require(set(weights) == set(PARAMETERS), "Event weight schema differs")
    _require(
        all(type(value) in (int, float) and math.isfinite(value) for value in values.values()),
        "Event features must be finite",
    )
    _require(
        all(type(value) in (int, float) and math.isfinite(value) and abs(value) <= 4 for value in weights.values()),
        "Event weights must be finite and bounded",
    )
    return sum(float(weights[name]) * values[name] for name in PARAMETERS)


def adjust(
    state: dict[str, Any],
    packet: dict[str, Any],
    candidates: dict[str, dict[str, Any]],
    weights: dict[str, float] = PRIOR,
) -> dict[str, Any]:
    if state.get("decision") != "event_choice":
        return packet
    result = copy.deepcopy(packet)
    for row in result.get("scores") or []:
        candidate = candidates.get(row.get("candidate_id"))
        _require(candidate is not None, "Event effect candidate missing")
        values, detail = features(state, row, candidate)
        adjustment = score(values, weights)
        before = row.get("score")
        _require(type(before) in (int, float) and math.isfinite(before), "Event score must be finite")
        row["score"] = before + adjustment
        row["event_effect_features"] = values
        row["event_effect_detail"] = detail
        row["event_effect_adjustment"] = adjustment
        row.setdefault("reasons", []).append(
            {
                "source": CONTRACT["version"],
                "score": adjustment,
                "explanation": "Fixed public event-effect expert prior; no outcome probability or hidden reward",
            }
        )
        if detail.get("applied"):
            missing = set(row.get("missing") or [])
            missing.discard("event_effect_and_probability_model")
            missing.add("event_outcome_probability_model")
            if values["event_effect_unknown"]:
                missing.add("unmodeled_event_effect")
            row["missing"] = sorted(missing)
    skip = next((row["score"] for row in result["scores"] if row.get("is_skip")), None)
    for row in result["scores"]:
        row["delta_from_skip"] = None if skip is None else row["score"] - skip
    result["event_effect_contract"] = copy.deepcopy(CONTRACT)
    return result
