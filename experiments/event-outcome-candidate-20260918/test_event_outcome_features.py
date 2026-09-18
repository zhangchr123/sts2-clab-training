from __future__ import annotations

import unittest

import event_outcome_features as module


class FakePolicy:
    def _card_score(self, card, state):
        hits = (card.get("stats") or {}).get("repeat", 0)
        return {"features": {"attack_hit_count": hits}}


def candidate(key, index=0):
    event, option = key.split(":")
    return {
        "candidate_id": key,
        "request": {"cmd": "action", "action": "choose_option", "args": {"option_index": index}},
        "evidence": {"text_key": f"{event}.pages.INITIAL.options.{option}", "is_locked": False},
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
            ]},
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
