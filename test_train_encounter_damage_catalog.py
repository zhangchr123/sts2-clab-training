import unittest

import train_encounter_damage_catalog as damage


class EncounterDamageCatalogTests(unittest.TestCase):
    def rows(self):
        rows = []
        for act in (1, 2, 3):
            for node_index, node_type in enumerate(damage.NODE_TYPES):
                for index in range(6):
                    rows.append({
                        "act": act,
                        "node_type": node_type,
                        "gross_loss_ratio": 0.02 * act + 0.05 * node_index + 0.01 * index,
                    })
        return rows

    def test_catalog_covers_every_public_act_and_known_fight_type(self):
        table = damage.fit(self.rows(), smoothing=20.0)
        self.assertEqual(len(table), 9)
        for act in (1, 2, 3):
            for node_type in damage.NODE_TYPES:
                cell = table[f"act{act}:{node_type}"]
                values = list(cell["quantiles"].values())
                self.assertEqual(values, sorted(values))
                self.assertEqual(cell["support"], 6)

    def test_unseen_cell_uses_declared_hierarchy_without_test_rows(self):
        rows = [row for row in self.rows()
                if not (row["act"] == 3 and row["node_type"] == "Boss")]
        table = damage.fit(rows, smoothing=20.0)
        cell = table["act3:Boss"]
        self.assertEqual(cell["support"], 0)
        self.assertEqual(cell["cell_weight"], 0.0)
        self.assertTrue(all(value >= 0 for value in cell["quantiles"].values()))

    def test_pinball_metrics_use_only_supplied_holdout_rows(self):
        rows = self.rows()
        table = damage.fit(rows[:-5], smoothing=10.0)
        metrics = damage.evaluate(rows[-5:], table)
        self.assertEqual(metrics["rows"], 5)
        self.assertEqual(set(metrics["pinball"]), {"0.5", "0.75", "0.9"})
        self.assertGreaterEqual(metrics["mean_pinball"], 0)

    def test_baselines_ignore_disallowed_dimensions(self):
        rows = self.rows()
        global_table = damage.fit_baseline(rows, "global")
        act_table = damage.fit_baseline(rows, "act")
        node_table = damage.fit_baseline(rows, "node_type")
        self.assertEqual(global_table["act1:Monster"]["quantiles"],
                         global_table["act3:Boss"]["quantiles"])
        self.assertEqual(act_table["act1:Monster"]["quantiles"],
                         act_table["act1:Boss"]["quantiles"])
        self.assertEqual(node_table["act1:Elite"]["quantiles"],
                         node_table["act3:Elite"]["quantiles"])

    def test_act3_first_boss_chain_is_a_known_boss_resolution(self):
        state = {"context": {
            "act": 3, "floor": 14,
            "boss": {"id": "QUEEN_BOSS"},
            "second_boss": "AEONGLASS_BOSS",
        }}
        next_state = {"decision": "map_select", "context": {
            "act": 3, "floor": 15, "room_type": "Map",
        }}
        self.assertEqual(
            damage.known_room_resolution("Boss", state, next_state),
            "act3_first_boss_to_second_boss_map",
        )
        next_state["context"]["floor"] = 14
        self.assertIsNone(damage.known_room_resolution("Boss", state, next_state))

    def test_cell_metrics_keep_act3_boss_separate(self):
        rows = self.rows()
        table = damage.fit(rows, smoothing=0.0)
        grouped = damage.evaluate_by_cell(rows, table)
        self.assertEqual(set(grouped), {
            f"act{act}:{node_type}" for act in (1, 2, 3)
            for node_type in damage.NODE_TYPES
        })
        self.assertEqual(grouped["act3:Boss"]["rows"], 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
