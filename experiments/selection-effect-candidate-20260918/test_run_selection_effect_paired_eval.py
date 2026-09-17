import unittest

import run_selection_effect_paired_eval as paired


class SelectionEffectPairedEvalTests(unittest.TestCase):
    def test_allocation_is_paired_unique_and_order_balanced(self):
        jobs = paired.allocation()
        self.assertTrue(paired.validate_allocation(jobs))
        self.assertEqual(len(jobs), 120)
        self.assertEqual(len({row["seed"] for row in jobs}), 60)
        self.assertEqual(sum(row["arm"] == "control" and row["position"] == 0 for row in jobs), 30)
        self.assertEqual(sum(row["arm"] == "candidate" and row["position"] == 0 for row in jobs), 30)
        self.assertTrue(all("selection-effect" in row["label"] for row in jobs))

    def test_comparison_retains_invalid_runs_as_failures(self):
        rows = []
        for pair_number in range(60):
            for arm in ("control", "candidate"):
                valid = not (pair_number == 0 and arm == "candidate")
                success = pair_number == 1 and arm == "candidate"
                rows.append({
                    "pair": pair_number,
                    "arm": arm,
                    "integration_passed": valid,
                    "goal_success": bool(valid and success),
                    "report": {"outcome": "defeat"},
                })
        result = paired.comparison(rows)
        self.assertEqual(result["candidate"]["invalid_failures"], 1)
        self.assertEqual(result["candidate_only_success"], 1)
        self.assertFalse(result["automatic_deployment"])
        self.assertFalse(result["evaluation_used_for_refit"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
