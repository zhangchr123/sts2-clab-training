import unittest

from decision_data import enumerate_candidates
from replay_event_effect_candidate import compare_decision


class EventEffectReplayTests(unittest.TestCase):
    def test_public_heal_breaks_neutral_event_tie(self):
        options = [
            {"description": "Gain {Gold} Gold. Lose {HpLoss} HP.", "index": 0, "is_locked": False, "text_key": "DENSE_VEGETATION.pages.INITIAL.options.TRUDGE_ON", "title": "Trudge On", "vars": {"Gold": 73, "Heal": 22, "HpLoss": 8}},
            {"description": "Heal {Heal} HP. Fight some enemies.", "index": 1, "is_locked": False, "text_key": "DENSE_VEGETATION.pages.INITIAL.options.REST", "title": "Rest", "vars": {"Gold": 73, "Heal": 22, "HpLoss": 8}},
        ]
        state = {
            "type": "decision",
            "decision": "event_choice",
            "context": {"act": 2, "ascension": 10, "combat_in_progress": False},
            "event_name": "Dense Vegetation",
            "options": options,
            "player": {"hp": 30, "max_hp": 60, "deck": [], "deck_size": 0},
        }
        space = enumerate_candidates(state)
        self.assertTrue(space["complete"])
        candidates = {candidate["candidate_id"]: candidate for candidate in space["candidates"]}
        rows = [
            {"candidate_id": candidate["candidate_id"], "request": candidate["request"], "score": 0.0}
            for candidate in space["candidates"]
        ]
        policy = {
            "candidate_id": rows[0]["candidate_id"],
            "scoring": {"scores": rows},
        }
        compared = compare_decision(state, policy, candidates)
        self.assertTrue(compared["old_uniform"])
        self.assertFalse(compared["new_uniform"])
        selected = next(row for row in compared["rows"] if row["candidate_id"] in compared["new_greedy"])
        self.assertEqual(selected["text_key"], "DENSE_VEGETATION.pages.INITIAL.options.REST")


if __name__ == "__main__":
    unittest.main()
