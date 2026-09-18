"""Read-only compact timeline for already completed games in a live CLab batch."""
from collections import Counter
from pathlib import Path
import sys

from decision_data import read_decisions


root = Path(sys.argv[1])
prefix = sys.argv[2] if len(sys.argv) > 2 else ""
for folder in sorted(root.iterdir()):
    if (
        not folder.is_dir()
        or not folder.name.startswith(prefix)
        or not (folder / "decisions.jsonl").exists()
    ):
        continue
    records = read_decisions(folder / "decisions.jsonl")
    print(f"\n=== {folder.name} records={len(records)}")
    for record in records:
        state = record["state"]
        context = state.get("context") or {}
        player = state.get("player") or {}
        chosen = record["chosen"]
        evidence = chosen.get("evidence") or {}
        request = chosen.get("request") or {}
        decision = state.get("decision")
        floor = context.get("floor")
        if decision == "map_select" and floor not in (1, 7, 14, 15, 16, 17):
            continue
        identity = (
            evidence.get("id")
            or evidence.get("title")
            or evidence.get("name")
            or evidence.get("text_key")
            or ""
        )
        action = request.get("action") or request.get("cmd")
        print(
            f"{record['sequence']:03} A{context.get('act')}F{floor!s:>2} "
            f"{decision or '':18} hp={player.get('hp')}/{player.get('max_hp')} "
            f"deck={player.get('deck_size')} -> {action} {identity}"
        )
    last = next(
        (
            record["state"]
            for record in reversed(records)
            if (record["state"].get("player") or {}).get("deck")
        ),
        None,
    )
    if last:
        cards = last["player"].get("deck") or []
        counts = Counter(
            (card.get("name") or card.get("id") or "?")
            + ("+" if card.get("upgraded") else "")
            for card in cards
        )
        print("FINAL DECK", last["player"].get("deck_size"), dict(counts))
