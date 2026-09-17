import unittest

from replay_selection_effect_candidate import compare_decision, summary


def candidate(candidate_id, damage_gain):
    return {
        "candidate_id": candidate_id,
        "request": {"cmd": "action", "action": "select_cards", "args": {"indices": candidate_id[-1]}},
        "evidence": {
            "cards": [{
                "id": "CARD." + candidate_id.upper(),
                "cost": 1,
                "stats": {"damage": 5},
                "keywords": None,
                "upgrade_preview_status": "available",
                "upgrade_preview_basis": "canonical_plus_upgrade_level",
                "upgrade_preview_instance_modifiers_copied": False,
                "after_upgrade": {
                    "cost": 1,
                    "stats": {"damage": 5 + damage_gain},
                    "added_keywords": None,
                    "removed_keywords": None,
                },
            }]
        },
    }


class SelectionEffectReplayTests(unittest.TestCase):
    def test_fixed_adjustment_changes_tied_greedy_set_with_exact_additivity(self):
        candidates = {"c0": candidate("c0", 3), "c1": candidate("c1", 10)}
        scoring = {
            "selection_purpose": "upgrade",
            "scores": [
                {"candidate_id": key, "request": value["request"], "score": 0.0}
                for key, value in candidates.items()
            ],
        }
        comparison = compare_decision({"candidate_id": "c1"}, scoring, candidates)
        self.assertEqual(comparison["old_greedy"], ["c0", "c1"])
        self.assertEqual(comparison["new_greedy"], ["c1"])
        self.assertTrue(comparison["greedy_set_changed"])
        self.assertTrue(all(row["exact_additivity"] for row in comparison["rows"]))

        report = summary([{"comparison": comparison}])
        self.assertEqual(report["decisions"], 1)
        self.assertEqual(report["exact_additivity_decisions"], 1)
        self.assertEqual(report["old_uniform"], 1)
        self.assertEqual(report["new_uniform"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
