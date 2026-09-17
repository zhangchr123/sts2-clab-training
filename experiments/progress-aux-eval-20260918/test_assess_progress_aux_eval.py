import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SOURCE = Path(__file__).with_name("assess_progress_aux_eval.py")
SPEC = importlib.util.spec_from_file_location("assessor", SOURCE)
assessor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assessor)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def evidence(path):
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


class AssessmentTests(unittest.TestCase):
    def fixture(self, root):
        base, solver = root / "eval", root / "solver"
        run = base / "run"
        run.mkdir(parents=True)
        model_control, model_candidate, frozen = root / "control.json", root / "candidate.json", root / "frozen.py"
        model_control.write_text("control", encoding="utf-8")
        model_candidate.write_text("candidate", encoding="utf-8")
        frozen.write_text("frozen", encoding="utf-8")
        models = {"control": evidence(model_control), "candidate": evidence(model_candidate)}
        jobs, rows = [], []
        for pair in range(assessor.PAIRS):
            for arm in ("control", "candidate"):
                label = f"pair-{pair:02d}-{arm}"
                seed = f"seed-{pair:02d}"
                job = {"label": label, "seed": seed, "pair": pair, "arm": arm, "model": models[arm]}
                jobs.append(job)
                raw = solver / "outputs" / label / "trace.jsonl"
                raw.parent.mkdir(parents=True)
                raw.write_text(label, encoding="utf-8")
                success = pair < 5 and arm == "candidate"
                row = {
                    "run_id": label, "seed": seed, "pair": pair, "arm": arm,
                    "report": {"seed": seed, "outcome": "defeat"},
                    "goal": {"natural_goal_success": success}, "issues": [],
                    "policy_bound": True, "integration_passed": True,
                    "invalid_failure_retained": False, "goal_success": success,
                    "evaluation_only": True, "refit_or_selection_eligible": False,
                }
                write(run / f"{label}-audit.json", row)
                rows.append(row)
        protocol = {
            "planned_pairs": assessor.PAIRS, "planned_games": assessor.COUNT, "parallel_workers": 1,
            "automatic_retry": False, "automatic_deployment": False,
            "no_refit_on_evaluation": True, "no_sample_extension": True,
            "jobs": jobs, "models": models, "frozen_sources": [evidence(frozen)],
        }
        write(run / "PROTOCOL.json", protocol)
        result = assessor.comparison(rows)
        write(run / "RESULT.json", result)
        raw_sources = [evidence(path) for job in jobs
                       for path in (solver / "outputs" / job["label"]).rglob("*") if path.is_file()]
        closure = {
            "passed": True, "games": assessor.COUNT, "protocol": evidence(run / "PROTOCOL.json"),
            "result": evidence(run / "RESULT.json"), "raw_sources": raw_sources,
            "invalid_failures_retained": 0, "raw_originals_retained": True,
            "automatic_deployment": False,
        }
        write(run / "SOURCE_CLOSURE.json", closure)
        return base, solver

    def test_independent_complete_verification(self):
        with tempfile.TemporaryDirectory() as name:
            base, solver = self.fixture(Path(name))
            result = assessor.verify_complete(base, solver)
            self.assertTrue(result["passed"])
            self.assertTrue(result["candidate_gate_passed"])
            self.assertEqual(result["audits_verified"], 120)
            self.assertFalse(result["deployment_authorized"])

    def test_raw_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            base, solver = self.fixture(Path(name))
            next((solver / "outputs").rglob("trace.jsonl")).write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Raw source changed"):
                assessor.verify_complete(base, solver)

    def test_exact_gate_rejects_four_candidate_only_wins(self):
        rows = []
        for pair in range(assessor.PAIRS):
            for arm in ("control", "candidate"):
                rows.append({"pair": pair, "arm": arm, "integration_passed": True,
                             "goal_success": pair < 4 and arm == "candidate",
                             "report": {"outcome": "defeat"}})
        result = assessor.comparison(rows)
        self.assertEqual(result["candidate_only_success"], 4)
        self.assertEqual(result["one_sided_paired_p"], 0.0625)
        self.assertFalse(result["improvement_gate_passed"])

    def test_zip_archive_uses_relative_manifest_path(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            base, solver = self.fixture(root)
            assessor.RUN = base / "run"
            assessor.ASSESSMENT = base / "assessment.json"
            assessment = assessor.verify_complete(base, solver)
            write(assessor.ASSESSMENT, assessment)
            staging = base / "staging"
            assessor.copy_evidence(staging, assessment, solver)
            index = json.loads((staging / "ARCHIVE_INDEX.json").read_text())
            manifest = json.loads((staging / "RESULTS_MANIFEST.json").read_text())
            self.assertTrue(index[0]["archive"]["path"].startswith("games/"))
            self.assertTrue(all(not Path(item["path"]).is_absolute() for item in manifest["files"]))


if __name__ == "__main__":
    unittest.main()
