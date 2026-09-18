"""Validated wrapper for current-engine deterministic and public random event outcomes."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from decision_data import DataContractError, enumerate_candidates, materialize_candidate, state_hash
from rest_heal_route_policy import RestHealRoutePolicy
from run_metadata import file_evidence
import event_outcome_features


VERSION = "whole-run-current-engine-event-outcomes-v2"
ROOT = Path(__file__).resolve().parent
OWN_SOURCES = (
    "event_outcome_facts.json",
    "event_outcome_features.py",
    "event_outcome_policy.py",
)


def source_files():
    result = {name: file_evidence(ROOT / name) for name in OWN_SOURCES}
    for name, value in event_outcome_features.source_evidence().items():
        prefix = "reference_facts/" if name.startswith("bridge/") else "reference_facts/current_engine/"
        result[prefix + name] = value
    return result


def make_artifact(parent_model, solver_config, *, training):
    parent = Path(parent_model).resolve()
    if not parent.is_file():
        raise DataContractError("Event-outcome parent model is missing")
    return {
        "format": VERSION,
        "parent_model": file_evidence(parent),
        "solver_requested_config": copy.deepcopy(solver_config),
        "training": copy.deepcopy(training),
        "source_files": source_files(),
        "facts": file_evidence(event_outcome_features.FACTS_PATH),
        "event_outcome_contract": copy.deepcopy(event_outcome_features.CONTRACT),
        "score_semantics": "validated_parent_plus_source_bound_event_expected_utility_not_win_probability",
        "calibrated_probability": False,
        "automatic_deployment": False,
    }


class EventOutcomePolicy(RestHealRoutePolicy):
    def __init__(self, path, *, solver_config, seed, epsilon=0.0):
        wrapper_path = Path(path).resolve()
        wrapper = json.loads(wrapper_path.read_text(encoding="utf-8"))
        parent = wrapper.get("parent_model") or {}
        parent_path = parent.get("path")
        if not isinstance(parent_path, str) or not Path(parent_path).is_absolute():
            raise DataContractError("Event-outcome parent path is invalid")
        if (
            wrapper.get("format") != VERSION
            or wrapper.get("solver_requested_config") != solver_config
            or wrapper.get("source_files") != source_files()
            or wrapper.get("facts") != file_evidence(event_outcome_features.FACTS_PATH)
            or wrapper.get("event_outcome_contract") != event_outcome_features.CONTRACT
            or wrapper.get("calibrated_probability") is not False
            or wrapper.get("automatic_deployment") is not False
            or file_evidence(parent_path) != parent
        ):
            raise DataContractError("Invalid deterministic event-outcome artifact")
        super().__init__(parent_path, solver_config=solver_config, seed=seed, epsilon=epsilon)
        self._event_outcome_path = wrapper_path
        self._event_outcome_artifact = wrapper
        self._event_outcome_source = file_evidence(wrapper_path)
        self._event_outcome_artifact_hash = state_hash(wrapper)

    @property
    def provenance(self):
        parent = super().provenance
        return {
            **parent,
            "kind": "search",
            "id": VERSION,
            "version": self._event_outcome_source["sha256"],
            "policy_source": copy.deepcopy(self._event_outcome_source),
            "parent_policy_source": copy.deepcopy(parent.get("policy_source")),
            "score_semantics": self._event_outcome_artifact["score_semantics"],
            "training_method": "current_engine_source_bound_event_utility_and_exact_public_reward_distribution",
            "automatic_deployment": False,
        }

    def _verify_event_outcome_sources(self):
        if (
            file_evidence(self._event_outcome_path) != self._event_outcome_source
            or state_hash(self._event_outcome_artifact) != self._event_outcome_artifact_hash
            or self._event_outcome_artifact["source_files"] != source_files()
            or self._event_outcome_artifact["facts"] != file_evidence(event_outcome_features.FACTS_PATH)
            or file_evidence(self._event_outcome_artifact["parent_model"]["path"])
            != self._event_outcome_artifact["parent_model"]
        ):
            raise DataContractError("Event-outcome sources changed after loading")

    def _score_public_future_reward(self, state, cards):
        """Score the exact public upgraded pool as the later skippable reward.

        This calls the admitted parent directly, so the hypothetical reward is
        evaluated with the same deck discipline and acquisition policy without
        recursively applying this event wrapper.
        """
        synthetic = copy.deepcopy(state)
        synthetic["type"] = "decision"
        synthetic["decision"] = "card_reward"
        synthetic["cards"] = copy.deepcopy(cards)
        synthetic["can_skip"] = True
        synthetic["gold_earned"] = 0
        for key in ("options", "event_name", "event_id", "description"):
            synthetic.pop(key, None)
        requests = [
            {"cmd": "action", "action": "select_card_reward",
             "args": {"card_index": card["index"]}}
            for card in synthetic["cards"]
        ]
        requests.append({"cmd": "action", "action": "skip_card_reward"})

        # Event decisions cannot legitimately carry any of these route inputs,
        # but preserve object state even if a caller violates that expectation.
        names = ("_route_input", "_full_route_input", "_encounter_damage_input",
                 "_rest_route_input")
        saved = {name: copy.deepcopy(getattr(self, name, None)) for name in names}
        try:
            for name in names:
                if hasattr(self, name):
                    setattr(self, name, None)
            packet = RestHealRoutePolicy.score_requests(self, synthetic, requests)
        finally:
            for name, value in saved.items():
                if hasattr(self, name):
                    setattr(self, name, value)

        rows = packet.get("scores") or []
        skip = next((row for row in rows
                     if (row.get("request") or {}).get("action") == "skip_card_reward"), None)
        if skip is None or type(skip.get("score")) not in (int, float):
            raise DataContractError("Future of Potions synthetic reward lacks skip score")
        result = {}
        by_index = {card["index"]: card for card in synthetic["cards"]}
        for row in rows:
            request = row.get("request") or {}
            if request.get("action") != "select_card_reward":
                continue
            index = (request.get("args") or {}).get("card_index")
            card = by_index.get(index)
            if card is None or type(row.get("score")) not in (int, float):
                raise DataContractError("Future of Potions synthetic reward row differs")
            result[card["id"]] = float(row["score"]) - float(skip["score"])
        return result

    def _event_outcome_adjust(self, state, packet):
        self._verify_event_outcome_sources()
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
        packet = event_outcome_features.adjust(self, state, packet, candidates)
        packet.update(
            policy_id=VERSION,
            policy_version=self._event_outcome_source["sha256"],
            event_outcome_policy_source=copy.deepcopy(self._event_outcome_source),
            parent_policy_version=super().provenance["version"],
            score_semantics=self._event_outcome_artifact["score_semantics"],
        )
        return packet

    def score(self, state, candidates=None, *, selection_purpose=None):
        return self._event_outcome_adjust(
            state,
            super().score(state, candidates, selection_purpose=selection_purpose),
        )

    def score_requests(self, state, requests, *, selection_purpose=None):
        return self._event_outcome_adjust(
            state,
            super().score_requests(state, requests, selection_purpose=selection_purpose),
        )
