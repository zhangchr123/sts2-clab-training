from __future__ import annotations

import copy
import unittest

import event_outcome_features as module


class FakePolicy:
    def _card_score(self, card, state):
        hits = (card.get("stats") or {}).get("repeat", 0)
        return {"features": {"attack_hit_count": hits}}

    def _score_public_future_reward(self, state, cards):
        if not all(card.get("upgraded") is True and card.get("current_upgrade_level") == 1
                   for card in cards):
            raise AssertionError("Future reward was not represented as upgraded")
        return {card["id"]: (index - 2) / 10 for index, card in enumerate(cards)}


def candidate(key, index=0, variables=None):
    event, option = key.split(":")
    return {
        "candidate_id": key,
        "request": {"cmd": "action", "action": "choose_option", "args": {"option_index": index}},
        "evidence": {"index": index,
                     "text_key": f"{event}.pages.INITIAL.options.{option}",
                     "is_locked": False,
                     "vars": variables},
    }


def row(key, score, missing=None):
    item = candidate(key)
    return {
        "candidate_id": key,
        "request": item["request"],
        "score": score,
        "is_skip": False,
        "missing": list(missing or []),
        "reasons": [],
    }


class EventOutcomeFeaturesTest(unittest.TestCase):
    def setUp(self):
        self.policy = FakePolicy()
        self.state = {
            "decision": "event_choice",
            "player": {"hp": 50, "max_hp": 75, "deck": [
                {"id": "CARD.MULTI", "type": "Attack", "cost": 1, "stats": {"damage": 2, "repeat": 3}},
                {"id": "CARD.BLOCK", "type": "Skill", "cost": 1, "stats": {"block": 5}},
                {"id": "CARD.POWER", "type": "Power", "cost": 2, "stats": None},
            ], "relics": [], "potions": []},
        }

    def test_bugslayer_uses_exact_current_engine_cards(self):
        extermination = candidate("BUGSLAYER:EXTERMINATION")
        squash = candidate("BUGSLAYER:SQUASH", 1)
        first = row("BUGSLAYER:EXTERMINATION", 0.0, ["event_outcome_probability_model", "unmodeled_event_effect"])
        second = row("BUGSLAYER:SQUASH", 0.0, ["event_outcome_probability_model", "unmodeled_event_effect"])
        second["request"] = squash["request"]
        packet = module.adjust(self.policy, self.state, {"scores": [first, second]}, {
            first["candidate_id"]: extermination,
            second["candidate_id"]: squash,
        })
        scores = [item["score"] for item in packet["scores"]]
        self.assertAlmostEqual(scores[0], 0.43)
        self.assertAlmostEqual(scores[1], 0.39)
        self.assertNotIn("event_outcome_probability_model", packet["scores"][0]["missing"])
        self.assertEqual(packet["event_outcome_applied_rows"], 2)

    def test_self_help_values_best_public_eligible_target(self):
        values = {}
        for option in ("READ_THE_BACK", "READ_PASSAGE", "READ_ENTIRE_BOOK"):
            key = "SELF_HELP_BOOK:" + option
            item = candidate(key)
            adjustment, detail = module.candidate_adjustment(
                self.policy, self.state, row(key, 0.45), item
            )
            values[option] = detail["exact_score"]
            self.assertAlmostEqual(adjustment, detail["exact_score"] - 0.45)
        self.assertAlmostEqual(values["READ_THE_BACK"], 0.54)
        self.assertAlmostEqual(values["READ_PASSAGE"], (0.15 + 0.08 / 3) * 2 / 2)
        self.assertAlmostEqual(values["READ_ENTIRE_BOOK"], 0.4)

    def test_public_resolved_plain_keeps_parent_score_and_clears_probability_gap(self):
        key = "THIS_OR_THAT:PLAIN"
        item = candidate(key)
        scored = row(key, 1.25, ["event_outcome_probability_model"])
        packet = module.adjust(self.policy, self.state, {"scores": [scored]}, {key: item})
        self.assertEqual(packet["scores"][0]["score"], 1.25)
        self.assertEqual(packet["scores"][0]["event_outcome_adjustment"], 0.0)
        self.assertNotIn("event_outcome_probability_model", packet["scores"][0]["missing"])

    def test_future_of_potions_uses_public_precommitted_type_and_exact_pool(self):
        key = "THE_FUTURE_OF_POTIONS:POTION"
        state = copy.deepcopy(self.state)
        state["player"]["potions"] = [{"index": 0, "id": "POTION.ATTACK_POTION"}]
        variables = {
            "Potion": "ATTACK_POTION.title",
            "Rarity": "CARD_RARITY.COMMON",
            "Type": "CARD_TYPE.SKILL",
        }
        item = candidate(key, variables=variables)
        scored = row(key, -0.25, ["event_outcome_probability_model", "unmodeled_event_effect"])
        adjustment, detail = module.candidate_adjustment(
            self.policy, state, scored, item
        )
        group = [card for card in module.REWARD_POOL
                 if card["rarity"] == "Common" and card["type"] == "Skill"]
        values = [(index - 2) / 10 for index in range(len(group))]
        expected = module._expected_best_of_three(values) - 0.25
        self.assertAlmostEqual(detail["exact_score"], expected)
        self.assertAlmostEqual(adjustment, expected + 0.25)
        self.assertEqual(detail["value_detail"]["filtered_pool_size"], len(group))
        self.assertEqual(detail["value_detail"]["potion_id"], "ATTACK_POTION")
        packet = module.adjust(self.policy, state, {"scores": [scored]}, {key: item})
        self.assertNotIn("event_outcome_probability_model", packet["scores"][0]["missing"])
        self.assertIn("future_potions_card_reward_hook_calibration",
                      packet["scores"][0]["missing"])

    def test_historical_future_of_potions_without_option_vars_stays_unresolved(self):
        key = "THE_FUTURE_OF_POTIONS:POTION"
        item = candidate(key)
        scored = row(key, 0.0, ["event_outcome_probability_model"])
        packet = module.adjust(self.policy, self.state, {"scores": [scored]}, {key: item})
        self.assertEqual(packet["event_outcome_applied_rows"], 0)
        self.assertIn("event_outcome_probability_model", packet["scores"][0]["missing"])
        self.assertEqual(packet["scores"][0]["event_outcome_detail"]["reason"],
                         "public_option_variables_missing")

    def test_future_of_potions_reward_modifier_fails_closed(self):
        key = "THE_FUTURE_OF_POTIONS:POTION"
        state = copy.deepcopy(self.state)
        state["player"]["potions"] = [{"index": 0, "id": "POTION.ENTROPIC_BREW"}]
        state["player"]["relics"] = [{"id": "RELIC.PRISMATIC_GEM"}]
        item = candidate(key, variables={
            "Potion": "ENTROPIC_BREW.title",
            "Rarity": "CARD_RARITY.RARE",
            "Type": "CARD_TYPE.POWER",
        })
        adjustment, detail = module.candidate_adjustment(
            self.policy, state, row(key, 0.0), item
        )
        self.assertEqual(adjustment, 0.0)
        self.assertFalse(detail["applied"])
        self.assertEqual(detail["blocking_relics"], ["RELIC.PRISMATIC_GEM"])

    def test_future_of_potions_mismatched_potion_identity_is_rejected(self):
        key = "THE_FUTURE_OF_POTIONS:POTION"
        state = copy.deepcopy(self.state)
        state["player"]["potions"] = [{"index": 0, "id": "POTION.FOCUS_POTION"}]
        item = candidate(key, variables={
            "Potion": "ATTACK_POTION.title",
            "Rarity": "CARD_RARITY.COMMON",
            "Type": "CARD_TYPE.ATTACK",
        })
        with self.assertRaisesRegex(Exception, "potion identity differs"):
            module.candidate_adjustment(self.policy, state, row(key, 0.0), item)

    def test_random_option_remains_unresolved(self):
        key = "TRIAL:ACCEPT"
        item = candidate(key)
        scored = row(key, 0.0, ["event_outcome_probability_model"])
        packet = module.adjust(self.policy, self.state, {"scores": [scored]}, {key: item})
        self.assertEqual(packet["scores"][0]["score"], 0.0)
        self.assertIn("event_outcome_probability_model", packet["scores"][0]["missing"])
        self.assertEqual(packet["event_outcome_applied_rows"], 0)

    def test_malformed_source_bound_self_help_fails_closed(self):
        state = {"decision": "event_choice", "player": {"hp": 50, "max_hp": 75, "deck": []}}
        key = "SELF_HELP_BOOK:READ_THE_BACK"
        with self.assertRaisesRegex(Exception, "no eligible Attack"):
            module.candidate_adjustment(self.policy, state, row(key, 0.45), candidate(key))


if __name__ == "__main__":
    unittest.main()
