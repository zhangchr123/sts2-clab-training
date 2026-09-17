import unittest

from run_selection_effect_smoke import validate_selection_packets


class SelectionEffectSmokeTests(unittest.TestCase):
    def test_packet_readback_requires_zero_outside_upgrade_and_public_adjustment_inside(self):
        contract = {"fixed": True}
        records = [
            {"decision_id": "map", "state": {"decision": "map_select"}},
            {"decision_id": "upgrade", "state": {"decision": "card_select"}},
        ]
        policies = {
            "map": {"scoring": {
                "policy_id": "v",
                "selection_purpose": None,
                "selection_effect_applied": False,
                "selection_effect_contract": contract,
                "scores": [{
                    "selection_effect_adjustment": 0.0,
                    "selection_effect_detail": {"reason": "not_upgrade_selection"},
                }],
            }},
            "upgrade": {"scoring": {
                "policy_id": "v",
                "selection_purpose": "upgrade",
                "selection_effect_applied": True,
                "selection_effect_contract": contract,
                "scores": [{
                    "selection_effect_adjustment": 0.65,
                    "selection_effect_detail": {
                        "applied": True,
                        "natural_outcomes_used": False,
                        "hidden_reward_or_future_state_used": False,
                    },
                }],
            }},
        }
        result = validate_selection_packets(records, policies, "v", contract)
        self.assertTrue(result["passed"])
        self.assertEqual(result["upgrade_decisions"], 1)
        self.assertEqual(result["nonzero_adjusted_candidates"], 1)

        policies["map"]["scoring"]["scores"][0]["selection_effect_adjustment"] = 0.1
        with self.assertRaises(ValueError):
            validate_selection_packets(records, policies, "v", contract)


if __name__ == "__main__":
    unittest.main(verbosity=2)
