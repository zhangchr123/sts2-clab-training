import unittest

import encounter_damage_features
import encounter_damage_policy
import full_route_policy


class EncounterDamagePolicyContractTests(unittest.TestCase):
    def test_source_closure_extends_parent_once(self):
        sources = encounter_damage_policy.FEATURE_SOURCES
        self.assertEqual(len(sources), len(set(sources)))
        self.assertEqual(
            sources[:len(full_route_policy.FEATURE_SOURCES)],
            full_route_policy.FEATURE_SOURCES,
        )
        self.assertEqual(
            sources[-3:],
            (
                "train_encounter_damage_catalog.py",
                "encounter_damage_features.py",
                "encounter_damage_policy.py",
            ),
        )
        self.assertFalse(encounter_damage_features.CONTRACT[
            "unknown_room_damage_assumed"
        ])
        self.assertFalse(encounter_damage_features.CONTRACT[
            "encounter_identity_used"
        ])


if __name__ == "__main__":
    unittest.main(verbosity=2)
