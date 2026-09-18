"""Validate the event wrapper against a real exported Future of Potions state."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from decision_data import DataContractError, enumerate_candidates
from event_outcome_policy import EventOutcomePolicy
import event_outcome_features as features
from rest_heal_route_policy import RestHealRoutePolicy
from run_metadata import file_evidence


def require(condition, message):
    if not condition:
        raise DataContractError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_probe(path):
    states = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("decision") == "event_choice" and row.get("event_name") == "The Future of Potions?":
            states.append(row)
    require(len(states) == 1, "Expected one live Future of Potions state")
    return states[0]


def greedy(packet):
    best = max(row["score"] for row in packet["scores"])
    return sorted(row["candidate_id"] for row in packet["scores"]
                  if math.isclose(row["score"], best, rel_tol=0.0, abs_tol=1e-12))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    state = read_probe(args.probe)
    artifact = read(args.model)
    config = artifact["solver_requested_config"]
    parent = RestHealRoutePolicy(artifact["parent_model"]["path"],
                                 solver_config=config, seed="live-future-probe", epsilon=0.0)
    candidate = EventOutcomePolicy(args.model, solver_config=config,
                                   seed="live-future-probe", epsilon=0.0)
    space = enumerate_candidates(state)
    require(space.get("representation") == "explicit_v1", "Live event candidates are not explicit")
    requests = [row["request"] for row in space["candidates"]]
    require(len(requests) == 2, "Live probe option count differs")
    parent_packet = parent.score_requests(state, requests)
    candidate_packet = candidate.score_requests(state, requests)
    before = {row["candidate_id"]: row for row in parent_packet["scores"]}
    after = {row["candidate_id"]: row for row in candidate_packet["scores"]}
    require(before.keys() == after.keys(), "Live candidate space differs from parent")

    expected = {(0, "Common", "Skill", 8), (1, "Rare", "Power", 9)}
    observed = set()
    rows = []
    maximum_additivity_error = 0.0
    for candidate_id, row in after.items():
        parent_row = before[candidate_id]
        detail = row.get("event_outcome_detail") or {}
        value = detail.get("value_detail") or {}
        option_index = row["request"]["args"]["option_index"]
        observed.add((option_index, value.get("target_rarity"), value.get("target_type"),
                      value.get("filtered_pool_size")))
        require(detail.get("applied") is True, "Live Future option was not applied")
        require(detail.get("kind") == "public_precommitted_random_card_reward",
                "Live Future option used the wrong handler")
        error = abs(row["score"] - (parent_row["score"] + row["event_outcome_adjustment"]))
        maximum_additivity_error = max(maximum_additivity_error, error)
        require(error <= 1e-12, "Live Future score is not additive")
        missing = set(row.get("missing") or [])
        require("event_outcome_probability_model" not in missing
                and "unmodeled_event_effect" not in missing,
                "Resolved live Future option retained a generic missing marker")
        require("future_potions_card_reward_hook_calibration" in missing,
                "Live Future option lost its explicit calibration limitation")
        rows.append({
            "candidate_id": candidate_id,
            "request": row["request"],
            "parent_score": parent_row["score"],
            "candidate_score": row["score"],
            "adjustment": row["event_outcome_adjustment"],
            "missing": row.get("missing") or [],
            "detail": detail,
        })
    require(observed == expected, "Live Future pool binding differs")

    # Exercise every currently possible public rarity/type pool on this same
    # real state. This fixes the cap against all eight legal distributions,
    # rather than only the two random branches emitted by the captured event.
    losses = {"Common": 0.25, "Uncommon": 0.35, "Rare": 0.50}
    envelope = []
    for rarity in ("Common", "Uncommon", "Rare"):
        for card_type in ("Attack", "Skill", "Power"):
            pool = [card for card in features.REWARD_POOL
                    if card["rarity"] == rarity and card["type"] == card_type]
            if len(pool) < features.CONTRACT["future_potions_reward_count"]:
                continue
            cards = [features._upgraded_reward_card(card, index)
                     for index, card in enumerate(pool)]
            values = candidate._score_public_future_reward(state, cards)
            expected_best = features._expected_best_of_three(
                [values[card["id"]] for card in cards]
            )
            exact_score = expected_best - losses[rarity]
            adjustment = exact_score - (-0.25)
            require(abs(adjustment) <= features.CONTRACT["candidate_adjustment_abs_cap"],
                    "All-pool live envelope exceeds the fixed cap")
            envelope.append({
                "rarity": rarity,
                "type": card_type,
                "pool_size": len(pool),
                "expected_best_card_delta_from_skip": expected_best,
                "exact_score": exact_score,
                "adjustment_from_parent_minus_0_25": adjustment,
                "minimum_single_card_delta": min(values.values()),
                "maximum_single_card_delta": max(values.values()),
            })
    require(len(envelope) == 8, "Expected all eight legal Future reward pools")

    result = {
        "schema_version": "future-potions-live-policy-probe-v1",
        "passed": True,
        "model": file_evidence(args.model.resolve()),
        "parent": artifact["parent_model"],
        "probe": file_evidence(args.probe.resolve()),
        "engine_sha256": features.ENGINE_SHA256,
        "event_state_hash": space["state_hash"],
        "rows": rows,
        "greedy_before": greedy(parent_packet),
        "greedy_after": greedy(candidate_packet),
        "maximum_additivity_error": maximum_additivity_error,
        "all_pool_envelope": envelope,
        "maximum_all_pool_adjustment": max(
            abs(row["adjustment_from_parent_minus_0_25"]) for row in envelope
        ),
        "candidate_adjustment_abs_cap": features.CONTRACT["candidate_adjustment_abs_cap"],
        "interpretation": {
            "real_bridge_state": True,
            "public_option_variables_only": True,
            "hidden_rng_or_future_state_used": False,
            "win_probability_calibrated": False,
            "automatic_deployment": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({
        "passed": True,
        "rows": rows,
        "greedy_before": result["greedy_before"],
        "greedy_after": result["greedy_after"],
        "maximum_additivity_error": maximum_additivity_error,
        "maximum_all_pool_adjustment": result["maximum_all_pool_adjustment"],
        "candidate_adjustment_abs_cap": result["candidate_adjustment_abs_cap"],
    }, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
