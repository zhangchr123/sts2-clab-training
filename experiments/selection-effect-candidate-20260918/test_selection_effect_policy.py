import unittest

import event_effect_policy
import selection_effect_features
import selection_effect_policy


class SelectionEffectPolicyContractTests(unittest.TestCase):
    def test_source_closure_extends_parent_once(self):
        sources = selection_effect_policy.FEATURE_SOURCES
        self.assertEqual(len(sources), len(set(sources)))
        self.assertEqual(sources[:len(event_effect_policy.FEATURE_SOURCES)], event_effect_policy.FEATURE_SOURCES)
        self.assertEqual(sources[-2:], ("selection_effect_features.py", "selection_effect_policy.py"))
        self.assertFalse(selection_effect_features.CONTRACT["natural_outcomes_used"])
        self.assertFalse(selection_effect_features.CONTRACT["instance_upgrade_modifiers_assumed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
