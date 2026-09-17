"""Wrapper adding fixed public upgrade-preview utility to the event candidate."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from decision_data import DataContractError, enumerate_candidates, materialize_candidate, state_hash
from event_effect_policy import FEATURE_SOURCES as PARENT_SOURCES, EventEffectPolicy
from run_metadata import file_evidence
import selection_effect_features


VERSION = "whole-run-public-selection-effects-v1"
ROOT = Path(__file__).resolve().parent
FEATURE_SOURCES = tuple(dict.fromkeys((
    *PARENT_SOURCES,
    "selection_effect_features.py",
    "selection_effect_policy.py",
)))


def source_files():
    return {name: file_evidence(ROOT / name) for name in FEATURE_SOURCES}


def make_artifact(parent_model, solver_config, *, training):
    parent = Path(parent_model).resolve()
    if not parent.is_file():
        raise DataContractError("Selection-effect parent model is missing")
    return {
        "format": VERSION,
        "parent_model": file_evidence(parent),
        "parameters": copy.deepcopy(selection_effect_features.PRIOR),
        "parameter_names": list(selection_effect_features.PARAMETERS),
        "solver_requested_config": copy.deepcopy(solver_config),
        "training": copy.deepcopy(training),
        "source_files": source_files(),
        "selection_effect_contract": copy.deepcopy(selection_effect_features.CONTRACT),
        "score_semantics": "validated_parent_score_plus_fixed_public_upgrade_preview_utility_not_win_probability",
        "calibrated_probability": False,
        "automatic_deployment": False,
    }


class SelectionEffectPolicy(EventEffectPolicy):
    def __init__(self, path, *, solver_config, seed, epsilon=0.0):
        wrapper_path = Path(path).resolve()
        wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
        parent = wrapper.get("parent_model") or {}
        parent_path = parent.get("path")
        if not isinstance(parent_path, str) or not Path(parent_path).is_absolute():
            raise DataContractError("Selection-effect parent path is invalid")
        if (
            wrapper.get("format") != VERSION
            or wrapper.get("parameter_names") != list(selection_effect_features.PARAMETERS)
            or set(wrapper.get("parameters") or {}) != set(selection_effect_features.PARAMETERS)
            or any(
                type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 4
                for value in (wrapper.get("parameters") or {}).values()
            )
            or wrapper.get("parameters") != selection_effect_features.PRIOR
            or wrapper.get("solver_requested_config") != solver_config
            or wrapper.get("source_files") != source_files()
            or wrapper.get("selection_effect_contract") != selection_effect_features.CONTRACT
            or wrapper.get("calibrated_probability") is not False
            or wrapper.get("automatic_deployment") is not False
            or file_evidence(parent_path) != parent
        ):
            raise DataContractError("Invalid public selection-effect artifact")
        super().__init__(parent_path, solver_config=solver_config, seed=seed, epsilon=epsilon)
        self._selection_path = wrapper_path
        self._selection_artifact = wrapper
        self._selection_source = file_evidence(wrapper_path)
        self._selection_artifact_hash = state_hash(wrapper)

    @property
    def provenance(self):
        parent = super().provenance
        return {
            **parent,
            "kind": "search",
            "id": VERSION,
            "version": self._selection_source["sha256"],
            "policy_source": copy.deepcopy(self._selection_source),
            "parent_policy_source": copy.deepcopy(parent.get("policy_source")),
            "score_semantics": self._selection_artifact["score_semantics"],
            "training_method": "public_canonical_upgrade_preview_fixed_expert_prior",
            "automatic_deployment": False,
        }

    def _selection_adjust(self, state, packet):
        if (
            file_evidence(self._selection_path) != self._selection_source
            or state_hash(self._selection_artifact) != self._selection_artifact_hash
            or self._selection_artifact["source_files"] != source_files()
            or file_evidence(self._selection_artifact["parent_model"]["path"])
            != self._selection_artifact["parent_model"]
        ):
            raise DataContractError("Selection-effect sources changed after loading")
        space = enumerate_candidates(state)
        by_id = (
            None
            if space.get("representation") == "ordered_selection_implicit_v1"
            else {candidate["candidate_id"]: candidate for candidate in space["candidates"]}
        )
        candidates = {
            row["candidate_id"]: (
                materialize_candidate(space, row["request"])
                if by_id is None
                else by_id[row["candidate_id"]]
            )
            for row in packet["scores"]
        }
        packet = selection_effect_features.adjust(
            state, packet, candidates, self._selection_artifact["parameters"]
        )
        packet.update(
            policy_id=VERSION,
            policy_version=self._selection_source["sha256"],
            selection_policy_source=copy.deepcopy(self._selection_source),
            parent_policy_version=super().provenance["version"],
            score_semantics=self._selection_artifact["score_semantics"],
        )
        return packet

    def score(self, state, candidates=None, *, selection_purpose=None):
        return self._selection_adjust(
            state,
            super().score(state, candidates, selection_purpose=selection_purpose),
        )

    def score_requests(self, state, requests, *, selection_purpose=None):
        return self._selection_adjust(
            state,
            super().score_requests(state, requests, selection_purpose=selection_purpose),
        )
