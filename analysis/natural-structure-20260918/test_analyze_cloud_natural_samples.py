import unittest

from analyze_cloud_natural_samples import summarize


class NaturalAnalysisTests(unittest.TestCase):
    def test_invalid_is_not_a_success_or_deck_denominator(self):
        valid = {"run_id": "v", "integration_passed": True, "target_success": True, "max_act": 3,
                 "max_floor": 16, "final_deck_size": 25, "max_observed_deck_size": 25,
                 "special_builds": [], "final_deck": [], "upgraded_cards": 4,
                 "card_rewards_taken": 2, "card_rewards_skipped": 3}
        invalid = dict(valid, run_id="i", integration_passed=False, final_deck_size=99,
                       max_observed_deck_size=99, target_success=True)
        result = summarize([valid, invalid])
        self.assertEqual(result["valid"], 1)
        self.assertEqual(result["target_successes"], 1)
        self.assertEqual(result["deck_size"]["maximum"], 25)


if __name__ == "__main__":
    unittest.main(verbosity=2)
