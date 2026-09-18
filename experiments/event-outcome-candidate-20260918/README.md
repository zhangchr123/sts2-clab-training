# Deterministic event-outcome candidate (2026-09-18)

## Scope

This candidate extends the frozen rest-heal and route model with exact
current-engine outcomes for three event families:

- `BUGSLAYER`: add the exact unupgraded `Exterminate` or `Squash` card.
- `SELF_HELP_BOOK`: select an eligible public deck card, then apply Sharp 2,
  Nimble 2, or Swift 2 with the current engine semantics.
- `THIS_OR_THAT:PLAIN`: retain the already computed public HP/gold score and
  classify the resolved option as deterministic.

The facts are bound to the current `sts2.dll` SHA-256
`14b57dbaee1b58cb919625a662831054fd714b3b75b13b7449eac0e95b98a3e4`
and to copied ILSpy sources with fixed hashes. Recorded outcomes, hidden RNG,
future states, and fitted policy weights are not used.

Random branches remain unresolved. In particular, this candidate does not
claim to solve Trial, Doll Room, Reflections, Colorful Philosophers, or The
Future of Potions.

## Fixed utility

`Bugslayer` uses the existing parent scales for total damage per cost,
Vulnerable, area damage, card acquisition opportunity cost, and duplicate
copies. Under those fixed scales, Exterminate scores `0.43` and Squash scores
`0.39` before later wrappers. The small difference comes from exact current
card numbers rather than a run-outcome fit.

`Self Help Book` evaluates every eligible public deck target and selects the
best target utility for each visible option:

- Sharp adds 2 powered-attack damage per verified hit;
- Nimble adds 2 Block, including the parent's current-health defense scale;
- Swift draws 2 cards on the first play of the enchanted Power each combat.

The wrapper replaces the generic parent enchant score for these exact options.
It keeps an explicit `event_card_value_calibration` limitation.

## Frozen replay

The final model was replayed over all 667 event decisions in the same 95 clean
Defect A10 runs used by the residual audit.

- 105 source-bound deterministic option rows were covered.
- All 105 removed the incorrect generic `event_outcome_probability_model`
  marker.
- 53 decisions contained at least one covered option.
- 34 decisions changed their greedy set.
- Parent plus wrapper reconstruction had maximum absolute error `0.0`.
- Random and unmodeled options retained their uncertainty markers.

The final model SHA-256 is
`2f9744038e092b6c9de264026531c953560c264d2c044fccde67d5b6db700485`.
The final replay receipt SHA-256 is
`a54e1124a52df78b6b3eaac10ff43cfa782d9d3156e6946b76f49a21483c9514`.

## The Future of Potions finding

The event's option index is source-proven to align with the first three public
potion slots, so the sacrificed potion can be identified without guessing.
The event chooses the reward card type before the decision, but the current
bridge exports the option description with unresolved placeholders and does
not expose the chosen type. The pool also depends on unlocked Defect cards,
which are not present in the public state. A later expected-value model must
either export those two public decision facts or explicitly marginalize over a
source-bound unlock set; this candidate leaves the option unresolved.

## Gate state

Status is `validated_not_deployed`. This replay proves source binding,
deterministic classification, score additivity, and behavior changes on the
frozen corpus. It does not prove a higher third-act first-boss success rate.
Prospective evaluation waits for the admitted parent chain and must remain
separate from the currently running progress-auxiliary evaluation.
