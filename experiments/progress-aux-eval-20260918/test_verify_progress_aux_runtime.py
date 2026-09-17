import unittest

from verify_progress_aux_runtime import expected_delta


class RuntimeReadbackTests(unittest.TestCase):
    def test_expected_delta_uses_each_parameter_once(self):
        features = {"a": 2.0, "b": -3.0}
        control = {"a": 1.0, "b": 4.0}
        candidate = {"a": 1.5, "b": 2.0}
        self.assertEqual(expected_delta(features, control, candidate, ["a", "b"]), 7.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
