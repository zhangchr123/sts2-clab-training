import unittest

import run_event_effect_smoke as smoke


class EventEffectSmokeTests(unittest.TestCase):
    def test_packet_audit_accepts_public_event_adjustments_and_non_event_rows(self):
        contract = {"natural_outcomes_used": False}
        records = [
            {"decision_id": "a", "state": {"decision": "card_reward"}},
            {"decision_id": "b", "state": {"decision": "event_choice"}},
        ]
        policies = {
            "a": {"scoring": {"policy_id": "event-v1"}},
            "b": {"scoring": {
                "policy_id": "event-v1",
                "event_effect_contract": contract,
                "scores": [
                    {"event_effect_adjustment": 2.0, "event_effect_detail": {
                        "applied": True, "natural_outcomes_used": False,
                    }},
                    {"event_effect_adjustment": 0.0, "event_effect_detail": {
                        "applied": False, "reason": "not_event_choice",
                    }},
                ],
            }},
        }
        result = smoke.validate_event_packets(records, policies, "event-v1", contract)
        self.assertEqual(result["event_decisions"], 1)
        self.assertEqual(result["nonzero_adjusted_candidates"], 1)

    def test_packet_audit_rejects_natural_outcome_use(self):
        records = [{"decision_id": "b", "state": {"decision": "event_choice"}}]
        contract = {"natural_outcomes_used": False}
        policies = {"b": {"scoring": {
            "policy_id": "event-v1",
            "event_effect_contract": contract,
            "scores": [{"event_effect_adjustment": 1.0, "event_effect_detail": {
                "applied": True, "natural_outcomes_used": True,
            }}],
        }}}
        with self.assertRaisesRegex(ValueError, "Natural outcome leak"):
            smoke.validate_event_packets(records, policies, "event-v1", contract)


if __name__ == "__main__":
    unittest.main(verbosity=2)
