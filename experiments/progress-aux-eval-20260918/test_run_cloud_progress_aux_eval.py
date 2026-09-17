import copy
import unittest

import run_cloud_progress_aux_eval as trial


def rows():
    return [
        {"pair": pair, "arm": arm, "integration_passed": True, "goal_success": False,
         "report": {"outcome": "defeat"}}
        for pair in range(60) for arm in ("control", "candidate")
    ]


class TrialContracts(unittest.TestCase):
    def test_frozen_pair_shape(self):
        jobs = [
            {"label": f"run-{arm}-{pair}", "seed": f"seed-{pair}", "pair": pair, "arm": arm}
            for pair in range(60) for arm in ("control", "candidate")
        ]
        self.assertTrue(trial.validate_allocation(jobs))

    def test_exact_paired_gate(self):
        data = rows()
        for row in data:
            if row["arm"] == "candidate" and row["pair"] < 6:
                row["goal_success"] = True
        result = trial.comparison(data)
        self.assertEqual(result["one_sided_paired_p"], 1 / 64)
        self.assertTrue(result["improvement_gate_passed"])

    def test_invalid_cannot_be_success(self):
        data = rows()
        data[1].update(integration_passed=False, goal_success=True)
        with self.assertRaisesRegex(ValueError, "Invalid"):
            trial.comparison(data)

    def test_incomplete_denominator_rejected(self):
        with self.assertRaisesRegex(ValueError, "denominator"):
            trial.comparison(rows()[:-1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
