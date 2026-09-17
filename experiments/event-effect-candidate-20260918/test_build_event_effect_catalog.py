import json
from pathlib import Path
import tempfile
import unittest

from build_event_effect_catalog import build


class EventEffectCatalogTests(unittest.TestCase):
    def test_build_keeps_commands_and_only_ancient_relics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            events = root / "events.json"
            database = root / "db.json"
            engine = root / "sts2.dll"
            events.write_text(
                json.dumps(
                    {
                        "Example": {
                            "id": "EXAMPLE",
                            "class": "Example",
                            "is_ancient": False,
                            "options": [
                                {"option_key": "TAKE", "handler": "Take", "raw_commands": ["RelicCmd.Obtain"]}
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            database.write_text(
                json.dumps(
                    {
                        "relics": {
                            "Ancient": {"id": "ANCIENT", "class": "Ancient", "rarity": "Ancient", "numbers": {"energy": 1}, "powers": {}, "hooks": ["AfterSideTurnStart"], "effects": ["PlayerCmd.GainEnergy"]},
                            "Common": {"id": "COMMON", "class": "Common", "rarity": "Common"},
                        }
                    }
                ),
                encoding="utf-8",
            )
            engine.write_bytes(b"engine")
            result = build(events, database, engine)
            self.assertEqual(result["event_options"]["EXAMPLE:TAKE"]["raw_commands"], ["RelicCmd.Obtain"])
            self.assertEqual(list(result["ancient_relics"]), ["ANCIENT"])
            self.assertFalse(result["semantics"]["natural_outcomes_used"])


if __name__ == "__main__":
    unittest.main()
