"""Wrapper adding fixed current-engine card reward semantics."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from decision_data import DataContractError, state_hash
from encounter_damage_policy import FEATURE_SOURCES as PARENT_SOURCES, EncounterDamagePolicy
import reward_mechanism_features
from reward_mechanism_facts import CONTRACT as FACTS_CONTRACT, verified_source
from run_metadata import file_evidence


VERSION = "whole-run-current-reward-mechanisms-v2"
ROOT = Path(__file__).resolve().parent
FEATURE_SOURCES = tuple(dict.fromkeys((
    *PARENT_SOURCES,
    "current_cards_eng.json",
    "reward_mechanism_facts.py",
    "reward_mechanism_features.py",
    "reward_mechanism_policy.py",
)))


def source_files():
    return {name: file_evidence(ROOT / name) for name in FEATURE_SOURCES}


def make_artifact(parent_model, solver_config, *, training):
    parent = Path(parent_model).resolve()
    if not parent.is_file():
        raise DataContractError("Reward-mechanism parent model is missing")
    return {
        "format": VERSION,
        "parent_model": file_evidence(parent),
        "parameters": copy.deepcopy(reward_mechanism_features.PRIOR),
        "parameter_names": list(reward_mechanism_features.PARAMETERS),
        "solver_requested_config": copy.deepcopy(solver_config),
        "training": copy.deepcopy(training),
        "source_files": source_files(),
        "reward_facts": verified_source(ROOT.parent / "sts2-cli/lib/sts2.dll"),
        "reward_feature_contract": copy.deepcopy(reward_mechanism_features.FEATURE_CONTRACT),
        "score_semantics": "validated_parent_score_plus_fixed_current_reward_semantic_utility_not_win_probability",
        "calibrated_probability": False,
        "automatic_deployment": False,
    }


class RewardMechanismPolicy(EncounterDamagePolicy):
    def __init__(self, path, *, solver_config, seed, epsilon=0.0):
        wrapper_path = Path(path).resolve()
        wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
        parent = wrapper.get("parent_model") or {}
        parent_path = parent.get("path")
        parameters = wrapper.get("parameters") or {}
        if not isinstance(parent_path, str) or not Path(parent_path).is_absolute():
            raise DataContractError("Reward-mechanism parent path is invalid")
        if (
            wrapper.get("format") != VERSION
            or wrapper.get("parameter_names") != list(reward_mechanism_features.PARAMETERS)
            or set(parameters) != set(reward_mechanism_features.PARAMETERS)
            or any(type(value) not in (int, float) or not math.isfinite(value)
                   or abs(value) > 4 for value in parameters.values())
            or parameters != reward_mechanism_features.PRIOR
            or wrapper.get("solver_requested_config") != solver_config
            or wrapper.get("source_files") != source_files()
            or wrapper.get("reward_facts") != verified_source(ROOT.parent / "sts2-cli/lib/sts2.dll")
            or wrapper.get("reward_feature_contract") != reward_mechanism_features.FEATURE_CONTRACT
            or wrapper.get("calibrated_probability") is not False
            or wrapper.get("automatic_deployment") is not False
            or file_evidence(parent_path) != parent
        ):
            raise DataContractError("Invalid reward-mechanism artifact")
        super().__init__(parent_path, solver_config=solver_config, seed=seed, epsilon=epsilon)
        self._reward_path = wrapper_path
        self._reward_artifact = wrapper
        self._reward_source = file_evidence(wrapper_path)
        self._reward_artifact_hash = state_hash(wrapper)

    @property
    def provenance(self):
        parent = super().provenance
        return {
            **parent,
            "kind": "search",
            "id": VERSION,
            "version": self._reward_source["sha256"],
            "policy_source": copy.deepcopy(self._reward_source),
            "parent_policy_source": copy.deepcopy(parent.get("policy_source")),
            "score_semantics": self._reward_artifact["score_semantics"],
            "training_method": "current_engine_description_bound_fixed_expert_prior",
            "automatic_deployment": False,
        }

    def _reward_adjust(self, state, packet):
        if (
            file_evidence(self._reward_path) != self._reward_source
            or state_hash(self._reward_artifact) != self._reward_artifact_hash
            or self._reward_artifact["source_files"] != source_files()
            or self._reward_artifact["reward_facts"] != verified_source(
                ROOT.parent / "sts2-cli/lib/sts2.dll"
            )
            or file_evidence(self._reward_artifact["parent_model"]["path"])
            != self._reward_artifact["parent_model"]
        ):
            raise DataContractError("Reward-mechanism sources changed after loading")
        packet = reward_mechanism_features.adjust(
            state, packet, self._reward_artifact["parameters"]
        )
        packet.update(
            policy_id=VERSION,
            policy_version=self._reward_source["sha256"],
            reward_mechanism_policy_source=copy.deepcopy(self._reward_source),
            parent_policy_version=super().provenance["version"],
            score_semantics=self._reward_artifact["score_semantics"],
        )
        return packet

    def score(self, state, candidates=None, *, selection_purpose=None):
        return self._reward_adjust(
            state, super().score(state, candidates, selection_purpose=selection_purpose)
        )

    def score_requests(self, state, requests, *, selection_purpose=None):
        return self._reward_adjust(
            state,
            super().score_requests(state, requests, selection_purpose=selection_purpose),
        )
