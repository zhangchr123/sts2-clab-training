import unittest

import rest_heal_route_features
import rest_heal_route_policy
import reward_mechanism_policy


class RestHealRoutePolicyContractTests(unittest.TestCase):
    def test_source_closure_extends_reward_parent_once_and_prior_is_fixed(self):
        sources = rest_heal_route_policy.FEATURE_SOURCES
        self.assertEqual(len(sources), len(set(sources)))
        self.assertEqual(
            sources[:len(reward_mechanism_policy.FEATURE_SOURCES)],
            reward_mechanism_policy.FEATURE_SOURCES,
        )
        self.assertEqual(sources[-3:], (
            "current_relics_eng.json",
            "rest_heal_route_features.py",
            "rest_heal_route_policy.py",
        ))
        self.assertFalse(rest_heal_route_features.CONTRACT[
            "natural_outcomes_used_for_weight_selection"
        ])
        self.assertFalse(rest_heal_route_features.CONTRACT[
            "future_route_choice_probability_assumed"
        ])


if __name__ == "__main__":
    unittest.main(verbosity=2)
