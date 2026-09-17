import unittest

import full_route_features
import full_route_policy
import selection_effect_policy


class FullRoutePolicyContractTests(unittest.TestCase):
    def test_source_closure_extends_parent_once(self):
        sources = full_route_policy.FEATURE_SOURCES
        self.assertEqual(len(sources), len(set(sources)))
        self.assertEqual(
            sources[:len(selection_effect_policy.FEATURE_SOURCES)],
            selection_effect_policy.FEATURE_SOURCES,
        )
        self.assertEqual(sources[-2:], ("full_route_features.py", "full_route_policy.py"))
        self.assertFalse(full_route_features.CONTRACT["natural_outcomes_used"])
        self.assertFalse(full_route_features.CONTRACT["hidden_rooms_or_encounters_used"])
        self.assertFalse(full_route_features.CONTRACT["encounter_damage_distribution_claimed"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
