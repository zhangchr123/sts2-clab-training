"""Pure fake-bridge integration tests. Temporary fixtures are not rollout data."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sample_runs
from decision_data import DataContractError, read_decisions
from initial_policy import CardPrior, FEATURE_NAMES, POLICY_VERSION, InitialPolicy
from test_decision_data import metadata as fixture_metadata, solver_call
from train_ranker import VERSION as MODEL_VERSION


def fixture_state(decision, *, combat=False, hp=30, second_boss=False):
    value = {"type": "decision", "decision": decision,
             "context": {"act": 1, "ascension": 10, "room_type": "Monster" if combat else "Event",
                         "combat_in_progress": combat, "is_second_boss": second_boss},
             "player": {"hp": hp, "max_hp": 75, "gold": 99, "deck": [], "potions": [],
                        "combat_metrics": {"source": "Creature.CurrentHpChanged", "hp_lost": 30 - hp}}}
    if decision == "event_choice":
        value["options"] = [{"index": 7, "is_locked": False, "title": "Fixture option", "description": "Fixture combat"}]
    elif decision == "combat_play":
        value.update(round=1, player_turn=1, hand=[])
    return value


class FakeBridge:
    def __init__(self, scenario="defeat"):
        self.scenario = scenario
        self.requests = []
        self.closed = False

    def send(self, **request):
        self.requests.append(copy.deepcopy(request))
        if request["cmd"] == "start_run":
            return fixture_state("event_choice")
        if request["cmd"] == "solve":
            if self.scenario == "solver_error":
                return {"type": "error", "error": "Fixture unhandled solver state"}
            response = solver_call()["response"]
            response["actions"] = [{"Turn": 1, "Kind": "EndTurn"}]
            return response
        if request.get("action") == "choose_option":
            if self.scenario == "macro_error":
                return {"type": "error", "error": "Fixture event failed"}
            if self.scenario == "timeout":
                raise TimeoutError("Fixture worker did not return before its deadline")
            return fixture_state("combat_play", combat=True, second_boss=self.scenario == "victory")
        if request.get("action") == "end_turn":
            value = fixture_state("game_over", hp=10 if self.scenario == "victory" else 0,
                                  second_boss=self.scenario == "victory")
            value["victory"] = self.scenario == "victory"
            return value
        raise AssertionError("Unexpected fixture request: " + repr(request))

    def close(self):
        self.closed = True


class SampleRunsTests(unittest.TestCase):
    def test_immediate_acquire_context_is_logged_once_and_does_not_leak_to_next_selection(self):
        self._selection_source_fixture(False)

    def test_failed_selection_retains_its_source_context_in_journal(self):
        self._selection_source_fixture(True)

    def _selection_source_fixture(self, fail):
        from mechanism_facts import ENGINE_SHA256
        from selection_context import validate_selection_contexts

        class SelectionBridge:
            selected = 0

            def send(self, **request):
                if request["cmd"] == "start_run":
                    result = fixture_state("event_choice")
                    result["options"][0]["text_key"] = "OROBAS.pages.INITIAL.options.SEA_GLASS"
                    return result
                if request.get("action") == "select_cards":
                    self.selected += 1
                    if fail:
                        raise TimeoutError("Synthetic failure after acquire intent")
                    if self.selected == 2:
                        result = fixture_state("game_over", hp=0)
                        result["victory"] = False
                        return result
                result = fixture_state("card_select")
                result.update(min_select=0, max_select=1, cards=[{"index": self.selected, "id": "CARD.TEST",
                    "cost": 1, "type": "Attack", "stats": {"damage": 20}, "description": "Fixture"}])
                return result

            def close(self):
                pass

        def meta(run_id, seed, ascension, config, provenance):
            value = fixture_metadata(seed=seed, run_id=run_id, ascension=ascension)
            value["versions"]["engine"] = {"sha256": ENGINE_SHA256}
            value.update(solver_requested_config=config, provenance=provenance)
            return value

        name = "context-failure" if fail else "context-phases"
        with patch.object(sample_runs, "Bridge", return_value=SelectionBridge()), patch.object(sample_runs, "metadata", side_effect=meta):
            report = sample_runs.run_one(name, "fixture-context", epsilon=0)
        out = self.root / "outputs" / name
        records = read_decisions(out / "decisions.jsonl")
        policies = {row["decision_id"]: row for row in map(json.loads, (out / "policy.jsonl").read_text().splitlines())}
        self.assertTrue(validate_selection_contexts(records, policies))
        self.assertEqual(records[1]["execution"]["selection_context"]["purpose"], "acquire")
        self.assertEqual(policies[records[1]["decision_id"]]["scoring"]["selection_purpose"], "acquire")
        if fail:
            self.assertEqual(report["outcome"], "environment_error")
            self.assertIsNone(records[1]["execution"]["direct_action_result"])
        else:
            self.assertEqual(report["outcome"], "defeat")
            self.assertIsNone(records[2]["execution"]["selection_context"])
            self.assertIsNone(policies[records[2]["decision_id"]]["scoring"]["selection_purpose"])

    def test_exact_selection_sources_survive_localization_and_preserve_unknown(self):
        for key, (purpose, source, destination) in sample_runs.EXACT_SELECTION_PURPOSES.items():
            candidate = {"request": {"action": "choose_option"},
                         "evidence": {"text_key": key, "description": "本地化占位文本"}}
            context = sample_runs.selection_context(candidate)
            self.assertEqual(sample_runs.selection_purpose(candidate), purpose)
            self.assertEqual(context["source_model"], source)
            self.assertEqual(context["destination"], destination)
        self.assertIsNone(sample_runs.selection_context({"request": {"action": "select_cards"},
            "evidence": {"description": "upgrade a card"}}))
        self.assertIsNone(sample_runs.selection_context({"request": {"action": "choose_option"},
            "evidence": {"description": "upgrade and transform"}}))
        self.assertEqual(sample_runs.selection_purpose({"request": {"action": "choose_option"},
            "evidence": {"option_id": "SMITH", "description": "锻造"}}), "upgrade")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch.object(sample_runs, "ROOT", self.root).start()

        def metadata(run_id, seed, ascension, config, provenance):
            value = fixture_metadata(seed=seed, run_id=run_id, ascension=ascension)
            value.update(solver_requested_config=config, provenance=provenance)
            return value
        patch.object(sample_runs, "metadata", side_effect=metadata).start()

    def run_scenario(self, scenario="defeat", **kwargs):
        bridge = FakeBridge(scenario)
        with patch.object(sample_runs, "Bridge", return_value=bridge):
            report = sample_runs.run_one("fixture-" + scenario, "fixture-seed", epsilon=0, **kwargs)
        self.assertTrue(bridge.closed)
        out = self.root / "outputs" / ("fixture-" + scenario)
        records = read_decisions(out / "decisions.jsonl")
        rows = [json.loads(line) for line in (out / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
        return report, records, rows, bridge, out

    def test_natural_defeat_logs_true_result_complete_policy_and_actual_solver(self):
        report, records, rows, bridge, out = self.run_scenario()
        self.assertEqual(report["outcome"], "defeat")
        self.assertEqual(report["solver_calls"], 1)
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]["training_eligible"], records[0]["training_exclusion_reasons"])
        self.assertEqual(records[0]["next_state"]["player"]["hp"], 0)
        self.assertIsNone(records[0]["chosen_is_optimal"])
        scoring = json.loads((out / "policy.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(scoring["candidate_id"], records[0]["chosen"]["candidate_id"])
        self.assertEqual(scoring["policy_provenance"], records[0]["policy_provenance"])
        self.assertEqual(rows[0]["metadata"]["provenance"]["version"], POLICY_VERSION)
        self.assertEqual(records[0]["solver_calls"][0]["request"]["cmd"], "solve")
        self.assertEqual(bridge.requests[1]["args"], {"option_index": 7})

    def test_macro_error_records_error_response_and_never_becomes_a_loss(self):
        report, records, _, _, _ = self.run_scenario("macro_error")
        self.assertEqual(report["outcome"], "environment_error")
        self.assertEqual(report["decisions"], 0)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["next_state"]["type"], "error")
        self.assertIsNotNone(records[0]["environment_error"])
        self.assertEqual(records[0]["execution"]["direct_action_result"]["type"], "error")
        self.assertFalse(records[0]["training_eligible"])
        self.assertIsNone(records[0]["run_outcome"]["engine_victory"])

    def test_solver_error_preserves_failed_call_evidence(self):
        report, records, _, _, _ = self.run_scenario("solver_error")
        self.assertEqual(report["outcome"], "environment_error")
        self.assertEqual(records[0]["solver_calls"][0]["response"]["type"], "error")
        self.assertIn("run_environment_error", records[0]["training_exclusion_reasons"])

    def test_timeout_marks_environment_failure_without_fabricating_defeat(self):
        report, records, rows, _, _ = self.run_scenario("timeout")
        self.assertEqual(report["outcome"], "environment_error")
        self.assertEqual(rows[-1]["termination"], "timeout")
        self.assertEqual(rows[-1]["environment_error"]["kind"], "timeout")
        self.assertFalse(records[0]["training_eligible"])
        self.assertEqual(rows[-1]["unresolved_decision_id"], None)

    def test_macro_limit_stops_before_issuing_an_action(self):
        report, records, rows, bridge, _ = self.run_scenario("limit", max_decisions=0)
        self.assertEqual(report["outcome"], "environment_error")
        self.assertEqual(rows[-1]["termination"], "timeout")
        self.assertEqual(records, [])
        self.assertEqual([request["cmd"] for request in bridge.requests], ["start_run"])

    def test_a10_victory_evidence_is_from_second_boss_transition(self):
        report, records, rows, _, _ = self.run_scenario("victory")
        self.assertEqual(report["outcome"], "victory")
        self.assertTrue(records[0]["training_eligible"], records[0]["training_exclusion_reasons"])
        self.assertTrue(rows[-1]["terminal_evidence"]["second_boss_entered"])
        self.assertTrue(rows[-1]["terminal_evidence"]["second_boss_victory"])

    def test_model_policy_log_preserves_model_hash_and_actual_feature_version(self):
        model = {"format": MODEL_VERSION, "feature_policy_version": POLICY_VERSION, "mode": "prior",
                 "feature_prior_sha256": InitialPolicy().prior.source["sha256"],
                 "feature_mechanism_facts": InitialPolicy().mechanism_source,
                 "feature_names": list(FEATURE_NAMES), "means": [0.0] * len(FEATURE_NAMES),
                 "scales": [1.0] * len(FEATURE_NAMES), "weights": [0.0] * (len(FEATURE_NAMES) + 1),
                 "feature_min": [0.0] * len(FEATURE_NAMES), "feature_max": [1.0] * len(FEATURE_NAMES)}
        model_path = self.root / "fixture-model.json"
        model_path.write_text(json.dumps(model), encoding="utf-8")
        _, records, rows, _, out = self.run_scenario("model", model_path=model_path)
        provenance = records[0]["policy_provenance"]
        self.assertEqual(provenance["kind"], "model")
        self.assertEqual(len(provenance["version"]), 64)
        self.assertEqual(rows[0]["metadata"]["provenance"]["version"], provenance["version"])
        scoring = json.loads((out / "policy.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(scoring["scoring"]["model"]["sha256"], provenance["version"])


class SamplePolicyFactoryTests(unittest.TestCase):
    def setUp(self):
        from test_survival_policy import FACTS
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for context in (patch.object(sample_runs, "ROOT", self.root),
                        patch("initial_policy.verified_source", side_effect=lambda _: copy.deepcopy(FACTS)),
                        patch("initial_policy.CardPrior", side_effect=lambda _: CardPrior(None))):
            context.start()
            self.addCleanup(context.stop)
        self.settings = sample_runs.solver_config()

    def artifact(self, survival=False):
        from train_act_survival import TARGET, VERSION as SURVIVAL_FORMAT
        base = InitialPolicy()
        model = {"format": MODEL_VERSION, "feature_policy_version": POLICY_VERSION, "mode": "prior",
            "feature_prior_sha256": base.prior.source["sha256"], "feature_mechanism_facts": base.mechanism_source,
            "feature_names": list(FEATURE_NAMES), "means": [0.] * len(FEATURE_NAMES),
            "scales": [1.] * len(FEATURE_NAMES), "weights": [0.] * (len(FEATURE_NAMES) + 1),
            "feature_min": [0.] * len(FEATURE_NAMES), "feature_max": [1.] * len(FEATURE_NAMES)}
        if survival:
            model.update(format=SURVIVAL_FORMAT, mode="act1_survival", target_semantics=TARGET,
                calibrated_probability=False, counterfactual_labels=False, chosen_action_is_optimal_label=False,
                deployment_scope={"character": "Defect", "ascension": 10, "mode": "standard", "act": 1},
                frozen_followup={"solver": self.settings, "policy": base.provenance,
                    "run_conditions": {"character": "Defect", "ascension": 10, "mode": "standard"}})
        path = self.root / ("synthetic-survival.json" if survival else "synthetic-linear.json")
        path.write_text(json.dumps(model), encoding="utf-8")
        return path

    def test_rule_and_linear_construction_preserve_previous_seeded_choice_behavior(self):
        from selection_policy import SelectionPolicy
        from test_initial_policy import state
        from train_ranker import SmallValuePolicy
        for model_path in (None, self.artifact()):
            old = InitialPolicy(epsilon=.27, random_seed="factory-seed")
            if model_path:
                old = SmallValuePolicy(model_path, fallback=old, epsilon=.27, seed="factory-seed")
            old = SelectionPolicy(old, max_evaluations=19)
            new = sample_runs.build_policy("factory-seed", self.settings, ascension=4,
                epsilon=.27, model_path=model_path, selection_budget=19)
            self.assertEqual(new.provenance, old.provenance)
            for _ in range(6):
                self.assertEqual(new.choose(state()), old.choose(state()))

    def test_survival_dispatch_binds_declared_solver_scope_and_global_provenance(self):
        from selection_policy import SelectionPolicy
        from survival_policy import SurvivalPolicy, VERSION as SURVIVAL_POLICY_VERSION
        from test_survival_policy import current
        path = self.artifact(survival=True)
        new = sample_runs.build_policy("survival-seed", self.settings, model_path=path, selection_budget=17)
        self.assertIsInstance(new, SelectionPolicy)
        self.assertIsInstance(new.base, SurvivalPolicy)
        self.assertEqual(new.max_evaluations, 17)
        identity = new.provenance
        self.assertEqual(identity["id"], SURVIVAL_POLICY_VERSION)
        self.assertEqual(identity["version"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(identity["solver_requested_config"], self.settings)
        self.assertEqual(identity["epsilon"], .1)
        for act in (1, 2, 3):
            result = new.choose(current(act))
            self.assertEqual(result["scoring"]["model"]["active"], act == 1)
            self.assertEqual(result["scoring"]["feature_policy_version"], POLICY_VERSION)
            self.assertEqual({k: v for k, v in result["policy_provenance"].items() if k != "choice_count"}, identity)
        self.assertFalse((self.root / "outputs").exists())
        with self.assertRaises(DataContractError):
            sample_runs.build_policy("seed", self.settings, ascension=9, model_path=path)
        with self.assertRaises(DataContractError):
            sample_runs.build_policy("seed", {**self.settings, "first_budget_ms": 999}, model_path=path)

    def test_unknown_or_malformed_model_fails_before_creating_run_or_worker(self):
        for artifact in ({"format": "unknown-future-model"}, {}, ["not-an-object"]):
            path = self.root / "invalid.json"
            path.write_text(json.dumps(artifact), encoding="utf-8")
            with patch.object(sample_runs, "Bridge") as bridge, self.assertRaises(DataContractError):
                sample_runs.run_one("must-not-start", "seed", model_path=path)
            bridge.assert_not_called()
            self.assertFalse((self.root / "outputs").exists())

    def test_survival_factory_is_used_by_sampler_with_one_fixed_identity_across_acts(self):
        from test_survival_policy import current
        path = self.artifact(survival=True)

        class TwoActBridge:
            def __init__(self):
                self.actions = 0
                self.closed = False

            def send(self, **request):
                if request["cmd"] == "start_run":
                    return current(1)
                self.actions += 1
                if self.actions == 1:
                    return current(2)
                final = current(2)
                final.update(decision="game_over", victory=False)
                final["player"]["hp"] = 0
                return final

            def close(self):
                self.closed = True

        def meta(run_id, seed, ascension, config, provenance):
            value = fixture_metadata(seed=seed, run_id=run_id, ascension=ascension)
            value.update(solver_requested_config=config, provenance=provenance)
            return value

        bridge = TwoActBridge()
        with patch.object(sample_runs, "Bridge", return_value=bridge), patch.object(sample_runs, "metadata", side_effect=meta):
            report = sample_runs.run_one("synthetic-two-acts", "fixture-seed", model_path=path,
                                         settings=self.settings, epsilon=0)
        self.assertEqual(report["outcome"], "defeat")
        self.assertEqual(report["decisions"], 2)
        self.assertTrue(bridge.closed)
        out = self.root / "outputs" / "synthetic-two-acts"
        manifest = json.loads((out / "manifest.json").read_text())
        policies = [json.loads(line) for line in (out / "policy.jsonl").read_text().splitlines()]
        records = read_decisions(out / "decisions.jsonl")
        self.assertEqual([p["scoring"]["model"]["active"] for p in policies], [True, False])
        for policy, record in zip(policies, records):
            self.assertEqual(policy["policy_provenance"], record["policy_provenance"])
            self.assertEqual({k: v for k, v in policy["policy_provenance"].items() if k != "choice_count"},
                             manifest["provenance"])


class InteractionPolicyFactoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        for context in (patch.object(sample_runs, "ROOT", self.directory),
                        patch("initial_policy.CardPrior", side_effect=lambda _: CardPrior(None))):
            context.start()
            self.addCleanup(context.stop)

    def artifact(self):
        import test_interaction_survival_policy as fixtures
        return fixtures.InteractionPolicyTests.artifact(self)

    def test_interaction_format_dispatches_real_adapter_with_fixed_global_identity(self):
        from initial_policy import FEATURE_NAMES as BASE_NAMES
        from interaction_features import FEATURE_NAMES as INTERACTION_NAMES, VERSION as TRANSFORM_VERSION
        from interaction_survival_policy import InteractionSurvivalPolicy, VERSION
        from test_survival_policy import CONFIG, current
        path, _ = self.artifact()
        policy = sample_runs.build_policy("interaction-fixture", CONFIG, model_path=path, selection_budget=13)
        self.assertIsInstance(policy.base, InteractionSurvivalPolicy)
        self.assertEqual(policy.max_evaluations, 13)
        identity = policy.provenance
        self.assertEqual(identity["id"], VERSION)
        self.assertEqual(identity["version"], hashlib.sha256(path.read_bytes()).hexdigest())
        for act, names, version in ((1, INTERACTION_NAMES, TRANSFORM_VERSION), (2, BASE_NAMES, POLICY_VERSION)):
            picked = policy.choose(current(act))
            self.assertEqual(picked["scoring"]["feature_policy_version"], version)
            self.assertTrue(all(set(row["features"]) == set(names) for row in picked["scoring"]["scores"]))
            self.assertEqual({k: v for k, v in picked["policy_provenance"].items() if k != "choice_count"}, identity)
        self.assertFalse((self.directory / "outputs").exists())
        for kwargs in ({"ascension": 9}, {"settings": {**CONFIG, "first_budget_ms": 999}}):
            params = {"settings": CONFIG, "model_path": path, **kwargs}
            with self.subTest(kwargs=kwargs), self.assertRaises(DataContractError):
                sample_runs.build_policy("must-not-start", **params)

    def test_interaction_sampler_records_119_then_101_with_valid_source_context(self):
        from selection_context import validate_selection_contexts
        from test_survival_policy import CONFIG, current
        path, _ = self.artifact()

        class TwoActBridge:
            def __init__(self):
                self.actions = 0

            def send(self, **request):
                if request["cmd"] == "start_run":
                    return current(1)
                self.actions += 1
                value = current(2)
                if self.actions > 1:
                    value.update(decision="game_over", victory=False)
                    value["player"]["hp"] = 0
                return value

            def close(self):
                pass

        def meta(run_id, seed, ascension, config, provenance):
            value = fixture_metadata(seed=seed, run_id=run_id, ascension=ascension)
            value.update(solver_requested_config=config, provenance=provenance)
            return value

        with patch.object(sample_runs, "Bridge", return_value=TwoActBridge()), patch.object(
                sample_runs, "metadata", side_effect=meta):
            report = sample_runs.run_one("synthetic-interaction-two-acts", "fixture-seed", model_path=path,
                settings=CONFIG, epsilon=0)
        self.assertEqual(report["outcome"], "defeat")
        self.assertEqual(report["decisions"], 2)
        output = self.directory / "outputs" / report["run_id"]
        records = read_decisions(output / "decisions.jsonl")
        policies = [json.loads(line) for line in (output / "policy.jsonl").read_text().splitlines()]
        self.assertEqual([len(p["scoring"]["scores"][0]["features"]) for p in policies], [119, 101])
        self.assertEqual([p["scoring"]["model"]["active"] for p in policies], [True, False])
        self.assertTrue(validate_selection_contexts(records, {p["decision_id"]: p for p in policies}))


if __name__ == "__main__":
    unittest.main()
