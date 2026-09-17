import unittest

import migrate_progress_aux_candidate as m


def model(names, values):
    return {"parameter_names": names, "parameters": dict(zip(names, values))}


class MigrationTests(unittest.TestCase):
    def test_only_prefix_changes(self):
        old = [f"p{i}" for i in range(438)]
        roles = [f"r{i}" for i in range(33)]
        baseline = model(old, [0.0] * 438)
        current = model(old + roles, [0.0] * 471)
        learned = model(old, [1.0] + [0.0] * 437)
        candidate, old_names, role_names, changed = m.migrate(
            current, baseline, learned, {"current": {}, "baseline": {}, "learned": {}}
        )
        self.assertEqual(old_names, old)
        self.assertEqual(role_names, roles)
        self.assertEqual(changed, ["p0"])
        self.assertEqual([candidate["parameters"][r] for r in roles], [0.0] * 33)

    def test_rejects_different_cloud_prefix(self):
        old = [f"p{i}" for i in range(438)]
        roles = [f"r{i}" for i in range(33)]
        baseline = model(old, [0.0] * 438)
        current = model(old + roles, [0.25] + [0.0] * 470)
        learned = model(old, [1.0] + [0.0] * 437)
        with self.assertRaisesRegex(ValueError, "not the frozen fit baseline"):
            m.migrate(current, baseline, learned, {"current": {}, "baseline": {}, "learned": {}})

    def test_rejects_nonfinite_candidate(self):
        old = [f"p{i}" for i in range(438)]
        roles = [f"r{i}" for i in range(33)]
        baseline = model(old, [0.0] * 438)
        current = model(old + roles, [0.0] * 471)
        learned = model(old, [float("nan")] + [0.0] * 437)
        with self.assertRaisesRegex(ValueError, "Non-finite"):
            m.migrate(current, baseline, learned, {"current": {}, "baseline": {}, "learned": {}})


if __name__ == "__main__":
    unittest.main(verbosity=2)
