"""Wrapper adding fixed complete public-route topology utility."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from decision_data import DataContractError, state_hash
import full_route_features
from run_metadata import file_evidence
from selection_effect_policy import (
    FEATURE_SOURCES as PARENT_SOURCES,
    SelectionEffectPolicy,
)


VERSION = "whole-run-public-full-route-effects-v1"
ROOT = Path(__file__).resolve().parent
FEATURE_SOURCES = tuple(
    dict.fromkeys(
        (
            *PARENT_SOURCES,
            "full_route_features.py",
            "full_route_policy.py",
        )
    )
)


def source_files() -> dict[str, dict]:
    return {name: file_evidence(ROOT / name) for name in FEATURE_SOURCES}


def make_artifact(parent_model: str | Path, solver_config: dict, *, training: dict) -> dict:
    parent = Path(parent_model).resolve()
    if not parent.is_file():
        raise DataContractError("Full-route parent model is missing")
    return {
        "format": VERSION,
        "parent_model": file_evidence(parent),
        "parameters": copy.deepcopy(full_route_features.PRIOR),
        "parameter_names": list(full_route_features.PARAMETERS),
        "solver_requested_config": copy.deepcopy(solver_config),
        "training": copy.deepcopy(training),
        "source_files": source_files(),
        "full_route_contract": copy.deepcopy(full_route_features.CONTRACT),
        "score_semantics": (
            "validated_parent_score_plus_fixed_complete_public_route_topology_utility_"
            "not_win_probability"
        ),
        "calibrated_probability": False,
        "automatic_deployment": False,
    }


class FullRoutePolicy(SelectionEffectPolicy):
    def __init__(self, path, *, solver_config, seed, epsilon=0.0):
        wrapper_path = Path(path).resolve()
        wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
        parent = wrapper.get("parent_model") or {}
        parent_path = parent.get("path")
        if not isinstance(parent_path, str) or not Path(parent_path).is_absolute():
            raise DataContractError("Full-route parent model path is invalid")
        parameters = wrapper.get("parameters") or {}
        if (
            wrapper.get("format") != VERSION
            or wrapper.get("parameter_names") != list(full_route_features.PARAMETERS)
            or set(parameters) != set(full_route_features.PARAMETERS)
            or any(
                type(value) not in (int, float)
                or not math.isfinite(value)
                or abs(value) > 4
                for value in parameters.values()
            )
            or parameters != full_route_features.PRIOR
            or wrapper.get("solver_requested_config") != solver_config
            or wrapper.get("source_files") != source_files()
            or wrapper.get("full_route_contract") != full_route_features.CONTRACT
            or wrapper.get("calibrated_probability") is not False
            or wrapper.get("automatic_deployment") is not False
            or file_evidence(parent_path) != parent
        ):
            raise DataContractError("Invalid public full-route artifact")
        super().__init__(parent_path, solver_config=solver_config, seed=seed, epsilon=epsilon)
        self._full_route_path = wrapper_path
        self._full_route_artifact = wrapper
        self._full_route_source = file_evidence(wrapper_path)
        self._full_route_artifact_hash = state_hash(wrapper)
        self._full_route_input = None

    @property
    def provenance(self):
        parent = super().provenance
        return {
            **parent,
            "kind": "search",
            "id": VERSION,
            "version": self._full_route_source["sha256"],
            "policy_source": copy.deepcopy(self._full_route_source),
            "parent_policy_source": copy.deepcopy(parent.get("policy_source")),
            "score_semantics": self._full_route_artifact["score_semantics"],
            "training_method": "complete_public_map_topology_fixed_expert_prior",
            "automatic_deployment": False,
        }

    def set_full_route_input(self, state, value):
        if state.get("decision") == "map_select":
            full_route_features.validate_input(state, value)
            self._full_route_input = copy.deepcopy(value)
        else:
            if value is not None:
                raise DataContractError("Non-map decision cannot use full route input")
            self._full_route_input = None

    def _full_route_adjust(self, state, packet):
        if (
            file_evidence(self._full_route_path) != self._full_route_source
            or state_hash(self._full_route_artifact) != self._full_route_artifact_hash
            or self._full_route_artifact["source_files"] != source_files()
            or file_evidence(self._full_route_artifact["parent_model"]["path"])
            != self._full_route_artifact["parent_model"]
        ):
            raise DataContractError("Full-route sources changed after loading")
        packet = full_route_features.adjust(
            state,
            packet,
            self._full_route_input,
            self._full_route_artifact["parameters"],
        )
        packet.update(
            policy_id=VERSION,
            policy_version=self._full_route_source["sha256"],
            full_route_policy_source=copy.deepcopy(self._full_route_source),
            parent_policy_version=super().provenance["version"],
            score_semantics=self._full_route_artifact["score_semantics"],
        )
        return packet

    def score(self, state, candidates=None, *, selection_purpose=None):
        return self._full_route_adjust(
            state,
            super().score(state, candidates, selection_purpose=selection_purpose),
        )

    def score_requests(self, state, requests, *, selection_purpose=None):
        return self._full_route_adjust(
            state,
            super().score_requests(state, requests, selection_purpose=selection_purpose),
        )
