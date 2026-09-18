"""Wrapper adding exact rest healing and latched public route damage."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from decision_data import DataContractError, state_hash
from map_observation import validate_map_observation
from reward_mechanism_policy import FEATURE_SOURCES as PARENT_SOURCES, RewardMechanismPolicy
import rest_heal_route_features
from run_metadata import file_evidence


VERSION = "whole-run-public-rest-heal-route-v1"
ROOT = Path(__file__).resolve().parent
FEATURE_SOURCES = tuple(dict.fromkeys((
    *PARENT_SOURCES,
    "current_relics_eng.json",
    "rest_heal_route_features.py",
    "rest_heal_route_policy.py",
)))


def source_files():
    return {name: file_evidence(ROOT / name) for name in FEATURE_SOURCES}


def make_artifact(parent_model, solver_config, *, training):
    parent = Path(parent_model).resolve()
    if not parent.is_file():
        raise DataContractError("Rest-heal parent model is missing")
    return {
        "format": VERSION,
        "parent_model": file_evidence(parent),
        "parameters": copy.deepcopy(rest_heal_route_features.PRIOR),
        "parameter_names": list(rest_heal_route_features.PARAMETERS),
        "solver_requested_config": copy.deepcopy(solver_config),
        "training": copy.deepcopy(training),
        "source_files": source_files(),
        "rest_heal_route_contract": copy.deepcopy(rest_heal_route_features.CONTRACT),
        "score_semantics": "validated_reward_parent_plus_exact_heal_route_risk_bridge_not_win_probability",
        "calibrated_probability": False,
        "automatic_deployment": False,
    }


class RestHealRoutePolicy(RewardMechanismPolicy):
    def __init__(self, path, *, solver_config, seed, epsilon=0.0):
        wrapper_path = Path(path).resolve()
        wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
        parent = wrapper.get("parent_model") or {}
        parent_path = parent.get("path")
        parameters = wrapper.get("parameters") or {}
        if not isinstance(parent_path, str) or not Path(parent_path).is_absolute():
            raise DataContractError("Rest-heal parent path is invalid")
        if (
            wrapper.get("format") != VERSION
            or wrapper.get("parameter_names") != list(rest_heal_route_features.PARAMETERS)
            or set(parameters) != set(rest_heal_route_features.PARAMETERS)
            or any(type(value) not in (int, float) or not math.isfinite(value)
                   or abs(value) > 4 for value in parameters.values())
            or parameters != rest_heal_route_features.PRIOR
            or wrapper.get("solver_requested_config") != solver_config
            or wrapper.get("source_files") != source_files()
            or wrapper.get("rest_heal_route_contract") != rest_heal_route_features.CONTRACT
            or wrapper.get("calibrated_probability") is not False
            or wrapper.get("automatic_deployment") is not False
            or file_evidence(parent_path) != parent
        ):
            raise DataContractError("Invalid rest-heal route artifact")
        super().__init__(parent_path, solver_config=solver_config,
                         seed=seed, epsilon=epsilon)
        self._rest_path = wrapper_path
        self._rest_artifact = wrapper
        self._rest_source = file_evidence(wrapper_path)
        self._rest_artifact_hash = state_hash(wrapper)
        self._rest_route_input = None
        self._rest_map_observation = None

    @property
    def provenance(self):
        parent = super().provenance
        return {
            **parent,
            "kind": "search",
            "id": VERSION,
            "version": self._rest_source["sha256"],
            "policy_source": copy.deepcopy(self._rest_source),
            "parent_policy_source": copy.deepcopy(parent.get("policy_source")),
            "score_semantics": self._rest_artifact["score_semantics"],
            "training_method": "exact_public_heal_and_frozen_public_route_damage_fixed_prior",
            "automatic_deployment": False,
        }

    def _verify_sources(self):
        if (
            file_evidence(self._rest_path) != self._rest_source
            or state_hash(self._rest_artifact) != self._rest_artifact_hash
            or self._rest_artifact["source_files"] != source_files()
            or file_evidence(self._rest_artifact["parent_model"]["path"])
            != self._rest_artifact["parent_model"]
        ):
            raise DataContractError("Rest-heal route sources changed after loading")

    def set_rest_route_observation(self, state, observation):
        self._verify_sources()
        if state.get("decision") != "map_select":
            raise DataContractError("Rest route observation requires map_select")
        validate_map_observation(state, observation)
        self._rest_map_observation = copy.deepcopy(observation)

    def set_rest_route_input(self, state, value):
        self._verify_sources()
        if state.get("decision") == "rest_site":
            if value is not None:
                rest_heal_route_features.validate_context(value, state)
            self._rest_route_input = copy.deepcopy(value)
        else:
            if value is not None:
                raise DataContractError("Non-rest decision cannot use rest route input")
            self._rest_route_input = None

    def _rest_adjust(self, state, packet):
        self._verify_sources()
        packet = rest_heal_route_features.adjust(
            state, packet,
            self._rest_route_input if state.get("decision") == "rest_site" else None,
            self._rest_artifact["parameters"],
        )
        packet.update(
            policy_id=VERSION,
            policy_version=self._rest_source["sha256"],
            rest_heal_route_policy_source=copy.deepcopy(self._rest_source),
            parent_policy_version=super().provenance["version"],
            score_semantics=self._rest_artifact["score_semantics"],
        )
        return packet

    def score(self, state, candidates=None, *, selection_purpose=None):
        return self._rest_adjust(
            state,
            super().score(state, candidates, selection_purpose=selection_purpose),
        )

    def score_requests(self, state, requests, *, selection_purpose=None):
        return self._rest_adjust(
            state,
            super().score_requests(state, requests,
                                   selection_purpose=selection_purpose),
        )

    def choose(self, state, candidates=None, *, selection_purpose=None):
        result = super().choose(
            state, candidates, selection_purpose=selection_purpose
        )
        if state.get("decision") == "map_select":
            if self._rest_map_observation is None:
                raise DataContractError("Map choice lacks rest-route observation")
            self._rest_route_input = rest_heal_route_features.make_context(
                state,
                self._rest_map_observation,
                result["request"],
                self._encounter_damage_catalog,
            )
            self._rest_map_observation = None
        elif state.get("decision") == "rest_site":
            self._rest_route_input = None
        return result
