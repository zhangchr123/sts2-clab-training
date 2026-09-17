# Full public-route candidate (2026-09-18)

## Purpose

The live parent already queries the audited public map before every map choice,
but its route residual uses only short summaries such as the nearest rest/shop,
fights before the first rest, and whether an elite can be avoided.  This
candidate adds complete candidate-to-boss topology summaries without opening
rooms, identifying encounters, or predicting damage.

## Fixed candidate

`full_route_features.py` derives, for every currently legal map node:

- minimum and maximum steps to the exported act boss;
- minimum and maximum known fights, elites, rests, and unknown rooms;
- whether every route includes a rest and whether an elite remains optional;
- capped public path flexibility and branch density.

The fixed prior combines these summaries with current public HP and act.  It
penalizes forced fights and elites more strongly at low HP, values reachable
rests, and gives a small value to optionality.  Each candidate adjustment is
capped at an absolute value of 2.  The feature explicitly clears only
`full_route_evaluation`; `encounter_damage_distribution` remains missing.

`full_route_policy.py` is an additive wrapper over the isolated
selection-effect candidate.  It validates the complete source closure, parent
artifact hash, solver configuration, fixed parameters, input state hash, legal
candidate set, and public map hash.  It is not deployed automatically.

## Frozen offline replay

Source: 95 clean natural Defect A10 runs from the original cloud batch and the
first three continuous-goal batches.  The one recorded environment-error run
(`defect-cloud-goal-20260917-000003-018`) is listed and excluded.  Terminal
outcomes were not used for fitting or weight selection; the replay is a
descriptive additivity and behavior audit.

- 2,805 map decisions and 4,529 candidate rows replayed.
- Exact parent-score additivity: 2,805 / 2,805 decisions.
- Greedy set changed: 89 / 2,805 decisions (3.17%).
- Adjustment range: -1.2242 to +0.9217; mean absolute adjustment 0.2197.
- Route availability: 2,661 complete, 142 partial, 2 unavailable.
- Full-route missing rows: 4,481 before, 0 after.
- Encounter-damage missing rows: 4,481 before and 4,481 after.
- Changed choices usually reduce forced elites or minimum fights and increase
  accessible rests or route flexibility.  No change selected an unavailable
  public path.

Replay receipt:
`/home/ubuntu/sts2-cloud-analysis/full-route-candidate-20260918-v1/RESULT.json`

SHA-256: `f36ff8903bae39960b0ac76a607b688f570beff90845c3a6ccc4bf06e16d7b29`

## Verification and status

The isolated Linux stage is
`/home/ubuntu/sts2-full-route-stage-20260918/sts2-solver-bridge`.
Python compilation and 32 focused sampler, audit, feature, and wrapper tests
pass on that stage.  Parent migration and assembled wrapper replay run under a
low-priority, resource-capped service while the declared progress-auxiliary
evaluation owns the live sampling boundary.

This candidate remains development evidence.  It has no prospective natural
game result, makes no win-rate claim, and cannot be deployed before the event
and selection parent chain passes its predeclared smoke, paired evaluation, and
independent assessment gates.
