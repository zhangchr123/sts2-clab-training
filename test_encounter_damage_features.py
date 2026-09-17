import copy
import unittest

import encounter_damage_features as damage
from decision_data import enumerate_candidates
from map_observation import make_map_observation
from test_map_observation import inputs


def catalog():
    table = {}
    base = {"Monster": (0.10, 0.20, 0.30),
            "Elite": (0.25, 0.40, 0.60),
            "Boss": (0.35, 0.55, 0.80)}
    for act in (1, 2, 3):
        for node_type, values in base.items():
            table[f"act{act}:{node_type}"] = {
                "support": 20,
                "cell_weight": 0.5,
                "quantiles": dict(zip(("0.5", "0.75", "0.9"), values)),
            }
    return {
        "schema_version": damage.SCHEMA,
        "passed": True,
        "contract": copy.deepcopy(damage.CATALOG_CONTRACT),
        "automatic_deployment": False,
        "win_rate_claim_permitted": False,
        "final_fit_scope": "train_plus_validation_only_after_smoothing_selected",
        "held_out_test": {"rows": 10},
        "final_table": table,
    }


class EncounterDamageFeatureTests(unittest.TestCase):
    def fixture(self, hp=20):
        state, response = inputs()
        state["player"] = {"hp": hp, "max_hp": 80, "gold": 0}
        return state, make_map_observation(state, response)

    def test_public_paths_accumulate_monotone_known_damage_ranges(self):
        state, observation = self.fixture()
        value = damage.policy_input(state, observation, catalog())
        self.assertTrue(damage.validate_input(state, value))
        self.assertEqual(value["status"], "available")
        for row in value["per_candidate"]:
            summary = row["summary"]
            self.assertLessEqual(summary["damage_q50_to_stop_min"],
                                 summary["damage_q75_to_stop_min"])
            self.assertLessEqual(summary["damage_q75_to_stop_min"],
                                 summary["damage_q90_to_stop_min"])
            self.assertLessEqual(summary["damage_q75_to_stop_min"],
                                 summary["damage_q75_to_stop_max"])

    def test_low_hp_penalty_uses_distribution_and_preserves_unknown_room_gap(self):
        state, observation = self.fixture(hp=8)
        value = damage.policy_input(state, observation, catalog())
        candidates = enumerate_candidates(state)["candidates"]
        packet = {"scores": [{
            "candidate_id": candidate["candidate_id"],
            "request": candidate["request"],
            "score": 1.0,
            "missing": ["encounter_damage_distribution", "unknown_room_outcomes"],
        } for candidate in candidates]}
        result = damage.adjust(state, packet, value)
        self.assertTrue(result["encounter_damage_applied"])
        for row in result["scores"]:
            self.assertNotIn("encounter_damage_distribution", row["missing"])
            self.assertIn("unknown_room_outcomes", row["missing"])
            self.assertAlmostEqual(row["score"], 1.0 + row["encounter_damage_adjustment"])
            self.assertLessEqual(row["encounter_damage_adjustment"], 0)

    def test_unavailable_map_does_not_claim_distribution_coverage(self):
        state, _ = self.fixture()
        observation = make_map_observation(state, {"type": "error", "message": "unavailable"})
        value = damage.policy_input(state, observation, catalog())
        candidate = enumerate_candidates(state)["candidates"][0]
        packet = {"scores": [{
            "candidate_id": candidate["candidate_id"],
            "request": candidate["request"],
            "score": 0.0,
            "missing": ["encounter_damage_distribution"],
        }]}
        result = damage.adjust(state, packet, value)
        self.assertIn("encounter_damage_distribution", result["scores"][0]["missing"])
        self.assertEqual(result["scores"][0]["encounter_damage_adjustment"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
