import copy
import unittest

from decision_data import enumerate_candidates
from map_observation import make_map_observation
from test_map_observation import inputs
import full_route_features as f


class FullRouteFeatureTests(unittest.TestCase):
    def fixture(self, hp=20):
        state, response = inputs()
        state["player"] = {"hp": hp, "max_hp": 80, "gold": 0}
        observation = make_map_observation(state, response)
        return state, observation

    def test_complete_public_paths_keep_fight_elite_and_rest_ranges(self):
        state, observation = self.fixture()
        value = f.policy_input(state, observation)
        left, right = [row["summary"] for row in value["per_candidate"]]
        self.assertEqual(
            (left["min_steps"], left["min_known_fights"], left["min_elites"], left["min_rests"]),
            (2, 1, 0, 1),
        )
        self.assertEqual(
            (right["min_steps"], right["min_known_fights"], right["min_elites"], right["min_rests"]),
            (4, 2, 1, 1),
        )
        self.assertEqual(value["status"], "available")
        self.assertTrue(f.validate_input(state, value))

    def test_low_hp_fixed_prior_prefers_route_without_forced_elite(self):
        state, observation = self.fixture(hp=10)
        value = f.policy_input(state, observation)
        left, right = [f.candidate_features(state, row["summary"])
                       for row in value["per_candidate"]]
        self.assertGreater(f.score(left), f.score(right))
        self.assertEqual(left["low_hp_route_min_elites"], 0)
        self.assertGreater(right["low_hp_route_min_elites"], 0)

    def test_adjust_is_additive_and_does_not_mutate_parent(self):
        state, observation = self.fixture()
        value = f.policy_input(state, observation)
        candidates = enumerate_candidates(state)["candidates"]
        packet = {"scores": [{
            "candidate_id": candidate["candidate_id"],
            "request": candidate["request"],
            "score": 1.0,
            "missing": ["full_route_evaluation", "encounter_damage_distribution"],
        } for candidate in candidates]}
        original = copy.deepcopy(packet)
        result = f.adjust(state, packet, value)
        self.assertEqual(packet, original)
        self.assertTrue(result["full_route_applied"])
        for row in result["scores"]:
            self.assertAlmostEqual(row["score"], 1.0 + row["full_route_adjustment"])
            self.assertNotIn("full_route_evaluation", row["missing"])
            self.assertIn("encounter_damage_distribution", row["missing"])

    def test_unavailable_public_map_retains_all_candidates_at_zero(self):
        state, _ = self.fixture()
        observation = make_map_observation(state, {"type": "error", "message": "unavailable"})
        value = f.policy_input(state, observation)
        self.assertEqual(value["status"], "unavailable")
        self.assertEqual(len(value["per_candidate"]), 2)
        self.assertTrue(all(all(number == 0 for number in row["summary"].values())
                            for row in value["per_candidate"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
