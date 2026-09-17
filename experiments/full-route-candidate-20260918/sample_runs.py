"""Bounded natural A10 sampling with non-LLM macro policy and original CombatSolver."""
from __future__ import annotations

import argparse
import json
import re
import time
import traceback
from pathlib import Path

from combat_executor import CombatExecutor, solver_config
from decision_data import DataContractError, DecisionJournal, enumerate_candidates, materialize_candidate, read_decisions, split_by_seed
from probe import Bridge, ROOT
from run_metadata import atomic_json, metadata


from selection_context import (EXACT_SELECTION_PURPOSES, selection_context, bind_selection_context,
                               direct_action_evidence)


def selection_purpose(candidate):
    context = selection_context(candidate)
    return context["purpose"] if context else None


def build_policy(seed, settings, *, ascension=10, epsilon=.1, model_path=None, selection_budget=256):
    """Construct the exact prospective policy without starting or recording a run.

    The returned SelectionPolicy exposes .provenance for protocol preflight.
    Scoped models require the declared Defect/A10 run and their frozen solver
    configuration; paired-prefix models also require their registered protocol.
    Earlier rule/linear policies retain their existing behavior.
    """
    from initial_policy import InitialPolicy
    from selection_policy import SelectionPolicy

    model_format = None
    if model_path:
        from train_ranker import VERSION as LINEAR_FORMAT
        from train_act_survival import VERSION as SURVIVAL_FORMAT
        from train_interaction_survival import VERSION as INTERACTION_FORMAT
        from train_prefix_ranker import VERSION as PREFIX_FORMAT
        from whole_run_policy import VERSION as WHOLE_RUN_FORMAT
        from contextual_policy import VERSION as CONTEXTUAL_FORMAT
        from card_identity_policy import VERSION as IDENTITY_FORMAT
        from circulation_context_policy import VERSION as CIRCULATION_FORMAT
        from circulation_capability_policy import VERSION as CAPABILITY_FORMAT
        from compact_deck_policy import VERSION as COMPACT_FORMAT
        from selection_target_policy import VERSION as TARGET_FORMAT
        from event_risk_policy import VERSION as RISK_FORMAT
        from public_route_policy import VERSION as ROUTE_FORMAT
        from persistent_acquisition_policy import VERSION as PERSISTENT_FORMAT
        from reference_archetype_policy import VERSION as REFERENCE_FORMAT
        from neow_preference_policy import VERSION as NEOW_FORMAT
        from event_effect_policy import VERSION as EVENT_EFFECT_FORMAT
        from selection_effect_policy import VERSION as SELECTION_EFFECT_FORMAT
        from full_route_policy import VERSION as FULL_ROUTE_FORMAT
        try:
            artifact = json.loads(Path(model_path).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise DataContractError("Invalid model artifact JSON") from exc
        if not isinstance(artifact, dict):
            raise DataContractError("Model artifact must be a JSON object")
        model_format = artifact.get("format")
        if model_format not in (LINEAR_FORMAT, SURVIVAL_FORMAT, INTERACTION_FORMAT, PREFIX_FORMAT, WHOLE_RUN_FORMAT, CONTEXTUAL_FORMAT, IDENTITY_FORMAT, CIRCULATION_FORMAT, CAPABILITY_FORMAT, COMPACT_FORMAT, TARGET_FORMAT, RISK_FORMAT, ROUTE_FORMAT, REFERENCE_FORMAT, PERSISTENT_FORMAT, NEOW_FORMAT, EVENT_EFFECT_FORMAT, SELECTION_EFFECT_FORMAT, FULL_ROUTE_FORMAT):
            raise DataContractError("Unsupported model artifact format: " + repr(model_format))

    policy = InitialPolicy(epsilon=epsilon, random_seed=seed)
    if model_path:
        if model_format == FULL_ROUTE_FORMAT:
            from full_route_policy import FullRoutePolicy
            if ascension != 10: raise DataContractError("Full route policy requires Defect A10")
            policy = FullRoutePolicy(model_path, solver_config=settings, seed=seed, epsilon=epsilon)
        elif model_format == SELECTION_EFFECT_FORMAT:
            from selection_effect_policy import SelectionEffectPolicy
            if ascension != 10: raise DataContractError("Selection effect policy requires Defect A10")
            policy = SelectionEffectPolicy(model_path, solver_config=settings, seed=seed, epsilon=epsilon)
        elif model_format == EVENT_EFFECT_FORMAT:
            from event_effect_policy import EventEffectPolicy
            if ascension != 10: raise DataContractError("Event effect policy requires Defect A10")
            policy = EventEffectPolicy(model_path, solver_config=settings, seed=seed, epsilon=epsilon)
        elif model_format == LINEAR_FORMAT:
            from train_ranker import SmallValuePolicy
            policy = SmallValuePolicy(model_path, fallback=policy, epsilon=epsilon, seed=seed)
        elif model_format == SURVIVAL_FORMAT:
            from survival_policy import SurvivalPolicy
            policy = SurvivalPolicy(model_path, solver_config=settings, character="Defect", ascension=ascension,
                mode="standard", fallback=policy, epsilon=epsilon, seed=seed)
        elif model_format == INTERACTION_FORMAT:
            from interaction_survival_policy import InteractionSurvivalPolicy
            policy = InteractionSurvivalPolicy(model_path, solver_config=settings, character="Defect", ascension=ascension,
                mode="standard", fallback=policy, epsilon=epsilon, seed=seed)
        elif model_format == NEOW_FORMAT:
            from neow_preference_policy import NeowPreferencePolicy
            if ascension != 10: raise DataContractError("Neow preference requires Defect A10")
            policy = NeowPreferencePolicy(model_path, solver_config=settings, seed=seed, epsilon=epsilon)
        elif model_format == PERSISTENT_FORMAT:
            from persistent_acquisition_policy import PersistentAcquisitionPolicy
            if ascension != 10: raise DataContractError('Persistent acquisition policy requires Defect A10')
            policy = PersistentAcquisitionPolicy(model_path, solver_config=settings, seed=seed, epsilon=epsilon)
        elif model_format == REFERENCE_FORMAT:
            from reference_archetype_policy import ReferenceArchetypePolicy
            if ascension != 10: raise DataContractError('Public-reference policy requires Defect A10')
            policy = ReferenceArchetypePolicy(model_path, solver_config=settings, seed=seed, epsilon=epsilon)
        elif model_format == ROUTE_FORMAT:
            from public_route_policy import PublicRoutePolicy
            if ascension != 10: raise DataContractError('Public route policy requires Defect A10')
            policy = PublicRoutePolicy(model_path, solver_config=settings, seed=seed, epsilon=epsilon)
        elif model_format == RISK_FORMAT:
            from event_risk_policy import EventRiskPolicy
            if ascension != 10: raise DataContractError("Event risk policy requires Defect A10")
            policy = EventRiskPolicy(model_path, solver_config=settings, seed=seed, epsilon=epsilon)
        elif model_format == TARGET_FORMAT:
            from selection_target_policy import SelectionTargetPolicy
            if ascension != 10: raise DataContractError("Selection target policy requires Defect A10")
            policy = SelectionTargetPolicy(model_path, solver_config=settings, seed=seed, epsilon=epsilon)
        elif model_format == COMPACT_FORMAT:
            from compact_deck_policy import CompactDeckPolicy
            if ascension != 10: raise DataContractError("Compact deck policy requires Defect A10")
            policy = CompactDeckPolicy(model_path, solver_config=settings, seed=seed, epsilon=epsilon)
        elif model_format == CAPABILITY_FORMAT:
            from circulation_capability_policy import CirculationCapabilityPolicy
            if ascension != 10:
                raise DataContractError("Capability policy requires Defect A10")
            policy = CirculationCapabilityPolicy(model_path, solver_config=settings, seed=seed, epsilon=epsilon)
        elif model_format == CIRCULATION_FORMAT:
            from circulation_context_policy import CirculationContextPolicy
            if ascension != 10:
                raise DataContractError("Circulation search policy requires Defect A10")
            policy = CirculationContextPolicy(model_path, solver_config=settings, seed=seed, epsilon=epsilon)
        elif model_format == IDENTITY_FORMAT:
            from card_identity_policy import CardIdentityPolicy
            if ascension != 10:
                raise DataContractError("Card identity search policy requires Defect A10")
            policy = CardIdentityPolicy(model_path, solver_config=settings, seed=seed, epsilon=epsilon)
        elif model_format == CONTEXTUAL_FORMAT:
            from contextual_policy import ContextualPolicy
            if ascension != 10:
                raise DataContractError("Contextual search policy requires Defect A10")
            policy = ContextualPolicy(model_path, solver_config=settings, seed=seed, epsilon=epsilon)
        elif model_format == WHOLE_RUN_FORMAT:
            from whole_run_policy import WholeRunPolicy
            if ascension != 10:
                raise DataContractError("Whole-run search policy requires Defect A10")
            policy = WholeRunPolicy(model_path, solver_config=settings, seed=seed, epsilon=epsilon)
        else:
            from prefix_health_policy import PrefixHealthPolicy
            source = artifact.get("source_protocol")
            protocol_path = source.get("path") if isinstance(source, dict) else None
            if (not isinstance(protocol_path, str) or not protocol_path
                    or not Path(protocol_path).is_absolute()):
                raise DataContractError("Paired-prefix artifact must identify its absolute registered protocol path")
            policy = PrefixHealthPolicy(model_path, protocol_path=protocol_path, solver_config=settings,
                character="Defect", ascension=ascension, mode="standard", epsilon=epsilon, seed=seed)
    from compact_deck_policy import CompactDeckPolicy, CompactSelectionPolicy
    from selection_target_policy import SelectionTargetPolicy, SelectionTargetSelectionPolicy
    from event_risk_policy import EventRiskPolicy, EventRiskSelectionPolicy
    from public_route_policy import PublicRoutePolicy, PublicRouteSelectionPolicy
    wrapper = (PublicRouteSelectionPolicy if isinstance(policy, PublicRoutePolicy) else
        EventRiskSelectionPolicy if isinstance(policy, EventRiskPolicy) else
        SelectionTargetSelectionPolicy if isinstance(policy, SelectionTargetPolicy) else
        CompactSelectionPolicy if isinstance(policy, CompactDeckPolicy) else SelectionPolicy)
    return wrapper(policy, max_evaluations=selection_budget)


def run_one(name, seed, *, ascension=10, settings=None, epsilon=.1, max_seconds=1200,
            max_decisions=500, model_path=None, selection_budget=256):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError("Invalid run name")
    settings = settings or solver_config()
    policy = build_policy(seed, settings, ascension=ascension, epsilon=epsilon,
                          model_path=model_path, selection_budget=selection_budget)
    from persistent_acquisition_policy import PersistentAcquisitionPolicy, require_parent_integration
    if isinstance(getattr(policy, 'base', None), PersistentAcquisitionPolicy):
        require_parent_integration()
    out = ROOT / "outputs" / name
    out.mkdir(parents=True, exist_ok=False)
    provenance = policy.provenance
    manifest = metadata(name, seed, ascension, settings, provenance)
    manifest["sampling"] = {"epsilon": epsilon, "max_seconds": max_seconds, "max_decisions": max_decisions,
        "model_path": str(model_path) if model_path else None, "hidden_audit_features_used": False,
        "selection_budget": selection_budget}
    atomic_json(out / "manifest.json", manifest)
    journal = DecisionJournal(out, manifest)
    trace = (out / "trace.jsonl").open("x", encoding="utf-8")
    scores = (out / "policy.jsonl").open("x", encoding="utf-8")
    start = time.monotonic()
    state = {"type": "initializing"}
    bridge = None
    token = None
    failure = None
    termination = "stopped"
    steps = 0
    calls = 0
    second_entered = False
    purpose = None
    purpose_context = None
    direct_state = None
    current_execution = None

    def send(**request):
        nonlocal calls, second_entered, state
        if time.monotonic() - start > max_seconds:
            raise TimeoutError("Per-run time limit reached")
        before = time.monotonic()
        from decision_data import state_hash
        map_binding = ({'decision_state_hash': state_hash(state)} if request['cmd'] == 'get_map' else {})
        calls += int(request["cmd"] == "solve")
        try:
            response = bridge.send(**request)
        except Exception as exc:
            trace.write(json.dumps({"elapsed": time.monotonic() - start, "request": request,
                "response": None, **map_binding, "transport_error": repr(exc), "seconds": time.monotonic() - before}) + "\n")
            trace.flush()
            raise
        trace.write(json.dumps({"elapsed": time.monotonic() - start, "request": request,
            "response": response, **map_binding, "seconds": time.monotonic() - before}, ensure_ascii=False) + "\n")
        trace.flush()
        if response.get("type") == "decision" or (request["cmd"] in {"action", "start_run"} and response.get("type") == "error"):
            state = response
            if response.get("context", {}).get("integrity_recovery_used") is True:
                raise RuntimeError("Engine recovery was used; trajectory is not clean natural training data")
            if response.get("decision") == "combat_play" and response.get("context", {}).get("is_second_boss") is True:
                second_entered = True
        return response

    def publish(value):
        atomic_json(out / "state.json", value)
        atomic_json(out / "status.json", {"status": "sampling", "run_id": name, "seed": seed,
            "decisions": steps, "solver_calls": calls, "elapsed": time.monotonic() - start,
            "decision": value.get("decision"), "context": value.get("context")})

    executor = CombatExecutor(send, settings, publish)
    try:
        bridge = Bridge(name)
        state = send(cmd="start_run", character="Defect", ascension=ascension, seed=seed)
        while state.get("decision") != "game_over":
            if state.get("type") == "error":
                raise RuntimeError(json.dumps(state))
            if steps >= max_decisions:
                raise TimeoutError("Per-run macro decision limit reached")
            candidates = enumerate_candidates(state)
            if not candidates["complete"]:
                raise RuntimeError("Incomplete candidate set: " + str(candidates["reason"]))
            # Hidden RNG audit data never enter state or the policy input.
            from public_route_policy import PublicRoutePolicy
            observation = None
            if isinstance(policy.base, PublicRoutePolicy):
                from public_route_learning import observe_before_choice
                observation, route_input = observe_before_choice(state, send)
                policy.base.set_public_route_input(state, route_input)
            from full_route_policy import FullRoutePolicy
            if isinstance(policy.base, FullRoutePolicy):
                from full_route_features import policy_input as full_route_input
                value = full_route_input(state, observation) if state.get("decision") == "map_select" else None
                policy.base.set_full_route_input(state, value)
            picked = policy.choose(state, candidates=candidates, selection_purpose=purpose)
            if observation is not None:
                picked['map_observation'] = observation
            chosen = materialize_candidate(candidates, picked["request"])
            source_state = state
            direct_state = None
            current_execution = {"exploration": picked.get("exploration"), "selection_purpose": purpose,
                                 "selection_context": purpose_context, "direct_action_result": None}
            token = journal.begin(state, picked["request"], policy=picked["policy_provenance"], candidates=candidates)
            scores.write(json.dumps({"decision_id": token, **picked, "selection_context": purpose_context}, ensure_ascii=False) + "\n")
            scores.flush()
            direct_state = send(**picked["request"])
            current_execution["direct_action_result"] = direct_action_evidence(direct_state)
            state = executor.advance(direct_state)
            if state.get("type") == "error":
                raise RuntimeError(json.dumps(state, ensure_ascii=False))
            journal.complete(token, state, solver_calls=executor.solve_calls,
                execution=current_execution)
            purpose_context = bind_selection_context(chosen, token, source_state, direct_state, state,
                                                     captured_direct=current_execution["direct_action_result"])
            token = None
            purpose = purpose_context["purpose"] if purpose_context else None
            steps += 1
            publish(state)
        termination = "engine_terminal"
    except Exception as exc:
        termination = "timeout" if isinstance(exc, TimeoutError) else "environment_error"
        failure = {"kind": termination, "traceback": traceback.format_exc()}
        (out / "error.txt").write_text(failure["traceback"], encoding="utf-8")
        if token:
            journal.complete(token, state, solver_calls=executor.solve_calls, environment_error=failure,
                             execution=current_execution or {"selection_context": purpose_context,
                                 "selection_purpose": purpose, "direct_action_result": direct_action_evidence(direct_state)})
    finally:
        evidence = {"second_boss_entered": second_entered,
            "second_boss_victory": second_entered and state.get("victory") is True
                and state.get("context", {}).get("is_second_boss") is True,
            "trace_reference": str(out / "trace.jsonl")}
        result = journal.finalize(state, termination=termination, environment_error=failure, terminal_evidence=evidence)
        if bridge:
            bridge.close()
        trace.close()
        scores.close()
        observations = read_decisions(out / "decisions.jsonl")
        report = {"run_id": name, "seed": seed, "outcome": result["outcome"], "decisions": steps,
            "solver_calls": calls, "seconds": time.monotonic() - start,
            "training_eligible_decisions": sum(r["training_eligible"] for r in observations),
            "exclusion_reasons": sorted({v for r in observations for v in r["training_exclusion_reasons"]}),
            "final_context": state.get("context"), "final_hp": state.get("player", {}).get("hp"),
            "error": failure}
        atomic_json(out / "state.json", state)
        atomic_json(out / "status.json", {"status": "finished", **report})
        atomic_json(out / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-name", required=True)
    parser.add_argument("--seed-prefix", required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--ascension", type=int, default=10, choices=range(11))
    parser.add_argument("--epsilon", type=float, default=.1)
    parser.add_argument("--max-seconds-per-run", type=int, default=1200)
    parser.add_argument("--max-decisions", type=int, default=500)
    parser.add_argument("--solver-config", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--selection-budget", type=int, default=256)
    args = parser.parse_args()
    if not 1 <= args.runs <= 10000 or not 0 <= args.epsilon <= 1:
        parser.error("Invalid runs or epsilon")
    batch = ROOT / "outputs" / args.batch_name
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.batch_name):
        parser.error("Invalid batch name")
    batch.mkdir(parents=True, exist_ok=False)
    settings = solver_config(args.solver_config)
    reports = []
    records = []
    for index in range(args.start_index, args.start_index + args.runs):
        name = f"{args.batch_name}-{index:04d}"
        report = run_one(name, f"{args.seed_prefix}-{index:04d}", ascension=args.ascension,
            settings=settings, epsilon=args.epsilon, max_seconds=args.max_seconds_per_run,
            max_decisions=args.max_decisions, model_path=args.model, selection_budget=args.selection_budget)
        reports.append(report)
        records.extend(read_decisions(ROOT / "outputs" / name / "decisions.jsonl"))
        atomic_json(batch / "reports.json", reports)
        print(json.dumps(report, ensure_ascii=True), flush=True)
    splits = split_by_seed(records)
    atomic_json(batch / "split-manifest.json", {key: sorted({r["run_id"] for r in rows}) for key, rows in splits.items()})
    atomic_json(batch / "summary.json", {"runs": len(reports), "reports": reports,
        "training_eligible_decisions": sum(r["training_eligible"] for r in records),
        "purpose": "connectivity pilot; no claim of policy quality or calibrated win probability"})


if __name__ == "__main__":
    main()
