import copy
import unittest

import merchant_item_features as f


def card(item_id, card_type="Skill", cost=1):
    return {"id": "CARD." + item_id, "type": card_type, "cost": cost,
            "description": item_id, "stats": None}


def state(*, hp=65, maximum=80, gold=300, full=False):
    held = []
    if full:
        held = [
            {"id": "POTION.WEAK_POTION", "index": 0, "name": "Weak Potion",
             "description": f._description("POTION.WEAK_POTION"),
             "target_type": "AnyEnemy", "vars": {"WeakPower": 3}},
            {"id": "POTION.ENERGY_POTION", "index": 1, "name": "Energy Potion",
             "description": f._description("POTION.ENERGY_POTION"),
             "target_type": "AnyPlayer", "vars": {"Energy": 2}},
        ]
    return {
        "type": "decision",
        "decision": "shop",
        "context": {"act": 2, "floor": 7, "room_type": "Shop"},
        "player": {
            "hp": hp, "max_hp": maximum, "gold": gold,
            "potion_capacity": 2, "potion_empty_slots": 0 if full else 2,
            "potions": held,
            "deck": [card("ZAP"), card("GLACIER"), card("BALL_LIGHTNING", "Attack"),
                     card("DEFEND_DEFECT"), card("STRIKE_DEFECT", "Attack")],
            "relics": [],
        },
        "cards": [], "relics": [], "potions": [], "can_leave": True,
    }


def candidate(action, item_id, *, index=0, cost=None, can_purchase=None):
    request = {"cmd": "action", "action": action,
               "args": {"relic_index" if action == "buy_relic" else "potion_index": index}}
    evidence = {"id": item_id, "index": index,
                "description": f._description(item_id), "name": item_id}
    if cost is not None:
        evidence.update(cost=cost, is_stocked=True)
    if can_purchase is not None:
        evidence["can_purchase"] = can_purchase
    return {"candidate_id": action + ":" + item_id, "request": request,
            "evidence": evidence, "is_skip": False}


def adjusted(one_state, one_candidate, score, missing):
    row = {"candidate_id": one_candidate["candidate_id"],
           "request": copy.deepcopy(one_candidate["request"]), "score": score,
           "missing": list(missing), "reasons": [], "is_skip": False}
    packet = {"scores": [row]}
    return f.adjust(one_state, packet, {one_candidate["candidate_id"]: one_candidate})["scores"][0]


class MerchantItemFeatureTests(unittest.TestCase):
    def test_data_disk_and_runic_capacitor_use_orb_context(self):
        rich = state()
        data, detail = f.item_utility(rich, "RELIC.DATA_DISK")
        runic, _ = f.item_utility(rich, "RELIC.RUNIC_CAPACITOR")
        self.assertAlmostEqual(data, 1.92)
        self.assertAlmostEqual(runic, 1.32)
        self.assertEqual(detail["orb_sources"], 3)
        poor = state()
        poor["player"]["deck"] = [card("STRIKE_DEFECT", "Attack"), card("DEFEND_DEFECT")]
        self.assertEqual(f.item_utility(poor, "RELIC.DATA_DISK")[0], 0.0)

    def test_waffle_uses_exact_public_heal_and_max_hp(self):
        value, detail = f.item_utility(state(hp=65, maximum=80), "RELIC.LEES_WAFFLE")
        self.assertAlmostEqual(value, 2.62)
        self.assertEqual(detail["hp_gain"], 22.0)
        self.assertEqual(detail["max_hp_gain"], 7.0)

    def test_core_potion_scales_reuse_parent_mechanisms(self):
        current = state(hp=65, maximum=80)
        self.assertAlmostEqual(f.item_utility(current, "POTION.ENERGY_POTION")[0], 1.0)
        self.assertAlmostEqual(f.item_utility(current, "POTION.SWIFT_POTION")[0], 1.8)
        self.assertAlmostEqual(f.item_utility(current, "POTION.FOCUS_POTION")[0], .78)
        self.assertAlmostEqual(f.item_utility(current, "POTION.BLOCK_POTION")[0], 1.98)
        self.assertAlmostEqual(f.item_utility(current, "POTION.FIRE_POTION")[0], 3.6)

    def test_purchase_adds_utility_and_clears_exact_gap(self):
        current = state()
        row = adjusted(current, candidate("buy_potion", "POTION.ENERGY_POTION",
                                          cost=50, can_purchase=True),
                       -0.25 - 50 / 150, ["item_effect_model"])
        self.assertAlmostEqual(row["score"], 1.0 - 0.25 - 50 / 150)
        self.assertNotIn("item_effect_model", row["missing"])
        self.assertIn("merchant_item_value_calibration", row["missing"])

    def test_discard_scores_visible_affordable_replacement(self):
        current = state(gold=100, full=True)
        current["potions"] = [{
            "id": "POTION.FIRE_POTION", "index": 0, "name": "Fire Potion",
            "description": f._description("POTION.FIRE_POTION"),
            "cost": 50, "is_stocked": True, "can_purchase": False,
        }]
        held = candidate("discard_potion", "POTION.WEAK_POTION")
        held["evidence"].update(target_type="AnyEnemy", vars={"WeakPower": 3})
        row = adjusted(current, held, -0.5, ["potion_replacement_utility"])
        expected = (3.6 - .25 - 50 / 150) - .3
        self.assertAlmostEqual(row["score"], expected)
        self.assertEqual(row["merchant_item_detail"]["value_detail"]["replacement"]["item_id"],
                         "POTION.FIRE_POTION")
        self.assertNotIn("potion_replacement_utility", row["missing"])

    def test_unknown_item_keeps_parent_score_and_gap(self):
        current = state()
        unknown = {"candidate_id": "unknown", "request": {"cmd": "action",
                   "action": "buy_relic", "args": {"relic_index": 0}},
                   "evidence": {"id": "RELIC.UNKNOWN", "index": 0}, "is_skip": False}
        row = adjusted(current, unknown, -1.0, ["item_effect_model"])
        self.assertEqual(row["score"], -1.0)
        self.assertEqual(row["merchant_item_adjustment"], 0.0)
        self.assertIn("item_effect_model", row["missing"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

