import unittest

import build_decision_priorities_v2 as builder


class PriorityBuilderTests(unittest.TestCase):
    def test_fixed_denominator_and_bounded_priorities(self):
        action = {
            "decisions": 7,
            "missing_signal_decisions": 5,
            "margin_at_most_0_10": 3,
        }
        result = {
            "schema_version": "cloud-natural-policy-decision-diagnostics-v1",
            "samples": 4,
            "category_counts": {
                "target_success": 1,
                "near_target_failure": 1,
                "earlier_failure": 1,
                "invalid": 1,
            },
            "by_category": {"near_target_failure": {"actions": {
                key: dict(action) for key in ("event_choice", "card_select", "map_select", "card_reward", "rest_site")
            }}},
            "near_target_review_queue_total": 2,
            "near_target_review_queue_retained": 2,
            "near_target_review_queue": [
                {"act": 3, "floor": 10, "action": "event_choice"},
                {"act": 2, "floor": 16, "action": "map_select"},
            ],
            "interpretation": {"natural_outcomes_used_for_fitting": False},
        }
        plan = builder.build(result, {"path": "/result", "bytes": 1, "sha256": "a"})
        self.assertEqual(plan["audited_natural_runs"], 4)
        self.assertEqual(plan["late_act3_review_decisions"], 1)
        self.assertEqual(len(plan["priorities"]), 5)
        self.assertFalse(plan["interpretation"]["natural_outcomes_used_for_fitting"])

    def test_category_denominator_mismatch_is_rejected(self):
        result = {
            "schema_version": "cloud-natural-policy-decision-diagnostics-v1",
            "samples": 2,
            "category_counts": {"target_success": 1, "near_target_failure": 0, "earlier_failure": 0, "invalid": 0},
            "interpretation": {"natural_outcomes_used_for_fitting": False},
        }
        with self.assertRaisesRegex(ValueError, "denominator"):
            builder.build(result, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
