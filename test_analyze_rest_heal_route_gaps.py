import unittest

from analyze_rest_heal_route_gaps import heal_projection


def state(hp, maximum, relics=()):
    return {
        "player": {
            "hp": hp,
            "max_hp": maximum,
            "relics": list(relics),
        }
    }


class RestHealProjectionTests(unittest.TestCase):
    def test_base_heal_is_thirty_percent_of_old_max_rounded_down(self):
        self.assertEqual(heal_projection(state(38, 67)), {
            "hp_before": 38,
            "max_hp_before": 67,
            "base_heal": 20,
            "regal_pillow_heal": 0,
            "stone_humidifier_max_hp": 0,
            "uncapped_hp_gain": 20,
            "hp_gain": 20,
            "hp_after": 58,
            "max_hp_after": 67,
        })

    def test_public_relic_vars_apply_and_cap_at_new_max_hp(self):
        relics = (
            {"id": "RELIC.REGAL_PILLOW", "vars": {"Heal": 15}},
            {"id": "RELIC.STONE_HUMIDIFIER", "vars": {"MaxHp": 5}},
        )
        projection = heal_projection(state(70, 75, relics))
        self.assertEqual(projection["base_heal"], 22)
        self.assertEqual(projection["uncapped_hp_gain"], 42)
        self.assertEqual(projection["hp_gain"], 10)
        self.assertEqual(projection["hp_after"], 80)
        self.assertEqual(projection["max_hp_after"], 80)


if __name__ == "__main__":
    unittest.main(verbosity=2)
