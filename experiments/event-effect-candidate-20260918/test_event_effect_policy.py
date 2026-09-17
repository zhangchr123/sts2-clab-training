import unittest

import event_effect_features
import event_effect_policy


class EventEffectPolicyContractTests(unittest.TestCase):
    def test_source_closure_is_unique_and_contains_event_contract(self):
        self.assertEqual(len(event_effect_policy.FEATURE_SOURCES), len(set(event_effect_policy.FEATURE_SOURCES)))
        self.assertTrue(
            {"event_effect_catalog.json", "event_effect_features.py", "event_effect_policy.py"}
            <= set(event_effect_policy.FEATURE_SOURCES)
        )
        self.assertFalse(event_effect_features.CONTRACT["natural_outcomes_used"])
        self.assertFalse(event_effect_features.CONTRACT["hidden_reward_or_future_state_used"])


if __name__ == "__main__":
    unittest.main()
