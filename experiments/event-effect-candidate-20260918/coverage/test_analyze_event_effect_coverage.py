import json
from pathlib import Path
import tempfile
import unittest

import analyze_event_effect_coverage as event_coverage


class EventEffectCoverageTests(unittest.TestCase):
    def test_locked_identity_maps_to_catalog_option(self):
        self.assertEqual(
            event_coverage.normalized_option_identity(
                "SELF_HELP_BOOK.pages.INITIAL.options.READ_ENTIRE_BOOK_LOCKED"
            ),
            ("SELF_HELP_BOOK", "READ_ENTIRE_BOOK"),
        )

    def test_public_description_and_referenced_vars_are_explicit(self):
        option = {
            "description": "Gain {Gold} Gold. Lose {HpLoss} HP.",
            "vars": {"Gold": 73, "HpLoss": 8, "Unused": 99},
        }
        self.assertEqual(event_coverage.runtime_effects(option["description"]), ["gold_gain", "hp_loss"])
        self.assertEqual(event_coverage.used_variables(option), {"Gold": 73.0, "HpLoss": 8.0})

    def test_catalog_commands_supply_structural_effects(self):
        option = {
            "text_key": "EXAMPLE.pages.INITIAL.options.TAKE",
            "description": "Take it.",
            "vars": None,
        }
        catalog = {
            ("EXAMPLE", "TAKE"): {
                "handler": "Take",
                "raw_commands": ["RelicCmd.Obtain", "CreatureCmd.Damage"],
            }
        }
        facts = event_coverage.option_facts(option, catalog)
        self.assertTrue(facts["catalog_mapped"])
        self.assertEqual(facts["normalized_effects"], ["hp_loss", "relic_gain"])

    def test_exact_game_item_identity_marks_ancient_relic_gain(self):
        option = {
            "text_key": "NEOW.pages.INITIAL.options.BOOMING_CONCH",
            "title": "Booming Conch",
            "description": "At the start of Elite combats, draw cards.",
            "vars": None,
            "is_locked": False,
        }
        items = {
            "BOOMING_CONCH": [
                {"item_type": "relic", "id": "BOOMING_CONCH", "rarity": "Ancient", "effects": []}
            ]
        }
        facts = event_coverage.option_facts(option, {}, items)
        self.assertEqual(facts["normalized_effects"], ["combat", "relic_gain"])
        self.assertEqual(facts["granted_items"][0]["id"], "BOOMING_CONCH")

    def test_plain_option_card_id_collision_does_not_claim_card_gain(self):
        option = {
            "text_key": "STONE_OF_ALL_TIME.pages.INITIAL.options.LIFT",
            "title": "Lift",
            "description": "Try to lift the stone.",
            "vars": None,
            "is_locked": False,
        }
        items = {
            "LIFT": [
                {"item_type": "card", "id": "LIFT", "rarity": "Uncommon", "effects": []}
            ]
        }
        facts = event_coverage.option_facts(option, {}, items)
        self.assertEqual(facts["granted_items"], [])
        self.assertNotIn("card_gain", facts["normalized_effects"])

    def test_end_to_end_audited_decision_coverage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outputs = root / "outputs"
            run = outputs / "run-1"
            audits = root / "audits"
            run.mkdir(parents=True)
            audits.mkdir()
            events = root / "events.json"
            events.write_text(
                json.dumps(
                    {
                        "EXAMPLE": {
                            "id": "EXAMPLE",
                            "options": [
                                {"option_key": "GOLD", "handler": "Gold", "raw_commands": ["PlayerCmd.GainGold"]},
                                {"option_key": "LEAVE", "handler": "Leave", "raw_commands": []},
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            audit = {
                "integration_passed": True,
                "job": {"name": "run-1"},
                "goal": {"natural_goal_success": False, "max_act_observed": 3, "max_floor_in_max_act": 15},
            }
            (audits / "run-1-audit.json").write_text(json.dumps(audit), encoding="utf-8")
            state = {
                "decision_id": "d1",
                "state": {
                    "decision": "event_choice",
                    "context": {"act": 3, "floor": 15},
                    "event_name": "Example",
                    "options": [
                        {"index": 0, "text_key": "EXAMPLE.pages.INITIAL.options.GOLD", "description": "Gain {Gold} Gold.", "vars": {"Gold": 50}},
                        {"index": 1, "text_key": "EXAMPLE.pages.INITIAL.options.LEAVE", "description": "Leave.", "vars": None},
                    ],
                },
            }
            (run / "decisions.jsonl").write_text(json.dumps(state) + "\n", encoding="utf-8")
            policy = {
                "decision_id": "d1",
                "request": {"action": "choose_option", "args": {"option_index": 0}},
                "candidate_id": "a",
                "scoring": {
                    "scores": [
                        {"candidate_id": "a", "score": 0.0, "missing": ["event_effect_and_probability_model"]},
                        {"candidate_id": "b", "score": 0.0, "missing": ["event_effect_and_probability_model"]},
                    ]
                },
            }
            (run / "policy.jsonl").write_text(json.dumps(policy) + "\n", encoding="utf-8")
            result = event_coverage.analyze(events, outputs, [audits], None)
            self.assertEqual(result["all"]["decisions"], 1)
            self.assertEqual(result["by_category"]["near_target_failure"]["decisions"], 1)
            self.assertEqual(result["all"]["uniform_policy_score_decisions"], 1)
            self.assertEqual(result["all"]["catalog_mapped_actionable_option_instances"], 2)
            self.assertEqual(result["all"]["effect_covered_actionable_option_instances"], 2)


if __name__ == "__main__":
    unittest.main()
