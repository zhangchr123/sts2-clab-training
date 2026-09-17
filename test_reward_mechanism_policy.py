import unittest

import encounter_damage_policy
import reward_mechanism_features
import reward_mechanism_policy


class RewardMechanismPolicyContractTests(unittest.TestCase):
    def test_source_closure_extends_parent_once_and_prior_is_fixed(self):
        sources = reward_mechanism_policy.FEATURE_SOURCES
        self.assertEqual(len(sources), len(set(sources)))
        self.assertEqual(
            sources[:len(encounter_damage_policy.FEATURE_SOURCES)],
            encounter_damage_policy.FEATURE_SOURCES,
        )
        self.assertEqual(sources[-4:], (
            "current_cards_eng.json",
            "reward_mechanism_facts.py",
            "reward_mechanism_features.py",
            "reward_mechanism_policy.py",
        ))
        self.assertFalse(reward_mechanism_features.FEATURE_CONTRACT[
            "policy_weights_fitted"
        ])
        self.assertFalse(reward_mechanism_features.FEATURE_CONTRACT[
            "future_condition_probabilities_assumed"
        ])


if __name__ == "__main__":
    unittest.main(verbosity=2)
