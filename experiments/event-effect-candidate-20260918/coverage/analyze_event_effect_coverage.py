"""Audit event-choice fact coverage in completed, audited natural runs.

This is descriptive analysis.  Natural outcomes are used only to stratify
coverage; they are never treated as causal labels or fitted action values.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any


SCHEMA_VERSION = "event-effect-coverage-v1"
TEXT_KEY = re.compile(
    r"^(?P<event>[A-Z0-9_]+)\.pages\.[^.]+\.options\.(?P<option>[A-Z0-9_]+)$"
)
PLACEHOLDER = re.compile(r"\{([A-Za-z][A-Za-z0-9_]*)(?::[^}]*)?\}")

COMMAND_EFFECTS = {
    "RelicCmd.Obtain": "relic_gain",
    "CreatureCmd.Damage": "hp_loss",
    "CreatureCmd.Heal": "heal",
    "CreatureCmd.GainMaxHp": "max_hp_gain",
    "CreatureCmd.LoseMaxHp": "max_hp_loss",
    "PlayerCmd.GainGold": "gold_gain",
    "PlayerCmd.LoseGold": "gold_loss",
    "PlayerCmd.MimicRestSiteHeal": "heal",
    "CardPileCmd.RemoveFromDeck": "card_remove",
    "CardPileCmd.AddCurseToDeck": "curse_gain",
    "CardPileCmd.AddCursesToDeck": "curse_gain",
    "CardPileCmd.Add": "card_gain",
    "CardCmd.Upgrade": "card_upgrade",
    "CardCmd.Downgrade": "card_downgrade",
    "CardCmd.TransformToRandom": "card_transform",
    "CardCmd.TransformTo": "card_transform",
    "CardCmd.Enchant": "card_enchant",
    "PotionCmd.Discard": "potion_loss",
    "RewardsCmd.OfferCustom": "reward_offer",
}

DESCRIPTION_PATTERNS = (
    ("gold_gain", re.compile(r"\b(?:gain|receive)\b[^.]*\bgold\b", re.I)),
    ("gold_loss", re.compile(r"\b(?:lose|pay|spend)\b[^.]*\bgold\b", re.I)),
    ("heal", re.compile(r"\b(?:heal|recover)\b[^.]*\bhp\b", re.I)),
    ("hp_loss", re.compile(r"\b(?:lose|take)\b[^.]*\b(?:hp|damage)\b", re.I)),
    ("max_hp_gain", re.compile(r"\bgain\b[^.]*\bmax(?:imum)? hp\b", re.I)),
    ("max_hp_loss", re.compile(r"\blose\b[^.]*\bmax(?:imum)? hp\b", re.I)),
    ("card_remove", re.compile(r"\bremove\b[^.]*\bcard", re.I)),
    ("card_upgrade", re.compile(r"\bupgrade\b[^.]*\bcard", re.I)),
    ("card_transform", re.compile(r"\btransform\b[^.]*\bcard", re.I)),
    ("card_enchant", re.compile(r"\benchant(?:ed|ment)?\b", re.I)),
    ("card_gain", re.compile(r"\b(?:add|choose|obtain|receive)\b[^.]*\bcard", re.I)),
    ("curse_gain", re.compile(r"\b(?:gain|receive|add)\b[^.]*\bcurse", re.I)),
    ("relic_gain", re.compile(r"\b(?:gain|obtain|receive|choose)\b[^.]*\brelic", re.I)),
    ("potion_gain", re.compile(r"\b(?:gain|obtain|receive|choose)\b[^.]*\bpotion", re.I)),
    ("relic_exchange", re.compile(r"\btrade\b[^.]*\bfor\b", re.I)),
    ("combat", re.compile(r"\b(?:fight|combats?|enemies|enemy)\b", re.I)),
    ("leave", re.compile(r"\b(?:leave|depart|exit|continue|proceed)\b", re.I)),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def evidence(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def audit_category(audit: dict[str, Any]) -> str:
    goal = audit.get("goal") or {}
    if audit.get("integration_passed") and goal.get("natural_goal_success"):
        return "target_success"
    if (
        audit.get("integration_passed")
        and goal.get("max_act_observed") == 3
        and (goal.get("max_floor_in_max_act") or 0) >= 15
    ):
        return "near_target_failure"
    return "earlier_failure" if audit.get("integration_passed") else "invalid"


def normalized_option_identity(text_key: Any) -> tuple[str, str] | None:
    if not isinstance(text_key, str):
        return None
    match = TEXT_KEY.fullmatch(text_key)
    if not match:
        return None
    option = match.group("option")
    while option.endswith("_LOCKED"):
        option = option[: -len("_LOCKED")]
    return match.group("event"), option


def runtime_effects(description: Any) -> list[str]:
    if not isinstance(description, str):
        return []
    return sorted({name for name, pattern in DESCRIPTION_PATTERNS if pattern.search(description)})


def used_variables(option: dict[str, Any]) -> dict[str, float]:
    description = option.get("description")
    variables = option.get("vars")
    if not isinstance(description, str) or not isinstance(variables, dict):
        return {}
    referenced = set(PLACEHOLDER.findall(description))
    return {
        key: float(value)
        for key, value in variables.items()
        if key in referenced and type(value) in (int, float)
    }


def catalog_index(raw: Any) -> tuple[dict[str, Any], dict[tuple[str, str], dict[str, Any]]]:
    require(isinstance(raw, dict), "Event catalog must be an object")
    events: dict[str, Any] = {}
    options: dict[tuple[str, str], dict[str, Any]] = {}
    for key, event in raw.items():
        require(isinstance(event, dict), "Event catalog row must be an object")
        event_id = str(event.get("id") or key).upper()
        require(event_id not in events, f"Duplicate event id: {event_id}")
        events[event_id] = event
        for option in event.get("options") or []:
            require(isinstance(option, dict) and option.get("option_key"), "Malformed catalog option")
            identity = (event_id, str(option["option_key"]).upper())
            require(identity not in options, f"Duplicate event option: {identity}")
            options[identity] = option
    return events, options


def game_item_index(raw: Any) -> dict[str, list[dict[str, Any]]]:
    require(isinstance(raw, dict), "Game database must be an object")
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for section, item_type in (("cards", "card"), ("relics", "relic"), ("potions", "potion")):
        rows = raw.get(section) or {}
        require(isinstance(rows, dict), f"Game database {section} must be an object")
        for row in rows.values():
            require(isinstance(row, dict) and row.get("id"), f"Malformed game database {section} row")
            result[str(row["id"]).upper()].append({"item_type": item_type, **row})
    return dict(result)


def load_audits(roots: list[Path]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    audits: dict[str, dict[str, Any]] = {}
    sources: list[dict[str, Any]] = []
    for root in roots:
        paths = sorted(root.rglob("*-audit.json")) if root.is_dir() else [root]
        for path in paths:
            audit = read_json(path)
            run_id = (audit.get("job") or {}).get("name") or audit.get("run_id")
            require(run_id, f"Audit lacks run id: {path}")
            if run_id in audits:
                require(audits[run_id] == audit, f"Conflicting duplicate audit: {run_id}")
                continue
            audits[run_id] = audit
            sources.append(evidence(path))
    return audits, sources


def packet_map(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        packet = json.loads(line)
        decision_id = packet.get("decision_id")
        if decision_id and (decision_id not in result or "execution" in packet):
            result[decision_id] = packet
    return result


def policy_map(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        packet = json.loads(line)
        decision_id = packet.get("decision_id")
        require(decision_id and decision_id not in result, f"Duplicate policy decision: {decision_id}")
        result[decision_id] = packet
    return result


def option_facts(
    option: dict[str, Any],
    catalog_options: dict[tuple[str, str], dict[str, Any]],
    game_items: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    identity = normalized_option_identity(option.get("text_key"))
    catalog = catalog_options.get(identity) if identity else None
    commands = sorted(set((catalog or {}).get("raw_commands") or []))
    command_effects = sorted({COMMAND_EFFECTS[command] for command in commands if command in COMMAND_EFFECTS})
    public_text = ". ".join(
        value for value in (option.get("title"), option.get("description")) if isinstance(value, str)
    )
    description_effects = runtime_effects(public_text)
    raw_item_matches = (game_items or {}).get(identity[1], []) if identity else []
    # An exact option/item id collision is not sufficient evidence by itself:
    # ordinary event verbs such as LIFT and SHATTER also happen to be card ids.
    # Ancient relic ids are the actual option identities in the ancient-choice
    # events.  Other item matches require the catalog command that grants them.
    item_matches = [
        row
        for row in raw_item_matches
        if (
            row["item_type"] == "relic" and row.get("rarity") == "Ancient"
        )
        or (row["item_type"] == "relic" and "RelicCmd.Obtain" in commands)
        or (row["item_type"] == "card" and "CardPileCmd.Add" in commands)
    ]
    item_effects = sorted({f"{row['item_type']}_gain" for row in item_matches})
    granted_items = [
        {
            "item_type": row["item_type"],
            "id": row["id"],
            "rarity": row.get("rarity"),
            "numbers": row.get("numbers"),
            "powers": row.get("powers"),
            "hooks": row.get("hooks"),
            "internal_effects": row.get("effects"),
        }
        for row in item_matches
    ]
    return {
        "identity": list(identity) if identity else None,
        "text_key": option.get("text_key"),
        "catalog_mapped": catalog is not None,
        "catalog_handler": (catalog or {}).get("handler"),
        "catalog_commands": commands,
        "unmapped_catalog_commands": sorted(command for command in commands if command not in COMMAND_EFFECTS),
        "command_effects": command_effects,
        "description_effects": description_effects,
        "item_identity_effects": item_effects,
        "granted_items": granted_items,
        "normalized_effects": sorted(set(command_effects) | set(description_effects) | set(item_effects)),
        "used_variables": used_variables(option),
        "is_locked": option.get("is_locked") is True,
    }


def selected_score(policy: dict[str, Any]) -> dict[str, Any]:
    scoring = policy.get("scoring") or {}
    scores = scoring.get("scores") or []
    chosen = [row for row in scores if row.get("candidate_id") == policy.get("candidate_id")]
    require(len(chosen) == 1, "Chosen event candidate missing or duplicated")
    row = chosen[0]
    return {
        "score": row.get("score"),
        "missing": sorted(row.get("missing") or []),
        "all_candidate_scores": [candidate.get("score") for candidate in scores],
    }


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    instances = [option for row in rows for option in row["options"]]
    actionable = [option for option in instances if not option["is_locked"]]
    chosen = [row["options_by_index"][row["chosen_index"]] for row in rows]
    effect_counts = Counter(effect for option in actionable for effect in option["normalized_effects"])
    chosen_effect_counts = Counter(effect for option in chosen for effect in option["normalized_effects"])
    return {
        "decisions": len(rows),
        "option_instances": len(instances),
        "locked_option_instances": len(instances) - len(actionable),
        "actionable_option_instances": len(actionable),
        "catalog_mapped_actionable_option_instances": sum(option["catalog_mapped"] for option in actionable),
        "effect_covered_actionable_option_instances": sum(bool(option["normalized_effects"]) for option in actionable),
        "all_options_catalog_mapped_decisions": sum(
            all(option["catalog_mapped"] for option in row["options"] if not option["is_locked"])
            for row in rows
        ),
        "all_options_effect_covered_decisions": sum(
            all(option["normalized_effects"] for option in row["options"] if not option["is_locked"])
            for row in rows
        ),
        "chosen_effect_covered_decisions": sum(bool(option["normalized_effects"]) for option in chosen),
        "uniform_policy_score_decisions": sum(
            len(set(row["policy"]["all_candidate_scores"])) == 1 for row in rows
        ),
        "missing_event_model_decisions": sum(
            "event_effect_and_probability_model" in row["policy"]["missing"] for row in rows
        ),
        "effect_instance_counts": dict(effect_counts.most_common()),
        "chosen_effect_counts": dict(chosen_effect_counts.most_common()),
    }


def analyze(
    events_path: Path,
    outputs: Path,
    audit_roots: list[Path],
    engine_path: Path | None,
    game_db_path: Path | None = None,
) -> dict[str, Any]:
    catalog_raw = read_json(events_path)
    events, catalog_options = catalog_index(catalog_raw)
    game_items = game_item_index(read_json(game_db_path)) if game_db_path else {}
    audits, audit_sources = load_audits(audit_roots)
    rows: list[dict[str, Any]] = []
    run_sources: list[dict[str, Any]] = []
    completed_runs = 0
    invalid_runs = 0
    missing_output_runs: list[str] = []

    for run_id, audit in sorted(audits.items()):
        category = audit_category(audit)
        if category == "invalid":
            invalid_runs += 1
            continue
        folder = outputs / run_id
        decisions_path = folder / "decisions.jsonl"
        policy_path = folder / "policy.jsonl"
        if not decisions_path.is_file() or not policy_path.is_file():
            missing_output_runs.append(run_id)
            continue
        completed_runs += 1
        states = packet_map(decisions_path)
        policies = policy_map(policy_path)
        run_sources.extend((evidence(decisions_path), evidence(policy_path)))
        for decision_id, state_packet in states.items():
            state = state_packet.get("state") or {}
            if state.get("decision") != "event_choice":
                continue
            require(decision_id in policies, f"Event decision lacks policy row: {decision_id}")
            policy = policies[decision_id]
            require(policy.get("request", {}).get("action") == "choose_option", "Event action mismatch")
            options = state.get("options") or []
            require(options and all(isinstance(option, dict) for option in options), "Event options missing")
            facts = [option_facts(option, catalog_options, game_items) for option in options]
            indices = [option.get("index") for option in options]
            require(all(type(index) is int for index in indices), "Event option index missing")
            require(len(set(indices)) == len(indices), "Duplicate event option index")
            by_index = dict(zip(indices, facts))
            chosen_index = policy.get("request", {}).get("args", {}).get("option_index")
            require(chosen_index in by_index, "Chosen event option index not in state")
            rows.append(
                {
                    "run_id": run_id,
                    "decision_id": decision_id,
                    "category": category,
                    "act": (state.get("context") or {}).get("act"),
                    "floor": (state.get("context") or {}).get("floor"),
                    "event_name": state.get("event_name"),
                    "chosen_index": chosen_index,
                    "option_indices": indices,
                    "options": facts,
                    "options_by_index": by_index,
                    "policy": selected_score(policy),
                }
            )

    registry: dict[str, dict[str, Any]] = {}
    for row in rows:
        for index, option in zip(row["option_indices"], row["options"]):
            key = option.get("text_key") or "<missing>"
            entry = registry.setdefault(
                key,
                {
                    "text_key": option.get("text_key"),
                    "identity": option["identity"],
                    "catalog_mapped": option["catalog_mapped"],
                    "catalog_handler": option["catalog_handler"],
                    "catalog_commands": option["catalog_commands"],
                    "unmapped_catalog_commands": option["unmapped_catalog_commands"],
                    "normalized_effects": option["normalized_effects"],
                    "granted_items": option["granted_items"],
                    "instances": 0,
                    "actionable_instances": 0,
                    "chosen": 0,
                    "categories": Counter(),
                    "used_variable_names": Counter(),
                },
            )
            require(entry["normalized_effects"] == option["normalized_effects"], f"Effect drift: {key}")
            entry["instances"] += 1
            entry["actionable_instances"] += not option["is_locked"]
            entry["chosen"] += index == row["chosen_index"]
            entry["categories"][row["category"]] += 1
            entry["used_variable_names"].update(option["used_variables"])

    registry_rows = []
    for entry in registry.values():
        entry["categories"] = dict(entry["categories"].most_common())
        entry["used_variable_names"] = dict(entry["used_variable_names"].most_common())
        registry_rows.append(entry)
    registry_rows.sort(key=lambda entry: (-entry["instances"], str(entry["text_key"])))

    by_category = {
        category: summarize_rows([row for row in rows if row["category"] == category])
        for category in ("target_success", "near_target_failure", "earlier_failure")
    }
    unresolved = [
        entry for entry in registry_rows
        if entry["actionable_instances"] and not entry["normalized_effects"]
    ]
    unresolved.sort(key=lambda entry: (-entry["actionable_instances"], str(entry["text_key"])))
    result = {
        "schema_version": SCHEMA_VERSION,
        "interpretation": {
            "natural_outcomes_used_for_fitting": False,
            "candidate_selected_or_deployed": False,
            "catalog_commands": "engine-derived structural evidence, not complete outcome semantics",
            "runtime_descriptions": "public option text and referenced variables only",
            "uniform_policy_score": "all candidate scores equal; tie resolution is not effect-aware",
        },
        "sources": {
            "events_catalog": evidence(events_path),
            "game_database": evidence(game_db_path) if game_db_path else None,
            "engine": evidence(engine_path) if engine_path and engine_path.is_file() else None,
            "audits": audit_sources,
            "decision_and_policy_files": run_sources,
        },
        "catalog": {
            "events": len(events),
            "options": len(catalog_options),
            "commands": dict(
                Counter(
                    command
                    for option in catalog_options.values()
                    for command in option.get("raw_commands") or []
                ).most_common()
            ),
        },
        "runs": {
            "audits": len(audits),
            "completed_valid_with_outputs": completed_runs,
            "invalid_excluded": invalid_runs,
            "missing_output_runs": missing_output_runs,
        },
        "all": summarize_rows(rows),
        "by_category": by_category,
        "unique_runtime_options": len(registry_rows),
        "unresolved_unique_options": len(unresolved),
        "unresolved_actionable_option_instances": sum(entry["actionable_instances"] for entry in unresolved),
        "unresolved_options": unresolved,
        "option_registry": registry_rows,
    }
    return result


def report(result: dict[str, Any]) -> str:
    all_rows = result["all"]
    near = result["by_category"]["near_target_failure"]
    lines = [
        "# Event effect coverage audit",
        "",
        "This report measures engine-catalog and public-description coverage. Natural outcomes were not fitted as action values.",
        "",
        f"- Valid audited runs with decision evidence: {result['runs']['completed_valid_with_outputs']}",
        f"- Event decisions: {all_rows['decisions']}",
        f"- Actionable option instances: {all_rows['actionable_option_instances']}",
        f"- Catalog-mapped actionable option instances: {all_rows['catalog_mapped_actionable_option_instances']}",
        f"- Effect-covered actionable option instances: {all_rows['effect_covered_actionable_option_instances']}",
        f"- Uniform policy-score decisions: {all_rows['uniform_policy_score_decisions']}",
        f"- Near-target event decisions: {near['decisions']}",
        f"- Near-target uniform policy-score decisions: {near['uniform_policy_score_decisions']}",
        f"- Unresolved unique options: {result['unresolved_unique_options']}",
        f"- Unresolved actionable option instances: {result['unresolved_actionable_option_instances']}",
        "",
        "## Most frequent unresolved options",
        "",
    ]
    for entry in result["unresolved_options"][:25]:
        lines.append(f"- `{entry['text_key']}`: {entry['actionable_instances']} actionable instances, {entry['chosen']} chosen")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--outputs", type=Path, required=True)
    parser.add_argument("--audits", type=Path, action="append", required=True)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--game-db", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = analyze(args.events, args.outputs, args.audits, args.engine, args.game_db)
    atomic_json(args.output, result)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report(result), encoding="utf-8")
    print(
        json.dumps(
            {
                "runs": result["runs"],
                "event_decisions": result["all"]["decisions"],
                "actionable_option_instances": result["all"]["actionable_option_instances"],
                "effect_covered_actionable_option_instances": result["all"]["effect_covered_actionable_option_instances"],
                "uniform_policy_score_decisions": result["all"]["uniform_policy_score_decisions"],
                "near_target_event_decisions": result["by_category"]["near_target_failure"]["decisions"],
                "unresolved_unique_options": result["unresolved_unique_options"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
