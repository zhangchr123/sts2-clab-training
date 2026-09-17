"""Current-engine reward semantics bound to the frozen English card table.

The registry records only effects stated by the current exported description.
It does not claim probabilities for future combat conditions or hidden hooks.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from decision_data import DataContractError
from mechanism_facts import ENGINE_SHA256, _file_hash
from run_metadata import file_evidence


VERSION = "current-reward-description-semantics-v1"
ROOT = Path(__file__).resolve().parent
CATALOG_PATH = ROOT / "current_cards_eng.json"
CATALOG_SHA256 = "c469a0be87d57c1476b75a5d0d3031cebf47e65d380a4646aae0028a20c993c0"
DEFAULT_ENGINE = ROOT.parent / "sts2-cli" / "lib" / "sts2.dll"


def _fact(stats=(), **effects):
    return {"covered_stats": tuple(stats), "effects": effects}


FACTS = {
    "LIGHTNING_ROD": _fact(("block", "lightningrodpower"), delayed_lightning="lightningrodpower"),
    "BARRAGE": _fact(("damage", "calculatedhits", "calculationbase", "calculationextra"),
                     orb_scaled_attack=True),
    "BEAM_CELL": _fact(("damage", "vulnerablepower"), vulnerable="vulnerablepower"),
    "LEAP": _fact(("block",), plain_current_stats=True),
    "CLAW": _fact(("damage", "increase"), claw_increase="increase"),
    "GO_FOR_THE_EYES": _fact(("damage", "weakpower"), conditional_weak="weakpower"),
    "SWEEPING_BEAM": _fact(("damage", "cards"), draw="cards", aoe=True),
    "CHARGE_BATTERY": _fact(("block", "energy"), next_energy="energy"),
    "MOMENTUM_STRIKE": _fact(("damage",), self_cost_reduction=True),
    "UPROAR": _fact(("damage",), fixed_hits=2, random_attack_from_draw=True),
    "BOOST_AWAY": _fact(("block",), generated_status_count=1),
    "COMPILE_DRIVER": _fact(("damage", "calculatedcards", "calculationbase", "calculationextra"),
                            unique_orb_draw=True),
    "WHITE_NOISE": _fact((), random_zero_cost_power=True),
    "ITERATION": _fact(("iterationpower",), status_draw="iterationpower"),
    "CHILL": _fact((), frost_per_enemy=True),
    "SCAVENGE": _fact(("energy",), exhaust_control=True, next_energy="energy"),
    "BULK_UP": _fact(("strengthpower", "dexteritypower", "orbslots"),
                     strength="strengthpower", dexterity="dexteritypower",
                     lose_orb_slots="orbslots"),
    "FTL": _fact(("damage", "cards", "playmax"), conditional_draw="cards"),
    "THUNDER": _fact(("thunderpower",), lightning_evoke_damage="thunderpower"),
    "NULL": _fact(("damage", "weakpower"), weak="weakpower", dark=1),
    "FIGHT_THROUGH": _fact(("block",), generated_status_count=2),
    "SYNTHESIS": _fact(("damage",), next_power_free=True),
    "CAPACITOR": _fact(("repeat",), orb_slots="repeat"),
    "STORM": _fact(("stormpower",), power_lightning="stormpower"),
    "SMOKESTACK": _fact(("smokestackpower",), status_aoe="smokestackpower"),
    "FERAL": _fact(("feralpower",), zero_cost_attack_return="feralpower"),
    "LOOP": _fact(("loop",), orb_passive_repeat="loop"),
    "MODDED": _fact(("cards", "repeat"), draw="cards", orb_slots="repeat",
                    increasing_cost=True),
    "ROCKET_PUNCH": _fact(("damage", "cards"), draw="cards",
                          status_cost_reduction=True),
    "VOLTAIC": _fact(("calculatedchannels", "calculationbase", "calculationextra"),
                     lightning_history_scaling=True),
    "DOUBLE_ENERGY": _fact((), energy_multiplier=True),
    "FUSION": _fact((), plasma=1),
    "REBOOT": _fact(("cards",), draw="cards", full_shuffle=True),
    "DARKNESS": _fact((), dark=1),
    "BALL_LIGHTNING": _fact(("damage",), lightning=1),
    "COLD_SNAP": _fact(("damage",), frost=1),
    "COOLHEADED": _fact(("cards",), draw="cards", frost=1),
    "GLACIER": _fact(("block",), frost=2),
    "OVERCLOCK": _fact(("cards",), draw="cards", generated_status_count=1),
    "SKIM": _fact(("cards",), draw="cards"),
    "TURBO": _fact(("energy",), immediate_energy="energy", generated_status_count=1),
    "HOLOGRAM": _fact(("block",), discard_retrieval=True),
    "DEFRAGMENT": _fact(("focuspower",), sustained_focus="focuspower"),
}

REMAINING_MISSING = {
    "LIGHTNING_ROD": ("future_combat_duration",),
    "BARRAGE": ("future_channeled_orb_count",),
    "CLAW": ("future_claw_play_count",),
    "GO_FOR_THE_EYES": ("future_enemy_intent",),
    "MOMENTUM_STRIKE": ("self_cost_reduction_timing",),
    "UPROAR": ("future_draw_pile_attack_distribution",),
    "COMPILE_DRIVER": ("future_unique_orb_count",),
    "WHITE_NOISE": ("random_power_distribution",),
    "ITERATION": ("future_status_draw_count",),
    "CHILL": ("future_enemy_count",),
    "FTL": ("future_cards_played_before_ftl",),
    "THUNDER": ("future_lightning_evoke_count_and_targets",),
    "STORM": ("future_power_play_count",),
    "SMOKESTACK": ("future_status_creation_count_and_targets",),
    "FERAL": ("future_zero_cost_attack_play_count",),
    "LOOP": ("future_rightmost_orb_distribution",),
    "ROCKET_PUNCH": ("future_status_creation_count",),
    "VOLTAIC": ("future_lightning_channel_history",),
    "DOUBLE_ENERGY": ("future_energy_when_played",),
}


def normalize_description(value):
    if not isinstance(value, str):
        return value
    return re.sub(r"\[/?[A-Za-z0-9_]+\]", "", value)


def _load_catalog():
    raw = CATALOG_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CATALOG_SHA256:
        raise DataContractError("Current English card table differs")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise DataContractError("Current English card table schema differs")
    return value


CATALOG = _load_catalog()
for _cid, _fact_value in FACTS.items():
    if _cid + ".description" not in CATALOG:
        raise DataContractError("Reward fact has no current description: " + _cid)
    if set(_fact_value) != {"covered_stats", "effects"}:
        raise DataContractError("Reward fact schema differs: " + _cid)


CONTRACT = {
    "version": VERSION,
    "engine_sha256": ENGINE_SHA256,
    "card_table_sha256": CATALOG_SHA256,
    "facts": len(FACTS),
    "source": "current exported English description templates plus explicit conservative semantics",
    "hidden_runtime_state_used": False,
    "future_condition_probabilities_claimed": False,
}


def expected_description(cid):
    return normalize_description(CATALOG[cid + ".description"])


def validate_card(card):
    cid = str(card.get("id", "")).split(".")[-1].upper()
    fact = FACTS.get(cid)
    if fact is None:
        return None
    if normalize_description(card.get("description")) != expected_description(cid):
        raise DataContractError("Current reward description differs: " + cid)
    stats = card.get("stats")
    keys = tuple(sorted(str(key).lower() for key in stats)) if isinstance(stats, dict) else ()
    if keys != tuple(sorted(fact["covered_stats"])):
        raise DataContractError("Current reward stat schema differs: " + cid)
    return fact


def verified_source(engine_path=DEFAULT_ENGINE):
    path = Path(engine_path).resolve()
    try:
        stat = path.stat()
        engine_hash = _file_hash(str(path), stat.st_size, stat.st_mtime_ns)
    except OSError as exc:
        raise DataContractError("Reward facts require the verified engine DLL") from exc
    if engine_hash != ENGINE_SHA256:
        raise DataContractError("Reward facts engine SHA differs")
    return {
        **CONTRACT,
        "catalog": file_evidence(CATALOG_PATH),
        "registry_sha256": hashlib.sha256(json.dumps(
            {"facts": FACTS, "remaining_missing": REMAINING_MISSING},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode()).hexdigest(),
    }
