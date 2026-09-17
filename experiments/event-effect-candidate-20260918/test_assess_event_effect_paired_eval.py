import unittest

import assess_event_effect_paired_eval as assess
import run_event_effect_paired_eval as runner


class EventEffectAssessmentTests(unittest.TestCase):
    def test_allocation_validator_accepts_frozen_balanced_protocol(self):
        protocol = {
            "planned_pairs": 60,
            "planned_games": 120,
            "parallel_workers": 1,
            "automatic_retry": False,
            "automatic_deployment": False,
            "no_refit_on_evaluation": True,
            "no_sample_extension": True,
            "jobs": runner.allocation(),
        }
        self.assertEqual(len(assess.validate_allocation(protocol)), 120)

    def test_independent_comparison_matches_runner(self):
        rows = []
        for pair in range(60):
            for arm in ("control", "candidate"):
                success = pair in (0, 1) and arm == "candidate"
                rows.append({
                    "pair": pair,
                    "arm": arm,
                    "integration_passed": True,
                    "goal_success": success,
                    "report": {"outcome": "defeat"},
                })
        self.assertEqual(assess.comparison(rows), runner.comparison(rows))


if __name__ == "__main__":
    unittest.main(verbosity=2)
