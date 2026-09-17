"""Reconcile an existing sampler batch without running games or changing its data.

Usage: python audit_batch.py outputs/BATCH [--expected-runs N] [--output NEW.json]
The output is always a new file. Existing failures retain their original outcome.
An audit verifies evidence consistency; it cannot establish a blinded evaluation.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

from decision_data import read_decisions, split_by_seed, state_hash
from selection_policy import validate_selection_evidence
from selection_context import FEATURE_VERSION, direct_action_evidence, validate_selection_contexts
from train_ranker import validate_mechanism_facts, validate_model, predict
from replay_evidence import solver_projection, validate_replay_evidence
from initial_policy import FEATURE_NAMES as BASE_FEATURE_NAMES, InitialPolicy
from interaction_features import FEATURE_NAMES as INTERACTION_FEATURE_NAMES, VERSION as INTERACTION_VERSION
from train_interaction_survival import FEATURE_SOURCE_FILES, VERSION as INTERACTION_MODEL, MODE as INTERACTION_MODE

ROOT = Path(__file__).resolve().parent
IMPLICIT = "ordered_selection_implicit_v1"
SURVIVAL_MODEL = "defect-act1-survival-ridge-v1"
SURVIVAL_POLICY = "act1-survival-with-v3-fallback-v1"
INTERACTION_POLICY = "act1-interaction-survival-with-v3-fallback-v1"
PREFIX_MODEL = "paired-prefix-next-combat-hp-ridge-v1"
PREFIX_POLICY = "first-ordinary-act1-reward-prefix-health-with-v3-fallback-v1"
SURVIVAL_FORMATS = {SURVIVAL_MODEL: (SURVIVAL_POLICY, "act1_survival"),
                    INTERACTION_MODEL: (INTERACTION_POLICY, INTERACTION_MODE)}


def _equal(a, b):
    """Canonical JSON equality preserves the bool/integer distinction."""
    return state_hash(a) == state_hash(b)


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _candidate_count(record):
    candidates = record["candidate_set"]
    return candidates.get("candidate_count", len(candidates["candidates"]))


def _group_count(records):
    """Count connected seed/lineage/run components, not merely distinct seeds."""
    parent = {}

    def find(key):
        parent.setdefault(key, key)
        if parent[key] != key:
            parent[key] = find(parent[key])
        return parent[key]

    for row in records:
        meta = row["metadata"]
        keys = ["seed:" + meta["seed"], "run:" + meta["run_id"]]
        if meta.get("lineage_root_seed"):
            keys.append("seed:" + meta["lineage_root_seed"])
        for key in keys[1:]:
            parent[find(key)] = find(keys[0])
    return len({find(key) for key in parent})


class _Audit:
    def __init__(self, batch):
        self.batch = batch
        self.issues = []
        self.checks = Counter()
        self.evidence = {}
        self.feature_schemas = {}
        self.models = {}
        self.settings = Counter()
        self.selection_precision = Counter()
        self.evaluated = {}

    def check(self, ok, name, run_id=None, detail=None):
        self.checks[name] += 1
        if not ok:
            self.issues.append({"check": name, "run_id": run_id, "detail": detail})
        return bool(ok)

    def source(self, path):
        path = Path(path).resolve()
        if str(path) not in self.evidence:
            data = path.read_bytes()
            self.evidence[str(path)] = {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(),
                                        "bytes": len(data)}
        return self.evidence[str(path)]

    def read(self, path, *, lines=False):
        self.source(path)
        text = Path(path).read_text(encoding="utf-8-sig")
        def invalid(value):
            raise ValueError("Non-finite JSON constant: " + value)
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError("Duplicate JSON key: " + key)
                result[key] = value
            return result
        def decode(value):
            return json.loads(value, parse_constant=invalid, object_pairs_hook=pairs)
        return [decode(line) for line in text.splitlines() if line.strip()] if lines else decode(text)

    @staticmethod
    def resolve_reference(value):
        path = Path(value)
        # Sampler/model paths are written relative to the bridge project.
        return path if path.is_absolute() else ROOT / path

    def verify_source(self, claimed, run_id, check_name):
        path = self.resolve_reference(claimed["path"])
        actual = self.source(path)
        self.check(claimed.get("sha256") == actual["sha256"], check_name, run_id, str(path))
        if "bytes" in claimed:
            self.check(type(claimed["bytes"]) is int and claimed["bytes"] == actual["bytes"],
                       check_name + "_bytes", run_id, str(path))
        return actual

    def model(self, manifest, run_id):
        if manifest["provenance"]["kind"] != "model":
            return None
        path = self.resolve_reference(manifest["sampling"]["model_path"])
        model = self.read(path)
        actual = self.source(path)
        provenance = manifest["provenance"]
        self.check(actual["sha256"] == provenance["version"], "model_artifact_hash", run_id)
        if model["format"] == PREFIX_MODEL:
            from prefix_health_policy import PrefixHealthPolicy
            from selection_policy import SelectionPolicy
            from train_prefix_ranker import FEATURE_SOURCES as PREFIX_FEATURE_SOURCES
            protocol_path = self.resolve_reference(provenance["source_protocol"]["path"])
            registered = PrefixHealthPolicy(path, protocol_path=protocol_path,
                solver_config=manifest["solver_requested_config"], epsilon=manifest["sampling"]["epsilon"],
                seed=manifest["seed"], character=manifest["character"], ascension=manifest["ascension"],
                mode=manifest["mode"])
            expected = SelectionPolicy(registered, max_evaluations=manifest["sampling"].get("selection_budget", 256))
            self.check(_equal(expected.provenance, provenance), "prefix_registered_policy_identity", run_id)
            for claimed in (registered.source, provenance["source_protocol"], provenance["registered_fit_source"],
                            model["training_audit"], model["prior_source"], *model["feature_sources"].values()):
                self.verify_source(claimed, run_id, "prefix_registered_source_hash")
            observed = manifest["versions"].get("sources", {})
            for name in PREFIX_FEATURE_SOURCES:
                self.check(all(_equal(model["feature_sources"][name].get(key), observed.get(name, {}).get(key))
                               for key in ("sha256", "bytes")), "prefix_manifest_feature_source", run_id, name)
            self.check(manifest["versions"]["engine"]["sha256"] == model["mechanism_facts"]["engine_sha256"],
                       "prefix_mechanism_engine_identity", run_id)
            self.models[str(path.resolve())] = {**actual, "format": PREFIX_MODEL,
                "feature_policy_version": INTERACTION_VERSION, "base_feature_policy_version": FEATURE_VERSION,
                "feature_prior_sha256": model["prior_source"]["sha256"],
                "target_semantics": model["target_semantics"], "source_protocol": model["source_protocol"],
                "registered_fit_source": provenance["registered_fit_source"],
                "feature_sources": model["feature_sources"], "calibrated_probability": False}
            return model
        expected_id = SURVIVAL_FORMATS.get(model["format"], (model["format"], None))[0]
        self.check(expected_id == provenance["id"], "model_format_identity", run_id)
        if model["format"] in SURVIVAL_FORMATS:
            self.check(model["mode"] == SURVIVAL_FORMATS[model["format"]][1]
                       and model["target_semantics"] == "observed_act2_entry_under_frozen_followup_policy"
                       and _equal(model["deployment_scope"], {"character": "Defect", "ascension": 10, "mode": "standard", "act": 1}),
                       "survival_model_target_and_scope", run_id)
            self.check(_equal(model["frozen_followup"]["solver"], manifest["solver_requested_config"])
                       and _equal(provenance["solver_requested_config"], manifest["solver_requested_config"]),
                       "survival_model_solver_binding", run_id)
            self.check(provenance["training_followup_sha256"] == state_hash(model["frozen_followup"]),
                       "survival_model_training_followup_hash", run_id)
        if model["format"] == INTERACTION_MODEL:
            validate_model(model)
            self.check(model["feature_policy_version"] == INTERACTION_VERSION
                       and model.get("base_feature_policy_version") == FEATURE_VERSION
                       and model["feature_names"] == list(INTERACTION_FEATURE_NAMES),
                       "interaction_model_feature_schema", run_id)
            self.check(provenance.get("active_feature_policy_version") == INTERACTION_VERSION
                       and provenance.get("base_feature_policy_version") == FEATURE_VERSION
                       and _equal(provenance.get("feature_transform"), model.get("feature_transform")),
                       "interaction_model_transform_identity", run_id)
            sources = model.get("feature_transform_sources", {})
            self.check(set(sources) == set(FEATURE_SOURCE_FILES)
                       and _equal(sources, provenance.get("feature_transform_sources")),
                       "interaction_model_feature_sources", run_id)
            observed = manifest["versions"].get("sources", {})
            for name in FEATURE_SOURCE_FILES:
                claimed, actual_source = sources.get(name, {}), observed.get(name, {})
                self.check(isinstance(claimed.get("sha256"), str) and len(claimed["sha256"]) == 64
                           and type(claimed.get("bytes")) is int and claimed["bytes"] > 0
                           and all(_equal(claimed.get(key), actual_source.get(key)) for key in ("sha256", "bytes")),
                           "interaction_model_manifest_feature_source", run_id, name)
        self.check(isinstance(model["feature_policy_version"], str) and bool(model["feature_policy_version"]),
                   "model_feature_version_declared", run_id)
        self.check(model["feature_prior_sha256"] == provenance["prior_sha256"], "model_prior_hash", run_id)
        self.check(isinstance(model["feature_names"], list) and bool(model["feature_names"])
                   and all(isinstance(k, str) for k in model["feature_names"])
                   and len(set(model["feature_names"])) == len(model["feature_names"]), "model_feature_names", run_id)
        self.check(model.get("calibrated_probability") is False
                   and model.get("chosen_action_is_optimal_label") is False
                   and model.get("counterfactual_labels") is False, "model_label_semantics", run_id)
        sources = model.get("sources")
        if self.check(isinstance(sources, list) and bool(sources), "model_sources_present", run_id):
            for claimed in sources:
                self.verify_source(claimed, run_id, "model_training_source_hash")
        self.models[str(path.resolve())] = {**actual, "format": model["format"], "mode": model["mode"],
            "feature_policy_version": model["feature_policy_version"],
            "feature_prior_sha256": model["feature_prior_sha256"], "sources": sources}
        return model

    def policy(self, record, picked, manifest, model, position):
        rid = record["run_id"]
        scoring = picked["scoring"]
        prefix_model = model is not None and model["format"] == PREFIX_MODEL
        provenance = picked["policy_provenance"]
        candidates = record["candidate_set"]
        rows = scoring["scores"]
        self.check(_equal(picked["request"], record["chosen"]["request"])
                   and picked["candidate_id"] == record["chosen"]["candidate_id"], "chosen_policy_matches_journal", rid)
        self.check(_equal(provenance, record["policy_provenance"]), "policy_provenance_matches_journal", rid)
        identity = {key: value for key, value in provenance.items() if key != "choice_count"}
        self.check(_equal(identity, manifest["provenance"]), "policy_identity_matches_manifest", rid)
        self.check(type(provenance.get("choice_count")) is int and provenance["choice_count"] == position,
                   "policy_choice_sequence", rid)
        self.check(scoring["state_hash"] == state_hash(record["state"]), "scoring_state_hash", rid)
        self.check(scoring["candidate_source"] == candidates["source"], "scoring_candidate_source", rid)
        self.check(scoring["calibrated"] is False and record["chosen_is_optimal"] is None,
                   "observed_action_not_optimal_or_probability_label", rid)
        count = _candidate_count(record)
        if candidates.get("representation") == IMPLICIT:
            try:
                validity = validate_selection_evidence(record["state"], candidates, picked)
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                self.check(False, "implicit_selection_evidence", rid, str(exc))
            else:
                valid = isinstance(validity, dict) and validity.get("valid") is True
                self.check(valid, "implicit_selection_evidence", rid)
                if valid:
                    self.selection_precision[json.dumps(validity, sort_keys=True)] += 1
        else:
            wire = {c["candidate_id"]: c for c in candidates["candidates"]}
            self.check(len(rows) == len(wire) and {r["candidate_id"] for r in rows} == set(wire),
                       "explicit_every_candidate_scored_once", rid)
            self.check(all(r["candidate_id"] in wire and _equal(r["request"], wire[r["candidate_id"]]["request"])
                           and r["is_skip"] is wire[r["candidate_id"]]["is_skip"] for r in rows),
                       "explicit_scored_action_identity", rid)
            for key, expected in (("candidate_count", count), ("evaluated_candidate_count", len(rows)),
                                  ("evaluated_candidates_complete", True)):
                if key in scoring:
                    self.check(_equal(scoring[key], expected), "explicit_" + key, rid)
        version = scoring.get("feature_policy_version", scoring["policy_version"])
        if version in (FEATURE_VERSION, INTERACTION_VERSION):
            facts = validate_mechanism_facts(scoring.get("mechanism_facts"))
            self.check(_equal(facts, provenance.get("mechanism_facts")), "scoring_mechanism_facts", rid)
            self.check(isinstance(manifest["versions"]["engine"], dict)
                       and manifest["versions"]["engine"].get("sha256") == facts["engine_sha256"],
                       "mechanism_engine_matches_manifest", rid)
            if model is not None:
                self.check(_equal(facts, model.get("mechanism_facts" if prefix_model else "feature_mechanism_facts")),
                           "model_mechanism_facts", rid)
        self.check(scoring["policy_id"] == provenance["id"], "scoring_policy_id", rid)
        if model is None:
            self.check(scoring["policy_version"] == provenance["version"], "scoring_rule_version", rid)
        elif prefix_model:
            # The shared whole-run validator independently recomputes whether
            # this is the first eligible reward; an isolated Act1 test is insufficient.
            active = scoring.get("model", {}).get("active")
            self.check(type(active) is bool and version == (INTERACTION_VERSION if active else FEATURE_VERSION)
                       and scoring.get("effective_scorer") == (PREFIX_MODEL if active else FEATURE_VERSION),
                       "prefix_scoring_feature_scope", rid)
            self.check(scoring["policy_version"] == PREFIX_POLICY
                       and scoring["model"]["sha256"] == provenance["version"]
                       and scoring["model"].get("calibrated_probability") is False
                       and scoring["model"].get("A10_victory_model") is False,
                       "prefix_scoring_model_identity", rid)
        else:
            active = record["state"].get("context", {}).get("act") == 1
            expected_version = (FEATURE_VERSION if model["format"] == INTERACTION_MODEL and not active
                                else model["feature_policy_version"])
            self.check(version == expected_version, "scoring_model_feature_version", rid)
            self.check(scoring["model"]["sha256"] == provenance["version"]
                       and scoring["model"]["mode"] == model["mode"]
                       and scoring["model"]["calibrated_probability"] is False, "scoring_model_identity", rid)
            if model["format"] in SURVIVAL_FORMATS:
                act = record["state"].get("context", {}).get("act")
                active = act == 1
                self.check(type(act) is int and act in (1, 2, 3)
                           and scoring["model"].get("active") is active
                           and scoring.get("effective_scorer") == (model["format"] if active else FEATURE_VERSION),
                           "survival_model_actual_scope", rid)
                semantics = ("uncalibrated_Act1_interaction_survival_proxy_not_A10_win_probability"
                             if model["format"] == INTERACTION_MODEL else
                             "uncalibrated_Act1_survival_proxy_score_not_A10_win_probability")
                self.check(not active or scoring.get("score_semantics") == semantics,
                           "survival_proxy_not_victory_probability", rid)
            if model["format"] == INTERACTION_MODEL and active:
                self.check(scoring.get("base_feature_policy_version") == FEATURE_VERSION
                           and scoring.get("interaction_scores_applied") is True
                           and _equal(scoring.get("interaction_feature_source"), model["feature_transform"]),
                           "scoring_interaction_transform_identity", rid)
        prior = scoring["prior_source"]
        self.check(prior["sha256"] == provenance.get("prior_sha256"), "scoring_prior_hash", rid)
        if prior["sha256"] is not None:
            self.verify_source(prior, rid, "prior_csv_source_hash")
        else:
            self.check("source_file" in prior.get("missing", []), "missing_prior_is_explicit", rid)
        base_rows = None
        if model and model["format"] == INTERACTION_MODEL:
            base_packet = InitialPolicy(prior_path=prior.get("path")).score_requests(
                record["state"], [row["request"] for row in rows],
                selection_purpose=scoring.get("selection_purpose"))
            base_rows = {row["candidate_id"]: row for row in base_packet["scores"]}
        expected_skip = None
        if base_rows is not None:
            skip = next((row for row in rows if row["is_skip"]), None)
            if skip is not None:
                expected_skip = (predict(model, skip["features"]) if active else base_rows[skip["candidate_id"]]["score"])
        for row in rows:
            features = row["features"]
            self.check(isinstance(features, dict) and bool(features) and all(_finite(v) for v in features.values()),
                       "finite_numeric_features", rid)
            names = sorted(features)
            expected_names = (sorted(BASE_FEATURE_NAMES) if model and model["format"] in (INTERACTION_MODEL, PREFIX_MODEL) and not active
                              else sorted(model["feature_names"]) if model else self.feature_schemas.setdefault(version, names))
            self.check(names == expected_names, "feature_schema_consistency", rid, version)
            self.check(_finite(row["score"]), "finite_relative_score", rid)
            if base_rows is not None:
                base_row = base_rows[row["candidate_id"]]
                self.check(_equal({key: features.get(key) for key in BASE_FEATURE_NAMES}, base_row["features"]),
                           "interaction_base_features_recomputed", rid)
                if names == expected_names:
                    expected_score = predict(model, features) if active else base_row["score"]
                    self.check(_equal(row["score"], expected_score), "interaction_actual_model_or_fallback_score", rid)
                    self.check(_equal(row.get("delta_from_skip"), None if expected_skip is None else expected_score - expected_skip),
                               "interaction_actual_delta_from_skip", rid)
                    self.check(not active or _equal(row.get("rule_score"), base_row["score"]),
                               "interaction_recorded_rule_score", rid)
        exploration = picked["exploration"]
        epsilon = exploration["epsilon"]
        self.check(_finite(epsilon) and 0 <= epsilon <= 1
                   and _equal(epsilon, provenance["epsilon"])
                   and _equal(epsilon, manifest["sampling"]["epsilon"]), "exploration_epsilon_consistency", rid)
        self.check(_finite(exploration["chosen_probability"]) and 0 < exploration["chosen_probability"] <= 1
                   and type(exploration["explored"]) is bool, "exploration_probability_recorded", rid)
        self.check(_equal(exploration.get("choice_count"), provenance["choice_count"])
                   and _equal(exploration.get("random_seed"), provenance.get("random_seed")), "exploration_rng_identity", rid)
        execution = record.get("execution", {})
        if record.get("environment_error") is None:
            self.check(_equal(execution.get("exploration"), exploration)
                       and _equal(execution.get("selection_purpose"), scoring.get("selection_purpose")),
                       "policy_execution_evidence", rid)
        self.evaluated[record["decision_id"]] = len(rows)
        return len(rows)

    def run(self, report):
        rid = report["run_id"]
        if not isinstance(rid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", rid):
            raise ValueError("Unsafe or missing run_id")
        out = self.batch.parent / rid
        run_report, status, manifest, final_state = [self.read(out / name) for name in
            ("report.json", "status.json", "manifest.json", "state.json")]
        journal, policies, traces = [self.read(out / name, lines=True) for name in
            ("decisions.jsonl", "policy.jsonl", "trace.jsonl")]
        # This reconstructs each recorded adapter version/threshold and chosen
        # action. Never compare historical logs with today's default enumerator.
        records = read_decisions(out / "decisions.jsonl")
        self.check(True, "strict_journal_read", rid)
        starts = [row for row in journal if row["record_type"] == "decision_started"]
        finish = journal[-1]
        normalized = dict(journal[0]["metadata"])
        normalized.pop("seed_group", None)
        expected_manifest = dict(manifest)
        expected_manifest.pop("seed_group", None)
        self.check(_equal(normalized, expected_manifest), "manifest_matches_journal_start", rid)
        self.check(_equal(run_report, report), "per_run_report_matches_batch", rid)
        self.check(_equal(status, {"status": "finished", **report}), "status_matches_report", rid)
        self.check(finish["record_type"] == "run_finished" and _equal(finish["final_state"], final_state),
                   "final_state_matches_journal", rid)
        self.check(finish["outcome"] == report["outcome"]
                   and _equal(finish["environment_error"], report["error"]), "outcome_and_error_match_journal", rid)
        self.check(manifest["run_id"] == rid and manifest["seed"] == report["seed"], "run_seed_identity", rid)
        self.check(_equal(report["final_context"], final_state.get("context"))
                   and _equal(report["final_hp"], final_state.get("player", {}).get("hp")), "reported_final_state", rid)
        successful = [r for r in records if r["environment_error"] is None]
        eligible = [r for r in records if r["training_eligible"]]
        exclusions = sorted({reason for r in records for reason in r["training_exclusion_reasons"]})
        self.check(type(report["decisions"]) is int and report["decisions"] == len(successful),
                   "successful_transition_count", rid)
        self.check(len(starts) == len(records) == len(policies), "one_policy_completion_per_intent", rid)
        self.check(type(report["training_eligible_decisions"]) is int
                   and report["training_eligible_decisions"] == len(eligible), "eligibility_matches_code", rid)
        self.check(_equal(exclusions, report["exclusion_reasons"]), "exclusions_match_code", rid)
        if report["error"] is not None:
            self.check(report["outcome"] == "environment_error" and not eligible,
                       "error_never_fabricates_natural_result", rid)
        elif report["outcome"] in {"victory", "defeat"}:
            self.check(final_state.get("decision") == "game_over"
                       and final_state.get("victory") is (report["outcome"] == "victory"), "real_engine_terminal", rid)
        self.check(all(_equal(a["next_state"], b["state"]) for a, b in zip(records, records[1:])),
                   "macro_state_chain", rid)
        if records:
            self.check(_equal(records[-1]["next_state"], final_state), "last_transition_matches_final_state", rid)
        model = self.model(manifest, rid)
        pmap = {p["decision_id"]: p for p in policies}
        self.check(len(pmap) == len(policies) and set(pmap) == {r["decision_id"] for r in records},
                   "policy_ids_match_decisions", rid)
        try:
            validate_selection_contexts(records, pmap)
        except (ValueError, KeyError, TypeError) as exc:
            self.check(False, "selection_context_source_chain", rid, str(exc))
        else:
            self.check(True, "selection_context_source_chain", rid)
        evaluated, eligible_evaluated = 0, 0
        for position, record in enumerate(records):
            try:
                count = self.policy(record, pmap[record["decision_id"]], manifest, model, position)
                evaluated += count
                eligible_evaluated += count if record["training_eligible"] else 0
            except (ValueError, KeyError, TypeError, IndexError, OSError) as exc:
                self.check(False, "policy_evidence_readable", rid, f"{record['decision_id']}: {type(exc).__name__}: {exc}")
        from public_route_learning import validate_trace_observations
        try:
            validate_trace_observations(records, pmap, traces)
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            self.check(False, 'public_map_query_action_binding', rid, str(exc))
        else:
            self.check(True, 'public_map_query_action_binding', rid)
        if 'merchant_removal_audit.py' in manifest.get('versions', {}).get('sources', {}):
            from merchant_removal_audit import validate_merchant_lifecycle
            try:
                merchant = validate_merchant_lifecycle(traces)
                if 'merchant_removal_value.py' in manifest.get('versions', {}).get('sources', {}):
                    from merchant_removal_value import validate_previews
                    merchant['selection_previews'] = validate_previews(traces)
            except (ValueError, KeyError, TypeError) as exc:
                self.check(False, 'merchant_removal_lifecycle', rid, str(exc))
            else:
                self.check(True, 'merchant_removal_lifecycle', rid, merchant)
        trace_calls = [t for t in traces if t["request"].get("cmd") == "solve"]
        returned = [{"request": t["request"], "response": t["response"]} for t in trace_calls
                    if t.get("response") is not None]
        transport = [t for t in traces if t.get("response") is None]
        calls = [c for r in records for c in r["solver_calls"]]
        self.check(type(report["solver_calls"]) is int and report["solver_calls"] == len(trace_calls),
                   "solver_attempt_count_matches_trace", rid)
        self.check(_equal(returned, solver_projection(calls)), "solver_responses_match_journal", rid)
        try:
            replay = validate_replay_evidence(calls, traces)
        except ValueError as exc:
            self.check(False, "solver_replay_trace_binding", rid, str(exc))
        else:
            self.check(replay["verified"], "solver_replay_trace_binding", rid, replay)
        config = manifest["solver_requested_config"]
        for trace in trace_calls:
            request = trace["request"]
            for key in ("solver_backend", "potion_policy", "growth_budgets", "act_boss_hp_strategy",
                        "final_boss_hp_strategy", "search_profile"):
                if key in config or key == "solver_backend":
                    default = "beam" if key == "solver_backend" else None
                    self.check(_equal(request.get(key, default), config.get(key, default)),
                               "solver_request_matches_manifest", rid, key)
            budgets = [config[key] for key in ("budget_ms", "first_budget_ms", "replan_budget_ms",
                                               "setup_budget_ms", "retry_budget_ms") if key in config]
            if budgets:
                self.check(type(request.get("budget_ms")) is int and request["budget_ms"] in budgets,
                           "solver_budget_from_manifest", rid)
        self.check(not transport or (report["error"] is not None and all(t.get("transport_error") for t in transport)),
                   "transport_failure_evidence", rid)
        current_state, before = {"type": "initializing"}, []
        for trace in traces:
            before.append(current_state)
            response = trace.get("response")
            if isinstance(response, dict) and (response.get("type") == "decision" or
                    (trace["request"].get("cmd") in {"action", "start_run"} and response.get("type") == "error")):
                current_state = response
        self.check(_equal(current_state, final_state), "trace_final_state", rid)
        cursor, unissued, matched_macro_indices = 0, [], []
        for record in records:
            found = next((index for index in range(cursor, len(traces))
                          if _equal(before[index], record["state"])
                          and _equal(traces[index]["request"], record["chosen"]["request"])), None)
            if found is None and record["environment_error"] is not None:
                # A deadline can reject a send before any engine request occurs.
                # Its entire run is excluded; do not invent an executed action.
                unissued.append(record["decision_id"])
            else:
                self.check(found is not None, "macro_request_executed_in_order", rid, record["decision_id"])
                if found is not None:
                    matched_macro_indices.append(found)
                    scoring = pmap[record["decision_id"]]["scoring"]
                    if scoring.get("feature_policy_version", scoring.get("policy_version")) in (FEATURE_VERSION, INTERACTION_VERSION):
                        self.check(_equal(record["execution"].get("direct_action_result"),
                                          direct_action_evidence(traces[found].get("response"))),
                                   "direct_action_return_matches_trace", rid, record["decision_id"])
                    cursor = found + 1
        from whole_run_policy import VERSION as WHOLE_RUN_POLICY
        from contextual_policy import VERSION as CONTEXTUAL_POLICY
        from card_identity_policy import VERSION as IDENTITY_POLICY
        from circulation_context_policy import VERSION as CIRCULATION_POLICY
        from circulation_capability_policy import VERSION as CAPABILITY_POLICY
        from compact_deck_policy import VERSION as COMPACT_POLICY
        from selection_target_policy import VERSION as TARGET_POLICY
        from event_risk_policy import VERSION as RISK_POLICY
        from public_route_policy import VERSION as ROUTE_POLICY
        from persistent_acquisition_policy import VERSION as PERSISTENT_POLICY
        from reference_archetype_policy import VERSION as REFERENCE_POLICY
        from neow_preference_policy import VERSION as NEOW_POLICY
        from event_effect_policy import VERSION as EVENT_EFFECT_POLICY
        if ((model is not None and model["format"] == PREFIX_MODEL)
                or manifest["provenance"].get("id") in (WHOLE_RUN_POLICY, CONTEXTUAL_POLICY, IDENTITY_POLICY, CIRCULATION_POLICY, CAPABILITY_POLICY, COMPACT_POLICY, TARGET_POLICY, RISK_POLICY, ROUTE_POLICY, REFERENCE_POLICY, PERSISTENT_POLICY, NEOW_POLICY, EVENT_EFFECT_POLICY)):
            starts = [t for t in traces if t["request"].get("cmd") == "start_run"]
            self.check(len(starts) == 1 and traces[0] is starts[0]
                       and _equal(starts[0]["request"], {"cmd": "start_run", "character": "Defect",
                                                        "ascension": 10, "seed": manifest["seed"]}),
                       "prefix_actual_natural_run_start", rid)
            actual_macros = [index for index, trace in enumerate(traces)
                if trace["request"].get("cmd") == "action" and before[index].get("type") == "decision"
                and before[index].get("context", {}).get("combat_in_progress") is False]
            self.check(matched_macro_indices == actual_macros, "prefix_entire_macro_trace_coverage", rid)
        for call in calls:
            self.settings[json.dumps(call["response"].get("settings", {}), sort_keys=True)] += 1
        implicit = [r for r in records if r["candidate_set"].get("representation") == IMPLICIT]
        skip_count = sum(int(r["candidate_set"]["selection_space"]["min_select"] == 0)
                         if r["candidate_set"].get("representation") == IMPLICIT
                         else sum(c["is_skip"] for c in r["candidate_set"]["candidates"]) for r in records)
        return records, {"run_id": rid, "seed": report["seed"], "outcome": report["outcome"],
            "policy_kind": manifest["provenance"]["kind"], "reported_successful_decisions": report["decisions"],
            "completed_transition_records": len(records), "failed_transition_records": len(records) - len(successful),
            "training_eligible_decisions": len(eligible), "excluded_decisions": len(records) - len(eligible),
            "candidate_count": sum(map(_candidate_count, records)), "eligible_candidate_count": sum(map(_candidate_count, eligible)),
            "evaluated_candidate_count": evaluated, "eligible_evaluated_candidate_count": eligible_evaluated,
            "implicit_decisions": len(implicit), "skip_candidate_count": skip_count,
            "solver_attempts": len(trace_calls), "solver_responses": len(calls), "exclusion_reasons": exclusions,
            "failed_actions_without_trace_attempt": unissued, "error": report["error"]}


def audit_batch(batch_dir, expected_runs=None, output=None):
    """Return an audit dict and write it to its ``output_path`` using exclusive create.

    A corrupt or missing input produces ``passed=False`` and an issue, rather
    than suppressing other runs. A caller-specified existing output is an error.
    With no output argument, an existing DATA_AUDIT.json gets a fresh timestamp
    sibling. No source journal, report, model or previous audit is changed.
    """
    batch = Path(batch_dir).resolve()
    if not batch.is_dir():
        raise NotADirectoryError(batch)
    if expected_runs is not None and (type(expected_runs) is not int or expected_runs < 0):
        raise ValueError("expected_runs must be a nonnegative integer")
    target = Path(output).resolve() if output is not None else batch / "DATA_AUDIT.json"
    if target.exists():
        if output is not None:
            raise FileExistsError(target)
        target = batch / ("DATA_AUDIT-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    audit = _Audit(batch)
    records, runs, reports, summary, saved_split = [], [], [], {}, {}
    for name, destination in (("summary.json", "summary"), ("reports.json", "reports"), ("split-manifest.json", "split")):
        try:
            value = audit.read(batch / name)
            if destination == "summary":
                if not isinstance(value, dict):
                    raise ValueError("summary must be an object")
                summary = value
            elif destination == "reports":
                if not isinstance(value, list):
                    raise ValueError("reports must be an array")
                reports = value
            else:
                if not isinstance(value, dict):
                    raise ValueError("split manifest must be an object")
                saved_split = value
        except (ValueError, TypeError, OSError) as exc:
            audit.check(False, "batch_input_readable", detail=f"{name}: {type(exc).__name__}: {exc}")
    audit.check(type(summary.get("runs")) is int and summary["runs"] == len(reports), "summary_run_count")
    audit.check(_equal(summary.get("reports"), reports), "summary_reports_agree")
    if expected_runs is not None:
        audit.check(len(reports) == expected_runs, "expected_run_count")
    ids = [r.get("run_id") if isinstance(r, dict) else None for r in reports]
    audit.check(all(isinstance(rid, str) for rid in ids) and len(set(map(str, ids))) == len(ids), "unique_run_ids")
    for report in reports:
        rid = report.get("run_id") if isinstance(report, dict) else None
        try:
            observations, run = audit.run(report)
            records.extend(observations)
            runs.append(run)
        except (ValueError, KeyError, TypeError, IndexError, OSError) as exc:
            audit.check(False, "run_evidence_readable", rid, f"{type(exc).__name__}: {exc}")
    splits = split_by_seed(records)
    rebuilt = {key: sorted({r["run_id"] for r in values}) for key, values in splits.items()}
    audit.check(_equal(rebuilt, saved_split), "saved_split_matches_seed_lineage_reconstruction")
    seed_sets = {key: {r["seed"] for r in values} for key, values in splits.items()}
    audit.check(all(not seed_sets[a] & seed_sets[b] for a, b in
                    (("train", "validation"), ("train", "test"), ("validation", "test"))), "no_cross_split_seed_leakage")
    eligible = [r for r in records if r["training_eligible"]]
    audit.check(type(summary.get("training_eligible_decisions")) is int
                and summary["training_eligible_decisions"] == len(eligible), "summary_eligibility_recomputed")
    outcomes = Counter(r["outcome"] for r in runs)
    count_keys = ("completed_transition_records", "failed_transition_records", "training_eligible_decisions", "excluded_decisions",
                  "candidate_count", "eligible_candidate_count", "evaluated_candidate_count", "eligible_evaluated_candidate_count",
                  "implicit_decisions", "skip_candidate_count", "solver_attempts", "solver_responses")
    result = {"audit_schema": "sts2.batch_data_audit.v2", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "batch": str(batch), "output_path": str(target), "passed": not audit.issues,
        "scope": "Existing report/status/manifest/journal/policy/trace/source/split evidence only; no games or training.",
        "evaluation_use": "blinded_status_not_established_by_data_audit", "win_rate_claim_permitted": False,
        "evaluation_note": "Recorded outcomes and consistency counts do not establish policy quality or a blinded holdout. Development or repeated seeds must remain labeled as such.",
        "reported_purpose": summary.get("purpose"),
        "counts": {"reported_runs": len(reports), "audited_runs": len(runs), "distinct_seeds": len({r['seed'] for r in runs}),
            "seed_lineage_groups": _group_count(records), "outcomes": dict(outcomes),
            **{key: sum(r[key] for r in runs) for key in count_keys}},
        "candidate_count_semantics": "Exact full legal action-space sizes; implicit spaces are not claimed to have all actions scored. Evaluated counts include only logged complete requests.",
        "decision_count_semantics": "Reports count successful macro transitions. Journals also retain failed transitions; run-wide exclusions come from read_decisions.",
        "grouped_splits": {key: {"run_ids": rebuilt[key], "groups": _group_count(values), "decisions": len(values),
            "training_eligible_decisions": sum(r["training_eligible"] for r in values),
            "candidate_count": sum(map(_candidate_count, values)),
            "eligible_candidate_count": sum(_candidate_count(r) for r in values if r["training_eligible"]),
            "evaluated_candidate_count": sum(audit.evaluated.get(r["decision_id"], 0) for r in values),
            "eligible_evaluated_candidate_count": sum(audit.evaluated.get(r["decision_id"], 0) for r in values if r["training_eligible"])}
            for key, values in splits.items()},
        "zero_decision_run_ids_absent_from_split": [r["run_id"] for r in runs if r["completed_transition_records"] == 0],
        "checks": dict(audit.checks), "issues": audit.issues, "runs": runs,
        "model_artifact_sources": list(audit.models.values()),
        "implicit_probability_evidence": [{**json.loads(key), "decisions": value}
                                          for key, value in audit.selection_precision.items()],
        "exclusion_reason_decisions": dict(Counter(reason for record in records for reason in record["training_exclusion_reasons"])),
        "solver_settings_variants": [{"settings": json.loads(k), "calls": v} for k, v in audit.settings.items()],
        "source_evidence": list(audit.evidence.values()),
        "auditor_code_evidence": [audit.source(ROOT / name) for name in
            ("audit_batch.py", "decision_data.py", "selection_space.py", "selection_policy.py", "selection_context.py", "solver_evidence.py", "replay_evidence.py")]}
    with target.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("batch_dir", type=Path)
    parser.add_argument("--expected-runs", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit_batch(args.batch_dir, args.expected_runs, args.output)
    print(json.dumps({key: result[key] for key in ("output_path", "passed", "counts", "issues")}, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
