"""Validated wrapper adding source-bound merchant relic and potion utility."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from decision_data import DataContractError, enumerate_candidates, materialize_candidate, state_hash
from event_outcome_policy import EventOutcomePolicy
import merchant_item_features
from run_metadata import file_evidence


VERSION = "whole-run-source-bound-merchant-items-v1"
ROOT = Path(__file__).resolve().parent
OWN_SOURCES = (
    "merchant_item_facts.json",
    "merchant_item_features.py",
    "merchant_item_policy.py",
    "reference_facts/sts2_db.json",
    "reference_facts/relics.json",
    "reference_facts/potions.json",
)


def source_files():
    return {name: file_evidence(ROOT / name) for name in OWN_SOURCES}


def make_artifact(parent_model, solver_config, *, training):
    parent = Path(parent_model).resolve()
    if not parent.is_file():
        raise DataContractError("Merchant item parent model is missing")
    return {
        "format": VERSION,
        "parent_model": file_evidence(parent),
        "solver_requested_config": copy.deepcopy(solver_config),
        "training": copy.deepcopy(training),
        "source_files": source_files(),
        "facts": file_evidence(merchant_item_features.FACTS_PATH),
        "merchant_item_contract": copy.deepcopy(merchant_item_features.CONTRACT),
        "score_semantics": "validated_parent_plus_source_bound_merchant_item_utility_not_win_probability",
        "calibrated_probability": False,
        "automatic_deployment": False,
    }


class MerchantItemPolicy(EventOutcomePolicy):
    def __init__(self, path, *, solver_config, seed, epsilon=0.0):
        wrapper_path = Path(path).resolve()
        wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
        parent = wrapper.get("parent_model") or {}
        parent_path = parent.get("path")
        if not isinstance(parent_path, str) or not Path(parent_path).is_absolute():
            raise DataContractError("Merchant item parent path is invalid")
        if (
            wrapper.get("format") != VERSION
            or wrapper.get("solver_requested_config") != solver_config
            or wrapper.get("source_files") != source_files()
            or wrapper.get("facts") != file_evidence(merchant_item_features.FACTS_PATH)
            or wrapper.get("merchant_item_contract") != merchant_item_features.CONTRACT
            or wrapper.get("calibrated_probability") is not False
            or wrapper.get("automatic_deployment") is not False
            or file_evidence(parent_path) != parent
        ):
            raise DataContractError("Invalid merchant item artifact")
        super().__init__(parent_path, solver_config=solver_config, seed=seed, epsilon=epsilon)
        self._merchant_item_path = wrapper_path
        self._merchant_item_artifact = wrapper
        self._merchant_item_source = file_evidence(wrapper_path)
        self._merchant_item_artifact_hash = state_hash(wrapper)

    @property
    def provenance(self):
        parent = super().provenance
        return {
            **parent,
            "kind": "search",
            "id": VERSION,
            "version": self._merchant_item_source["sha256"],
            "policy_source": copy.deepcopy(self._merchant_item_source),
            "parent_policy_source": copy.deepcopy(parent.get("policy_source")),
            "score_semantics": self._merchant_item_artifact["score_semantics"],
            "training_method": "current_engine_source_bound_items_fixed_public_state_prior",
            "automatic_deployment": False,
        }

    def _verify_merchant_item_sources(self):
        if (
            file_evidence(self._merchant_item_path) != self._merchant_item_source
            or state_hash(self._merchant_item_artifact) != self._merchant_item_artifact_hash
            or self._merchant_item_artifact["source_files"] != source_files()
            or self._merchant_item_artifact["facts"]
            != file_evidence(merchant_item_features.FACTS_PATH)
            or file_evidence(self._merchant_item_artifact["parent_model"]["path"])
            != self._merchant_item_artifact["parent_model"]
        ):
            raise DataContractError("Merchant item sources changed after loading")

    def _merchant_item_adjust(self, state, packet):
        self._verify_merchant_item_sources()
        space = enumerate_candidates(state)
        by_id = None if space.get("representation") == "ordered_selection_implicit_v1" else {
            candidate["candidate_id"]: candidate for candidate in space["candidates"]
        }
        candidates = {
            row["candidate_id"]: (
                materialize_candidate(space, row["request"])
                if by_id is None else by_id[row["candidate_id"]]
            )
            for row in packet["scores"]
        }
        packet = merchant_item_features.adjust(state, packet, candidates)
        packet.update(
            policy_id=VERSION,
            policy_version=self._merchant_item_source["sha256"],
            merchant_item_policy_source=copy.deepcopy(self._merchant_item_source),
            parent_policy_version=super().provenance["version"],
            score_semantics=self._merchant_item_artifact["score_semantics"],
        )
        return packet

    def score(self, state, candidates=None, *, selection_purpose=None):
        return self._merchant_item_adjust(
            state,
            super().score(state, candidates, selection_purpose=selection_purpose),
        )

    def score_requests(self, state, requests, *, selection_purpose=None):
        return self._merchant_item_adjust(
            state,
            super().score_requests(state, requests, selection_purpose=selection_purpose),
        )

