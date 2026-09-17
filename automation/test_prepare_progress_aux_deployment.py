import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SOURCE = Path(__file__).with_name("prepare_progress_aux_deployment.py")
SPEC = importlib.util.spec_from_file_location("deploy_tool", SOURCE)
d = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(d)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def ev(path):
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


class DeploymentToolTests(unittest.TestCase):
    def fixture(self, root, gate=True):
        eval_root, goal = root / "eval", root / "goal"
        run, deploy = eval_root / "run", eval_root / "deployment"
        run.mkdir(parents=True); goal.mkdir()
        control, candidate = root / "control.json", eval_root / "output" / "candidate-runtime-model.json"
        write(control, {"name": "control"})
        write(candidate, {"automatic_deployment": False, "first_boss_success_verified": False})
        protocol = {"models": {"control": ev(control), "candidate": ev(candidate)}}
        write(run / "PROTOCOL.json", protocol)
        result = {
            "control": {"first_boss_successes": 1}, "candidate": {"first_boss_successes": 6},
            "candidate_only_success": 5, "control_only_success": 0, "one_sided_paired_p": 0.03125,
            "improvement_gate_passed": gate, "automatic_deployment": False,
            "evaluation_used_for_refit": False,
        }
        write(run / "RESULT.json", result)
        write(run / "SOURCE_CLOSURE.json", {"passed": True, "automatic_deployment": False})
        assessment = {
            "passed": True, "evaluation_complete": True, "games": 120, "pairs": 60,
            "audits_verified": 120, "candidate_gate_passed": gate, "deployment_authorized": False,
            "result": ev(run / "RESULT.json"), "protocol": ev(run / "PROTOCOL.json"),
            "source_closure": ev(run / "SOURCE_CLOSURE.json"),
        }
        assessment_path = eval_root / "assessment" / "ASSESSMENT.json"
        write(assessment_path, assessment)
        template = goal / "runner_template.py"
        template.write_text("import pathlib\nBASE_CHECKS=pathlib.Path('/tmp')\n" + d.BASELINE_LITERAL + "\n", encoding="utf-8")
        return eval_root, goal, run, deploy, assessment_path, candidate, template

    def test_failed_gate_cannot_prepare(self):
        with tempfile.TemporaryDirectory() as name:
            args = self.fixture(Path(name), gate=False)
            with self.assertRaisesRegex(ValueError, "natural gate did not pass"):
                d.prepare(args[4], args[2], args[5], args[6], args[3])

    def test_prepare_activate_and_rollback_require_exact_digests(self):
        with tempfile.TemporaryDirectory() as name:
            eval_root, goal, run, deploy, assessment, candidate, template = self.fixture(Path(name))
            original = template.read_bytes()
            plan_path, plan = d.prepare(assessment, run, candidate, template, deploy)
            self.assertEqual(template.read_bytes(), original)
            self.assertFalse(plan["automatic_deployment"])
            with self.assertRaisesRegex(ValueError, "Exact deployment plan digest"):
                d.activate(plan_path, "wrong", template, lambda: True, lambda: [])
            plan_digest = ev(plan_path)["sha256"]
            activation_path, activation = d.activate(plan_path, plan_digest, template,
                                                     lambda: True, lambda: [])
            self.assertIn(d.CANDIDATE_LITERAL, template.read_text())
            self.assertFalse(activation["automatic_deployment"])
            with self.assertRaisesRegex(ValueError, "Exact activation digest"):
                d.rollback(activation_path, "wrong", template, lambda: True, lambda: [])
            d.rollback(activation_path, ev(activation_path)["sha256"], template,
                       lambda: True, lambda: [])
            self.assertEqual(template.read_bytes(), original)

    def test_activation_refuses_live_goal_or_runner(self):
        with tempfile.TemporaryDirectory() as name:
            eval_root, goal, run, deploy, assessment, candidate, template = self.fixture(Path(name))
            plan_path, _ = d.prepare(assessment, run, candidate, template, deploy)
            digest = ev(plan_path)["sha256"]
            with self.assertRaisesRegex(ValueError, "Goal service must be inactive"):
                d.activate(plan_path, digest, template, lambda: False, lambda: [])
            with self.assertRaisesRegex(ValueError, "live sampling batch"):
                d.activate(plan_path, digest, template, lambda: True, lambda: [123])


if __name__ == "__main__":
    unittest.main(verbosity=2)
