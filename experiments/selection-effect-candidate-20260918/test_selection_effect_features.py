import copy
import unittest

from decision_data import DataContractError
import selection_effect_features as f


def candidate(card):
    return {
        "candidate_id": "c",
        "request": {"cmd": "action", "action": "select_cards", "args": {"card_indices": [0]}},
        "evidence": {"cards": [card]},
    }


class SelectionEffectFeatureTests(unittest.TestCase):
    def test_upgrade_values_cost_draw_and_removed_exhaust(self):
        card = {
            "id": "CARD.TEST", "cost": 2, "stats": {"cards": 1},
            "keywords": ["Exhaust"], "upgrade_preview_status": "available",
            "upgrade_preview_basis": "canonical_plus_upgrade_level",
            "upgrade_preview_instance_modifiers_copied": False,
            "after_upgrade": {"cost": 1, "stats": {"cards": 2},
                              "added_keywords": None, "removed_keywords": ["Exhaust"]},
        }
        values, detail = f.card_features(card)
        self.assertEqual(values["upgrade_cost_reduction"], 1)
        self.assertEqual(values["upgrade_draw_gain"], 1)
        self.assertEqual(values["upgrade_remove_exhaust"], 1)
        self.assertFalse(detail["instance_modifiers_copied"])
        self.assertGreater(f.score(values), 1.4)

    def test_adjust_is_additive_and_does_not_mutate_parent(self):
        card = {
            "id": "CARD.TEST", "cost": 1, "stats": {"damage": 5}, "keywords": None,
            "upgrade_preview_status": "available", "upgrade_preview_basis": "canonical_plus_upgrade_level",
            "upgrade_preview_instance_modifiers_copied": False,
            "after_upgrade": {"cost": 1, "stats": {"damage": 8},
                              "added_keywords": None, "removed_keywords": None},
        }
        c = candidate(card)
        packet = {"selection_purpose": "upgrade", "scores": [{
            "candidate_id": "c", "request": c["request"], "score": 1.0,
            "missing": ["selection_effect_model", "upgrade_preview_instance_modifications"],
        }]}
        original = copy.deepcopy(packet)
        result = f.adjust({"decision": "card_select"}, packet, {"c": c})
        row = result["scores"][0]
        self.assertEqual(packet, original)
        self.assertAlmostEqual(row["score"], 1.0 + row["selection_effect_adjustment"])
        self.assertNotIn("selection_effect_model", row["missing"])
        self.assertIn("upgrade_preview_instance_modifications", row["missing"])

    def test_non_upgrade_selection_is_exact_zero(self):
        c = candidate({"id": "CARD.TEST"})
        packet = {"selection_purpose": "remove", "scores": [{
            "candidate_id": "c", "request": c["request"], "score": 2.0,
        }]}
        result = f.adjust({"decision": "card_select"}, packet, {"c": c})
        self.assertEqual(result["scores"][0]["score"], 2.0)
        self.assertFalse(result["selection_effect_applied"])

    def test_malformed_public_preview_is_rejected(self):
        card = {
            "id": "CARD.TEST", "cost": 1, "stats": None, "keywords": None,
            "upgrade_preview_status": "available", "after_upgrade": None,
        }
        with self.assertRaises(DataContractError):
            f.card_features(card)


if __name__ == "__main__":
    unittest.main(verbosity=2)
