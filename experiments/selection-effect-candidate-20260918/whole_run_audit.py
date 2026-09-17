"""Pure whole-run policy reconstruction; no engine execution or training."""
from decision_data import DataContractError, state_hash
from whole_run_policy import VERSION, WholeRunPolicy, FEATURE_SOURCES
from contextual_policy import VERSION as CONTEXT_VERSION, ContextualPolicy, FEATURE_SOURCES as CONTEXT_SOURCES
from card_identity_policy import VERSION as IDENTITY_VERSION, CardIdentityPolicy, FEATURE_SOURCES as IDENTITY_SOURCES
from circulation_context_policy import VERSION as CIRCULATION_VERSION, CirculationContextPolicy, FEATURE_SOURCES as CIRCULATION_SOURCES
from circulation_capability_policy import VERSION as CAPABILITY_VERSION, CirculationCapabilityPolicy, FEATURE_SOURCES as CAPABILITY_SOURCES
from compact_deck_policy import VERSION as COMPACT_VERSION, CompactDeckPolicy, FEATURE_SOURCES as COMPACT_SOURCES
from selection_target_policy import VERSION as TARGET_VERSION, SelectionTargetPolicy, FEATURE_SOURCES as TARGET_SOURCES
from event_risk_policy import VERSION as RISK_VERSION, EventRiskPolicy, FEATURE_SOURCES as RISK_SOURCES
from public_route_policy import VERSION as ROUTE_VERSION, PublicRoutePolicy, FEATURE_SOURCES as ROUTE_SOURCES
from reference_archetype_policy import VERSION as REFERENCE_VERSION, ReferenceArchetypePolicy, FEATURE_SOURCES as REFERENCE_SOURCES
from persistent_acquisition_policy import VERSION as PERSISTENT_VERSION, PersistentAcquisitionPolicy, FEATURE_SOURCES as PERSISTENT_SOURCES
from selection_policy import SelectionPolicy
from neow_preference_policy import VERSION as NEOW_VERSION, NeowPreferencePolicy, FEATURE_SOURCES as NEOW_SOURCES
from event_effect_policy import VERSION as EVENT_EFFECT_VERSION, EventEffectPolicy, FEATURE_SOURCES as EVENT_EFFECT_SOURCES
from selection_effect_policy import VERSION as SELECTION_EFFECT_VERSION, SelectionEffectPolicy, FEATURE_SOURCES as SELECTION_EFFECT_SOURCES
from run_metadata import file_evidence


REGISTRY = {VERSION: (WholeRunPolicy, FEATURE_SOURCES),
            CONTEXT_VERSION: (ContextualPolicy, CONTEXT_SOURCES),
            IDENTITY_VERSION: (CardIdentityPolicy, IDENTITY_SOURCES),
            CIRCULATION_VERSION: (CirculationContextPolicy, CIRCULATION_SOURCES),
            CAPABILITY_VERSION: (CirculationCapabilityPolicy, CAPABILITY_SOURCES),
            COMPACT_VERSION: (CompactDeckPolicy, COMPACT_SOURCES),
            TARGET_VERSION: (SelectionTargetPolicy, TARGET_SOURCES),
            RISK_VERSION: (EventRiskPolicy, RISK_SOURCES), ROUTE_VERSION: (PublicRoutePolicy, ROUTE_SOURCES),
            REFERENCE_VERSION: (ReferenceArchetypePolicy, REFERENCE_SOURCES),
            PERSISTENT_VERSION: (PersistentAcquisitionPolicy, PERSISTENT_SOURCES),
            NEOW_VERSION: (NeowPreferencePolicy, NEOW_SOURCES),
            EVENT_EFFECT_VERSION: (EventEffectPolicy, EVENT_EFFECT_SOURCES),
            SELECTION_EFFECT_VERSION: (SelectionEffectPolicy, SELECTION_EFFECT_SOURCES)}


def validate_whole_run_choices(records, policies):
    grouped = {}
    for r in records:
        grouped.setdefault(r["run_id"], []).append(r)
    for run_id, rows in grouped.items():
        marked = any(r["metadata"].get("provenance", {}).get("id") in REGISTRY
            or policies[r["decision_id"]]["scoring"].get("policy_id") in REGISTRY
            or any("search_features" in s for s in policies[r["decision_id"]]["scoring"].get("scores", []))
            for r in rows)
        if not marked:
            continue
        meta = rows[0]["metadata"]
        def require(ok, why):
            if not ok:
                raise DataContractError("Whole-run policy audit: " + why)
        require(meta["character"] == "Defect" and meta["ascension"] == 10 and meta["mode"] == "standard",
                "unsupported run scope")
        provenance = meta["provenance"]
        require(provenance.get("id") in REGISTRY and provenance.get("kind") == "search", "relabelled policy")
        path = meta["sampling"]["model_path"]
        require(file_evidence(path) == provenance["policy_source"], "changed parameter artifact")
        policy_class, feature_sources = REGISTRY[provenance["id"]]
        base = policy_class(path, solver_config=meta["solver_requested_config"], seed=meta["seed"],
                              epsilon=meta["sampling"]["epsilon"])
        from compact_deck_policy import CompactSelectionPolicy
        from selection_target_policy import SelectionTargetSelectionPolicy
        from event_risk_policy import EventRiskSelectionPolicy
        from public_route_policy import PublicRouteSelectionPolicy
        wrapper = (PublicRouteSelectionPolicy if isinstance(base, PublicRoutePolicy) else
            EventRiskSelectionPolicy if isinstance(base, EventRiskPolicy) else
            SelectionTargetSelectionPolicy if isinstance(base, SelectionTargetPolicy) else
            CompactSelectionPolicy if isinstance(base, CompactDeckPolicy) else SelectionPolicy)
        policy = wrapper(base, max_evaluations=meta["sampling"]["selection_budget"])
        require(state_hash(policy.provenance) == state_hash(provenance), "manifest identity")
        declared_sources = (base._selection_artifact["source_files"]
                            if isinstance(base, SelectionEffectPolicy) else
                            base._event_artifact["source_files"]
                            if isinstance(base, EventEffectPolicy) else base.artifact["source_files"])
        for name in feature_sources:
            require(declared_sources[name] == meta["versions"]["sources"].get(name), "feature source")
        previous = None
        for i, record in enumerate(rows):
            actual = policies[record["decision_id"]]
            require(state_hash(record["metadata"]) == state_hash(meta), "changing metadata")
            require(previous is None or (previous.get("environment_error") is None
                and state_hash(previous["next_state"]) == state_hash(record["state"])), "broken sequence")
            context = actual.get("selection_context")
            extra_keys = set()
            if isinstance(base, PublicRoutePolicy):
                from public_route_learning import policy_input
                value = policy_input(record['state'], actual['map_observation']) if record['state'].get('decision') == 'map_select' else None
                base.set_public_route_input(record['state'], value)
                if value is not None: extra_keys.add('map_observation')
            expected = policy.choose(record["state"], candidates=record["candidate_set"],
                                     selection_purpose=context["purpose"] if context else None)
            require(set(actual) == set(expected) | {"decision_id", "selection_context"} | extra_keys
                and state_hash({key: actual[key] for key in expected}) == state_hash(expected),
                "scores, residual features, choices or RNG differ at " + str(i))
            previous = record
    return True
