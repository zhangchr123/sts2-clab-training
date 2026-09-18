import unittest
from unittest.mock import patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "assessment"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import assess_merchant_item_paired_eval as assess
import run_merchant_item_paired_eval as runner


class MerchantItemAssessmentTests(unittest.TestCase):
    def protocol(self):
        models = {
            "control": {"path": "/control", "bytes": 1, "sha256": "a"},
            "candidate": {"path": "/candidate", "bytes": 1, "sha256": "b"},
        }
        policies = {"control": "control-v1", "candidate": "candidate-v1"}
        jobs = []
        for row in runner.allocation():
            arm = row["arm"]
            jobs.append(dict(row, model=models[arm], expected_policy_id=policies[arm]))
        return {
            "schema_version": "merchant-item-paired-natural-evaluation-v1",
            "planned_pairs": 60,
            "planned_games": 120,
            "parallel_workers": 1,
            "automatic_retry": False,
            "automatic_deployment": False,
            "no_refit_on_evaluation": True,
            "no_sample_extension": True,
            "natural_outcome_used_for_fit_or_selection": False,
            "smoke_gate_required": True,
            "assessment": "Actual Act3 first boss; invalid retained in denominator as failure",
            "models": models,
            "policy_ids": policies,
            "jobs": jobs,
        }

    @patch.object(assess, "file_evidence")
    def test_allocation_validator_accepts_frozen_balanced_protocol(self, evidence):
        evidence.side_effect = lambda path: self.protocol()["models"]["control" if path == "/control" else "candidate"]
        self.assertEqual(len(assess.validate_allocation(self.protocol())), 120)

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
