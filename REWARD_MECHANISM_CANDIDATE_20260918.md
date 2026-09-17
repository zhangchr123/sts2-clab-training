# Current reward-mechanism candidate (2026-09-18)

## Scope

This candidate extends the source-closed encounter-damage parent with card
reward semantics that the existing policy explicitly marked as missing.  It is
bound to the current exported English descriptions, current public card stats,
and engine SHA-256.  It uses a fixed expert prior and does not fit weights from
run outcomes.

The candidate is validated offline and is not deployed.  It must wait for the
progress, event-effect, selection-effect, full-route, and encounter-damage
parent gates before a prospective evaluation can be queued.

## Frozen feature-gap audit

The audit covers 95 clean natural Defect A10 runs.  One environment-error run
is listed and excluded.

- 1,496 card-reward decisions and 4,488 offered-card rows.
- 223 distinct offered card IDs.
- 2,838 rows lacked mechanism coverage before this candidate.
- 366 rows lacked current-card-stat coverage.
- 331 rows lacked card-effect semantics and 232 lacked energy-effect
  semantics.
- Near the target, 259 decisions and 777 offered-card rows remain available;
  their missing counts include 488 mechanism, 76 current-stat, 43 card-effect,
  and 47 energy-effect markers.

The feature-gap artifact SHA-256 is
`cad6c6e4d318981d4106b90eaebdd1f197cce088f3257b5c7e9c414d6974ea48`.

## Current description-bound facts

`reward_mechanism_facts.py` binds 43 card facts to exact normalized current
descriptions and required public stat keys.  The current card table SHA-256 is
`c469a0be87d57c1476b75a5d0d3031cebf47e65d380a4646aae0028a20c993c0`;
the current engine SHA-256 is
`14b57dbaee1b58cb919625a662831054fd714b3b75b13b7449eac0e95b98a3e4`.
Description or stat-schema drift fails closed.

Covered semantics include draw, immediate and next-turn energy, weak and
vulnerable, fixed orb channels, fixed multihit counts, generated-status burden,
orb slots, Strength/Dexterity, discard retrieval, exhaust control, and several
explicit conditional hooks.  Future enemy count, combat duration, orb count,
draw-pile composition, and other dynamic quantities remain marked as future
uncertainty rather than being invented.

The v2 feature contract prevents duplicate credit where the parent already
models a mechanism.  In particular, it does not reapply Turbo's generated
status cost, Hologram's discard retrieval, fixed orb channels on already known
cards, or Defragment's Focus value.  Chill receives credit for one guaranteed
enemy and retains `future_enemy_count`.

## Frozen offline behavior replay

Replay artifact SHA-256:
`24f9f8a562c22eabed85148a3f3603bd3e04c75b11916371e9c711683b5b6413`.

- Exact additive reconstruction: 1,496 / 1,496 decisions and 6,008 candidate
  rows.
- Covered candidate rows: 3,102.
- Greedy set changed on 74 decisions (4.95%): 45 card-to-card, 17 skip-to-take,
  and 12 take-to-skip.
- Act changes: 55 / 834 in Act 1, 18 / 561 in Act 2, and 1 / 101 in Act 3.
- Deck-size strata: all 74 changes occurred at 25 cards or fewer; none occurred
  in the 26--36 or over-36 strata.
- Adjustment range: -0.36 to +1.20; mean absolute adjustment 0.06440; no cap
  hits.
- Missing mechanism rows fell from 2,838 to 756; current-stat rows from 366 to
  149; card-effect rows from 331 to 110; energy-effect rows from 232 to 68.

The three earlier Turbo take-to-skip changes disappear in v2.  Parent-covered
Turbo, Hologram, Cold Snap, and Defragment effects receive zero new adjustment;
they can still appear in a changed offer when another candidate receives a
valid new adjustment.

## Source-closed assembly

The complete baseline -> event -> selection -> full-route -> encounter-damage
-> reward chain was rebuilt in an isolated stage.  The historical association
prior was copied byte-for-byte into that stage and bound at SHA-256
`4f7bd5e4b6ce92a56054b2dde47abc2b334f714787083f13ea7606c7887764e4`.
The replay also reproduces the public whole-run Reflections/Shatter latch, so
special builds keep the user-requested whole-run deck-size exception.

All 1,496 reward decisions and 6,008 candidate rows matched the recorded parent
and the candidate's additive score exactly.  Maximum parent error and maximum
additive error are both 0.0.  The assembled candidate SHA-256 is
`01ea47f3bcb0f299f6a98fa8c3048cf54d0f159a3d095d204992919551bd713a`;
the assembled replay receipt SHA-256 is
`3ea56736eff4318980eeac038bac17c21465cbe0464f31b9e42dddc06d0d9470`.
The prospective sampling factory constructs the model as
`whole-run-current-reward-mechanisms-v2` with automatic deployment disabled.

## Limits and gate state

This replay proves source binding, missing-feature reduction, exact parent
equivalence, and fixed-prior behavior.  It does not prove a higher third-act
first-boss success rate.  Act 3 has only 101 replayed reward decisions and one
changed greedy set.  Dynamic conditional effects remain deliberately
unresolved.  The candidate remains `validated_not_deployed` until every parent
gate passes and a separately declared prospective evaluation is admitted.
