import copy
import unittest

from decision_data import DataContractError
import event_effect_features as event


def state(option, *, hp=30, maximum=60):
    return {
        "decision": "event_choice",
        "context": {"act": 2, "ascension": 10, "combat_in_progress": False},
        "player": {"hp": hp, "max_hp": maximum},
        "options": [option],
    }


def binding(option):
    request = {"action": "choose_option", "args": {"option_index": option["index"]}, "cmd": "action"}
    return {"request": request}, {"request": request, "evidence": option}


class EventEffectFeatureTests(unittest.TestCase):
    def values(self, option, **kwargs):
        row, candidate = binding(option)
        return event.features(state(option, **kwargs), row, candidate)

    def test_dense_vegetation_rest_uses_public_heal_and_direct_combat(self):
        option = {
            "description": "Heal {Heal} HP. Fight some enemies.",
            "index": 1,
            "is_locked": False,
            "text_key": "DENSE_VEGETATION.pages.INITIAL.options.REST",
            "title": "Rest",
            "vars": {"Heal": 22, "Gold": 73, "HpLoss": 8},
        }
        values, detail = self.values(option, hp=30, maximum=60)
        self.assertAlmostEqual(values["event_heal_missing_fraction"], 22 / 60)
        self.assertAlmostEqual(values["event_immediate_combat_health_deficit"], 0.5)
        self.assertEqual(detail["referenced_public_variables"], {"Heal": 22.0})

    def test_ancient_relic_exact_identity_exposes_public_turn_value(self):
        option = {
            "description": "At the start of your turn, draw {Cards} additional cards and gain {Energy}.",
            "index": 0,
            "is_locked": False,
            "text_key": "NEOW.pages.INITIAL.options.BOOMING_CONCH",
            "title": "Booming Conch",
            "vars": {"Cards": 2, "Energy": 1},
        }
        values, detail = self.values(option)
        self.assertEqual(values["event_relic_gain"], 1.0)
        self.assertEqual(values["ancient_relic_energy_each_turn"], 1.0)
        self.assertEqual(values["ancient_relic_draw_each_turn"], 2.0)
        self.assertEqual(detail["ancient_relic"], "BOOMING_CONCH")

    def test_plain_option_card_id_collision_is_not_an_item_grant(self):
        option = {
            "description": "Try to lift the stone.",
            "index": 0,
            "is_locked": False,
            "text_key": "STONE_OF_ALL_TIME.pages.INITIAL.options.LIFT",
            "title": "Lift",
            "vars": None,
        }
        values, detail = self.values(option)
        self.assertEqual(values["event_relic_gain"], 0.0)
        self.assertEqual(values["event_card_offer"], 0.0)
        self.assertEqual(values["event_potion_loss"], 1.0)
        self.assertEqual(values["event_effect_unknown"], 0.0)

    def test_locked_or_hidden_fields_are_rejected(self):
        option = {
            "description": "Locked",
            "index": 0,
            "is_locked": True,
            "text_key": "EXAMPLE.pages.INITIAL.options.TAKE_LOCKED",
            "title": "Locked",
            "vars": None,
        }
        with self.assertRaises(DataContractError):
            self.values(option)
        hidden = copy.deepcopy(option)
        hidden["is_locked"] = False
        hidden["future_reward"] = "secret"
        with self.assertRaises(DataContractError):
            self.values(hidden)

    def test_unknown_effect_has_exact_zero_prior_score(self):
        option = {
            "description": "Ponder the situation.",
            "index": 0,
            "is_locked": False,
            "text_key": "EXAMPLE.pages.INITIAL.options.PONDER",
            "title": "Ponder",
            "vars": None,
        }
        values, _ = self.values(option)
        self.assertEqual(values["event_effect_unknown"], 1.0)
        self.assertEqual(event.score(values), 0.0)

    def test_adjust_breaks_event_tie_without_mutating_parent_packet(self):
        options = [
            {"description": "Gain {Gold} Gold. Lose {HpLoss} HP.", "index": 0, "is_locked": False, "text_key": "DENSE_VEGETATION.pages.INITIAL.options.TRUDGE_ON", "title": "Trudge On", "vars": {"Gold": 73, "Heal": 22, "HpLoss": 8}},
            {"description": "Heal {Heal} HP. Fight some enemies.", "index": 1, "is_locked": False, "text_key": "DENSE_VEGETATION.pages.INITIAL.options.REST", "title": "Rest", "vars": {"Gold": 73, "Heal": 22, "HpLoss": 8}},
        ]
        requests = [
            {"action": "choose_option", "args": {"option_index": index}, "cmd": "action"}
            for index in range(2)
        ]
        packet = {
            "scores": [
                {"candidate_id": f"c{index}", "request": request, "score": 0.0, "is_skip": False, "missing": ["event_effect_and_probability_model"], "reasons": []}
                for index, request in enumerate(requests)
            ]
        }
        candidates = {
            f"c{index}": {"candidate_id": f"c{index}", "request": request, "evidence": options[index]}
            for index, request in enumerate(requests)
        }
        current = state(options[0], hp=30, maximum=60)
        current["options"] = options
        changed = event.adjust(current, packet, candidates)
        self.assertEqual([row["score"] for row in packet["scores"]], [0.0, 0.0])
        self.assertGreater(changed["scores"][1]["score"], changed["scores"][0]["score"])
        self.assertNotIn("event_effect_and_probability_model", changed["scores"][1]["missing"])
        self.assertIn("event_outcome_probability_model", changed["scores"][1]["missing"])


if __name__ == "__main__":
    unittest.main()
