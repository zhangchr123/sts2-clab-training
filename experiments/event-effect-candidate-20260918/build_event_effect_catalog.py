"""Build a compact, source-bound event fact catalog from engine extractions."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "event-effect-engine-catalog-v1"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def evidence(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {"name": path.name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build(events_path: Path, game_db_path: Path, engine_path: Path) -> dict[str, Any]:
    events_raw = read(events_path)
    game = read(game_db_path)
    require(isinstance(events_raw, dict), "events catalog must be an object")
    require(isinstance(game, dict), "game database must be an object")
    event_options: dict[str, Any] = {}
    event_rows: dict[str, Any] = {}
    for key, event in events_raw.items():
        require(isinstance(event, dict), f"malformed event row: {key}")
        event_id = str(event.get("id") or key).upper()
        require(event_id not in event_rows, f"duplicate event: {event_id}")
        event_rows[event_id] = {
            "class": event.get("class"),
            "is_ancient": event.get("is_ancient") is True,
        }
        for option in event.get("options") or []:
            require(isinstance(option, dict) and option.get("option_key"), "malformed event option")
            option_key = str(option["option_key"]).upper()
            identity = f"{event_id}:{option_key}"
            require(identity not in event_options, f"duplicate event option: {identity}")
            event_options[identity] = {
                "handler": option.get("handler"),
                "raw_commands": sorted(set(option.get("raw_commands") or [])),
            }

    relics: dict[str, Any] = {}
    for key, relic in (game.get("relics") or {}).items():
        require(isinstance(relic, dict) and relic.get("id"), f"malformed relic row: {key}")
        if relic.get("rarity") != "Ancient":
            continue
        relic_id = str(relic["id"]).upper()
        require(relic_id not in relics, f"duplicate ancient relic: {relic_id}")
        relics[relic_id] = {
            "class": relic.get("class"),
            "rarity": relic.get("rarity"),
            "numbers": relic.get("numbers") or {},
            "powers": relic.get("powers") or {},
            "hooks": sorted(relic.get("hooks") or []),
            "internal_effects": sorted(relic.get("effects") or []),
        }

    return {
        "schema_version": SCHEMA,
        "sources": {
            "events": evidence(events_path),
            "game_database": evidence(game_db_path),
            "engine": evidence(engine_path),
        },
        "events": dict(sorted(event_rows.items())),
        "event_options": dict(sorted(event_options.items())),
        "ancient_relics": dict(sorted(relics.items())),
        "semantics": {
            "event_commands": "engine-extracted structural calls; not complete outcome semantics",
            "ancient_relics": "exact option/item id matches may identify offered Ancient relics",
            "natural_outcomes_used": False,
            "utility_weights_included": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--game-db", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.events, args.game_db, args.engine)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(
        json.dumps(
            {
                "events": len(result["events"]),
                "event_options": len(result["event_options"]),
                "ancient_relics": len(result["ancient_relics"]),
                "output_sha256": evidence(args.output)["sha256"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
