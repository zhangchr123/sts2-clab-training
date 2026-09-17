import copy
import unittest

from decision_data import DataContractError, enumerate_candidates
from initial_policy import InitialPolicy
import reward_mechanism_features as reward
from reward_mechanism_facts import expected_description, validate_card


def card(cid, stats, *, cost=1, kind="Skill", rarity="Common"):
    return {
        "id": "CARD." + cid,
        "stats": copy.deepcopy(stats),
        "cost": cost,
        "type": kind,
        "rarity": rarity,
        "description": expected_description(cid),
        "current_upgrade_level": 0,
    }


def state(cards):
    deck = [
        card("BALL_LIGHTNING", {"damage": 7}, kind="Attack"),
        card("COLD_SNAP", {"damage": 6}, kind="Attack"),
        card("LEAP", {"block": 9}),
    ]
    return {
        "type": "decision",
        "decision": "card_reward",
        "cards": [dict(value, index=index) for index, value in enumerate(cards)],
        "can_skip": True,
        "context": {"ascension": 10, "act": 2, "floor": 5,
                    "combat_in_progress": False},
        "player": {"hp": 40, "max_hp": 75, "gold": 100,
                   "deck": deck, "deck_size": len(deck)},
    }


class RewardMechanismFeatureTests(unittest.TestCase):
    def packet(self, current):
        packet = InitialPolicy(prior_path=None, epsilon=0).score(current)
        return packet, {row["candidate_id"]: row for row in packet["scores"]}

    def test_sweeping_beam_clears_bound_semantic_gaps_and_adds_draw_aoe(self):
        current = state([card("SWEEPING_BEAM", {"damage": 6, "cards": 1},
                              kind="Attack")])
        parent, before = self.packet(current)
        candidate = reward.adjust(current, parent)
        after = {row["candidate_id"]: row for row in candidate["scores"]}
        cid = next(key for key, row in before.items() if not row["is_skip"])
        self.assertIn("mechanism_coverage", before[cid]["missing"])
        self.assertIn("cards_effect_semantics", before[cid]["missing"])
        self.assertNotIn("mechanism_coverage", after[cid]["missing"])
        self.assertNotIn("cards_effect_semantics", after[cid]["missing"])
        self.assertGreater(after[cid]["reward_mechanism_features"]["new_draw_per_cost"], 0)
        self.assertEqual(after[cid]["reward_mechanism_features"]["aoe"], 1)
        self.assertGreater(after[cid]["reward_mechanism_adjustment"], 0)
        self.assertAlmostEqual(after[cid]["score"], before[cid]["score"] +
                               after[cid]["reward_mechanism_adjustment"])

    def test_charge_battery_uses_next_turn_energy_not_immediate_energy(self):
        current = state([card("CHARGE_BATTERY", {"block": 7, "energy": 1})])
        parent, before = self.packet(current)
        result = reward.adjust(current, parent)
        row = next(row for row in result["scores"] if not row["is_skip"])
        self.assertEqual(row["reward_mechanism_features"]["new_immediate_energy_per_cost"], 0)
        self.assertGreater(row["reward_mechanism_features"]["new_next_energy_per_cost"], 0)
        self.assertNotIn("energy_effect_semantics", row["missing"])

    def test_parent_covered_mechanisms_are_not_scored_twice(self):
        cases = (
            (card("TURBO", {"energy": 2}, cost=0),
             ("new_immediate_energy_per_cost", "generated_status_burden")),
            (card("HOLOGRAM", {"block": 3}), ("discard_retrieval",)),
            (card("COLD_SNAP", {"damage": 6}, kind="Attack"),
             ("frost_per_cost",)),
            (card("DEFRAGMENT", {"focuspower": 1}, kind="Power"),
             ("sustained_focus_support",)),
        )
        for value, features in cases:
            with self.subTest(card=value["id"]):
                current = state([value])
                parent, before = self.packet(current)
                parent_row = next(row for row in before.values() if not row["is_skip"])
                self.assertNotIn("mechanism_coverage", parent_row["missing"])
                row = next(row for row in reward.adjust(current, parent)["scores"]
                           if not row["is_skip"])
                for feature in features:
                    self.assertEqual(row["reward_mechanism_features"][feature], 0)

    def test_chill_scores_one_conservative_frost_and_retains_enemy_count_gap(self):
        current = state([card("CHILL", {}, cost=0)])
        parent, before = self.packet(current)
        parent_row = next(row for row in before.values() if not row["is_skip"])
        self.assertIn("mechanism_coverage", parent_row["missing"])
        row = next(row for row in reward.adjust(current, parent)["scores"]
                   if not row["is_skip"])
        self.assertEqual(row["reward_mechanism_features"]["frost_per_cost"], 1)
        self.assertEqual(row["reward_mechanism_features"]["conditional_effect"], 1)
        self.assertIn("future_enemy_count", row["missing"])

    def test_dynamic_orb_card_retains_explicit_future_gap(self):
        current = state([card("BARRAGE", {
            "damage": 5, "calculatedhits": 0,
            "calculationbase": 0, "calculationextra": 1,
        }, kind="Attack")])
        parent, _ = self.packet(current)
        row = next(row for row in reward.adjust(current, parent)["scores"]
                   if not row["is_skip"])
        self.assertNotIn("mechanism_coverage", row["missing"])
        self.assertIn("future_channeled_orb_count", row["missing"])
        self.assertGreater(row["reward_mechanism_features"]["orb_scaled_attack_support"], 0)

    def test_description_or_stat_drift_is_rejected(self):
        value = card("SWEEPING_BEAM", {"damage": 6, "cards": 1}, kind="Attack")
        self.assertIsNotNone(validate_card(value))
        for mutation in (
            lambda card_value: card_value.update(description="changed"),
            lambda card_value: card_value["stats"].pop("cards"),
        ):
            changed = copy.deepcopy(value)
            mutation(changed)
            with self.assertRaises(DataContractError):
                validate_card(changed)

    def test_unknown_card_remains_uncovered_and_unchanged(self):
        unknown = {
            "id": "CARD.UNSEEN_FIXTURE", "stats": {"damage": 9}, "cost": 1,
            "type": "Attack", "rarity": "Common", "description": "Unknown effect",
            "current_upgrade_level": 0,
        }
        current = state([unknown])
        parent, before = self.packet(current)
        after = reward.adjust(current, parent)
        old = next(row for row in before.values() if not row["is_skip"])
        new = next(row for row in after["scores"] if not row["is_skip"])
        self.assertEqual(new["reward_mechanism_adjustment"], 0)
        self.assertEqual(new["score"], old["score"])
        self.assertIn("mechanism_coverage", new["missing"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
