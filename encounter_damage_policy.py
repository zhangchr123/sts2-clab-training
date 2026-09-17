"""Wrapper adding a frozen public-node encounter-damage distribution."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path

from decision_data import DataContractError, state_hash
import encounter_damage_features
from full_route_policy import FEATURE_SOURCES as PARENT_SOURCES, FullRoutePolicy
from run_metadata import file_evidence


VERSION = "whole-run-public-encounter-damage-v1"
ROOT = Path(__file__).resolve().parent
FEATURE_SOURCES = tuple(
    dict.fromkeys(
        (
            *PARENT_SOURCES,
            "train_encounter_damage_catalog.py",
            "encounter_damage_features.py",
            "encounter_damage_policy.py",
        )
    )
)


def source_files() -> dict[str, dict]:
    return {name: file_evidence(ROOT / name) for name in FEATURE_SOURCES}


def _read_catalog(path: str | Path) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    encounter_damage_features.validate_catalog(value)
    return value


def make_artifact(parent_model: str | Path, catalog_path: str | Path,
                  solver_config: dict, *, training: dict) -> dict:
    parent = Path(parent_model).resolve()
    catalog = Path(catalog_path).resolve()
    if not parent.is_file():
        raise DataContractError("Encounter-damage parent model is missing")
    if not catalog.is_file():
        raise DataContractError("Encounter-damage catalog is missing")
    catalog_value = _read_catalog(catalog)
    return {
        "format": VERSION,
        "parent_model": file_evidence(parent),
        "catalog_artifact": file_evidence(catalog),
        "catalog_schema": catalog_value["schema_version"],
        "parameters": copy.deepcopy(encounter_damage_features.PRIOR),
        "parameter_names": list(encounter_damage_features.PARAMETERS),
        "solver_requested_config": copy.deepcopy(solver_config),
        "training": copy.deepcopy(training),
        "source_files": source_files(),
        "encounter_damage_contract": copy.deepcopy(encounter_damage_features.CONTRACT),
        "score_semantics": (
            "validated_full_route_parent_score_plus_fixed_public_node_damage_burden_"
            "utility_not_win_probability"
        ),
        "calibrated_probability": False,
        "automatic_deployment": False,
    }


class EncounterDamagePolicy(FullRoutePolicy):
    def __init__(self, path, *, solver_config, seed, epsilon=0.0):
        wrapper_path = Path(path).resolve()
        wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
        parent = wrapper.get("parent_model") or {}
        parent_path = parent.get("path")
        catalog_evidence = wrapper.get("catalog_artifact") or {}
        catalog_path = catalog_evidence.get("path")
        parameters = wrapper.get("parameters") or {}
        if not isinstance(parent_path, str) or not Path(parent_path).is_absolute():
            raise DataContractError("Encounter-damage parent model path is invalid")
        if not isinstance(catalog_path, str) or not Path(catalog_path).is_absolute():
            raise DataContractError("Encounter-damage catalog path is invalid")
        if (
            wrapper.get("format") != VERSION
            or wrapper.get("parameter_names") != list(encounter_damage_features.PARAMETERS)
            or set(parameters) != set(encounter_damage_features.PARAMETERS)
            or any(
                type(value) not in (int, float)
                or not math.isfinite(value)
                or abs(value) > 4
                for value in parameters.values()
            )
            or parameters != encounter_damage_features.PRIOR
            or wrapper.get("solver_requested_config") != solver_config
            or wrapper.get("source_files") != source_files()
            or wrapper.get("encounter_damage_contract") != encounter_damage_features.CONTRACT
            or wrapper.get("catalog_schema") != encounter_damage_features.SCHEMA
            or wrapper.get("calibrated_probability") is not False
            or wrapper.get("automatic_deployment") is not False
            or file_evidence(parent_path) != parent
            or file_evidence(catalog_path) != catalog_evidence
        ):
            raise DataContractError("Invalid public encounter-damage artifact")
        catalog = _read_catalog(catalog_path)
        super().__init__(parent_path, solver_config=solver_config, seed=seed, epsilon=epsilon)
        self._encounter_damage_path = wrapper_path
        self._encounter_damage_artifact = wrapper
        self._encounter_damage_source = file_evidence(wrapper_path)
        self._encounter_damage_artifact_hash = state_hash(wrapper)
        self._encounter_damage_catalog = catalog
        self._encounter_damage_catalog_hash = state_hash(catalog)
        self._encounter_damage_input = None

    @property
    def provenance(self):
        parent = super().provenance
        return {
            **parent,
            "kind": "search",
            "id": VERSION,
            "version": self._encounter_damage_source["sha256"],
            "policy_source": copy.deepcopy(self._encounter_damage_source),
            "parent_policy_source": copy.deepcopy(parent.get("policy_source")),
            "catalog_artifact": copy.deepcopy(
                self._encounter_damage_artifact["catalog_artifact"]
            ),
            "score_semantics": self._encounter_damage_artifact["score_semantics"],
            "training_method": "held_out_catalog_plus_fixed_expert_damage_burden_prior",
            "automatic_deployment": False,
        }

    def _verify_encounter_damage_sources(self):
        if (
            file_evidence(self._encounter_damage_path) != self._encounter_damage_source
            or state_hash(self._encounter_damage_artifact) != self._encounter_damage_artifact_hash
            or self._encounter_damage_artifact["source_files"] != source_files()
            or file_evidence(self._encounter_damage_artifact["parent_model"]["path"])
            != self._encounter_damage_artifact["parent_model"]
            or file_evidence(self._encounter_damage_artifact["catalog_artifact"]["path"])
            != self._encounter_damage_artifact["catalog_artifact"]
            or state_hash(_read_catalog(
                self._encounter_damage_artifact["catalog_artifact"]["path"]
            )) != self._encounter_damage_catalog_hash
        ):
            raise DataContractError("Encounter-damage sources changed after loading")

    def make_encounter_damage_input(self, state, observation):
        self._verify_encounter_damage_sources()
        if state.get("decision") != "map_select":
            return None
        return encounter_damage_features.policy_input(
            state, observation, self._encounter_damage_catalog
        )

    def set_encounter_damage_input(self, state, value):
        if state.get("decision") == "map_select":
            encounter_damage_features.validate_input(state, value)
            self._encounter_damage_input = copy.deepcopy(value)
        else:
            if value is not None:
                raise DataContractError("Non-map decision cannot use encounter-damage input")
            self._encounter_damage_input = None

    def _encounter_damage_adjust(self, state, packet):
        self._verify_encounter_damage_sources()
        packet = encounter_damage_features.adjust(
            state,
            packet,
            self._encounter_damage_input,
            self._encounter_damage_artifact["parameters"],
        )
        packet.update(
            policy_id=VERSION,
            policy_version=self._encounter_damage_source["sha256"],
            encounter_damage_policy_source=copy.deepcopy(self._encounter_damage_source),
            encounter_damage_catalog=copy.deepcopy(
                self._encounter_damage_artifact["catalog_artifact"]
            ),
            parent_policy_version=super().provenance["version"],
            score_semantics=self._encounter_damage_artifact["score_semantics"],
        )
        return packet

    def score(self, state, candidates=None, *, selection_purpose=None):
        return self._encounter_damage_adjust(
            state,
            super().score(state, candidates, selection_purpose=selection_purpose),
        )

    def score_requests(self, state, requests, *, selection_purpose=None):
        return self._encounter_damage_adjust(
            state,
            super().score_requests(state, requests, selection_purpose=selection_purpose),
        )
