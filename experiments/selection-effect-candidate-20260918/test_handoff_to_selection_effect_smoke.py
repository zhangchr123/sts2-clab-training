import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import handoff_to_selection_effect_smoke as handoff


class SelectionEffectHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_parent_gate_requires_independent_candidate_gate(self):
        assessment = self.root / "ASSESSMENT.json"
        status = self.root / "HANDOFF_STATUS.json"
        smoke = self.root / "SMOKE_RESULT.json"
        with mock.patch.object(handoff, "PARENT_ASSESSMENT", assessment), \
             mock.patch.object(handoff, "PARENT_SMOKE_RESULT", smoke), \
             mock.patch.object(handoff, "STATUS", status):
            assessment.write_text(json.dumps({
                "passed": True,
                "evaluation_complete": True,
                "candidate_gate_passed": True,
                "deployment_authorized": False,
            }), encoding="utf-8")
            self.assertTrue(handoff.parent_gate())
            self.assertEqual(json.loads(status.read_text())["phase"], "parent_event_gate_passed")

            assessment.write_text(json.dumps({
                "passed": True,
                "evaluation_complete": True,
                "candidate_gate_passed": False,
                "deployment_authorized": False,
            }), encoding="utf-8")
            self.assertFalse(handoff.parent_gate())
            self.assertEqual(
                json.loads(status.read_text())["phase"],
                "parent_event_rejected_no_selection_smoke",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
