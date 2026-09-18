import unittest

import encounter_damage_features
from initial_policy import InitialPolicy
import rest_heal_route_features as rest


def state(hp=20, maximum=67):
    return {
        "type": "decision",
        "decision": "rest_site",
        "options": [
            {"index": 0, "is_enabled": True,
             "name": "HealRestSiteOption", "option_id": "HEAL"},
            {"index": 1, "is_enabled": True,
             "name": "SmithRestSiteOption", "option_id": "SMITH"},
        ],
        "context": {"ascension": 10, "act": 2, "floor": 8,
                    "combat_in_progress": False},
        "player": {
            "hp": hp, "max_hp": maximum, "gold": 100,
            "deck": [{
                "id": "CARD.STRIKE_DEFECT", "cost": 1, "type": "Attack",
                "stats": {"damage": 6}, "current_upgrade_level": 0,
                "after_upgrade": {"cost": 1, "stats": {"damage": 9}},
            }],
            "deck_size": 1,
            "relics": [],
        },
    }


def context(*, unknowns=0):
    names = set(encounter_damage_features.SUMMARY_NAMES) - {"path_available"}
    best = dict.fromkeys(names, 0.0)
    worst = dict.fromkeys(names, 0.0)
    best.update(
        damage_q75_to_stop_min=.50,
        damage_q90_to_stop_min=.70,
        damage_q75_to_boss_min=.90,
    )
    worst.update(best)
    worst["unknowns_to_stop_max"] = float(unknowns)
    return {
        "version": rest.VERSION,
        "source_map_state_hash": "source-map-hash",
        "public_map_hash": "public-map-hash",
        "catalog_schema": "catalog-schema",
        "act": 2,
        "selected_rest_position": [3, 7],
        "route": {
            "outgoing_nodes": 2,
            "available_outgoing_nodes": 2,
            "best_achievable": best,
            "worst_available": worst,
        },
    }


class RestHealRouteFeatureTests(unittest.TestCase):
    def test_heal_uses_exact_projection_and_bridges_public_route_risk(self):
        current = state()
        parent = InitialPolicy(prior_path=None, epsilon=0).score(current)
        old = {row["candidate_id"]: row for row in parent["scores"]}
        result = rest.adjust(current, parent, context())
        rows = {row["candidate_id"]: row for row in result["scores"]}
        heal_id = next(candidate_id for candidate_id, row in old.items()
                       if row["features"]["rest_heal"] == 1)
        smith_id = next(candidate_id for candidate_id, row in old.items()
                        if row["features"]["rest_smith"] == 1)
        heal = rows[heal_id]
        smith = rows[smith_id]
        self.assertGreater(heal["rest_heal_route_adjustment"], 0)
        self.assertEqual(smith["rest_heal_route_adjustment"], 0)
        self.assertEqual(heal["rest_heal_route_detail"]["heal_projection"][
            "hp_after"], 40)
        self.assertNotIn("actual_rest_heal_amount", heal["missing"])
        self.assertNotIn("future_route_damage_distribution", heal["missing"])
        self.assertAlmostEqual(
            heal["score"],
            old[heal_id]["score"] + heal["rest_heal_route_adjustment"],
        )

    def test_unknown_route_stays_explicit(self):
        current = state()
        result = rest.adjust(
            current, InitialPolicy(prior_path=None, epsilon=0).score(current),
            context(unknowns=1),
        )
        heal = next(row for row in result["scores"]
                    if row["rest_heal_route_detail"]["applied"])
        self.assertIn("unknown_room_outcomes", heal["missing"])

    def test_missing_latched_context_fails_open_without_clearing_gaps(self):
        current = state()
        parent = InitialPolicy(prior_path=None, epsilon=0).score(current)
        result = rest.adjust(current, parent, None)
        heal = next(row for row in result["scores"]
                    if row["features"]["rest_heal"] == 1)
        self.assertEqual(heal["rest_heal_route_adjustment"], 0)
        self.assertIn("actual_rest_heal_amount", heal["missing"])
        self.assertIn("future_route_damage_distribution", heal["missing"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
