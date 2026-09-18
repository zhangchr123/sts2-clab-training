# Rest-heal and future-route candidate (2026-09-18)

## Scope

This candidate extends the source-closed reward-mechanism parent with exact
public Rest healing and downstream public-route damage risk. It uses only the
public player state, the audited map observation that selected the Rest Site,
current public relic variables, and the frozen encounter-damage catalog. It
does not use hidden encounters, hidden rewards, run outcomes, or fitted policy
weights.

The candidate is validated offline and is not deployed. It must wait for the
progress, event-effect, selection-effect, full-route, encounter-damage, and
reward-mechanism parent gates before a prospective evaluation can be queued.

## Frozen gap audit

The audit covers 95 clean natural Defect A10 runs. One environment-error run is
listed and excluded.

- 412 Rest Site decisions: 354 recorded Heal actions and 58 Smith actions.
- All 412 parent decisions explicitly lacked both `actual_rest_heal_amount` and
  `future_route_damage_distribution`.
- The exact public healing formula matched the observed post-Rest state on all
  354 / 354 Heal actions.
- The formula applies `floor(0.30 * old_max_hp)`, public `REGAL_PILLOW.vars.Heal`,
  and public `STONE_HUMIDIFIER.vars.MaxHp`, then caps current HP at the new
  maximum HP.
- All 58 / 58 Smith actions left immediate current and maximum HP unchanged.
- The selected public Rest Site and pre-Rest map matched the later Rest state on
  all 412 / 412 decisions.

For the best available downstream branch, the median frozen damage q75 to the
next stop was 0.45038 and q90 was 0.62612. The median q75-to-boss burden was
0.89191. Unknown room outcomes remain explicit rather than receiving invented
damage estimates.

The gap-audit artifact SHA-256 is
`6ce16e053a22939b3750f221c89b1f2d2f323733b3e3e7511faa28431914d348`.
The current relic table SHA-256 is
`7379d2f141bc507fad392fd38d6d718667c6f55df5d2f6ce50ed0f5649403183`.

## Fixed public-risk prior

Only Heal receives a new adjustment. The score measures how much the exact
projected heal closes the downstream damage shortfall under three fixed public
route summaries:

- q75 damage to the next stop, weight 1.00;
- q90 damage to the next stop, weight 0.70;
- q75 damage to the boss, weight 0.20.

The absolute adjustment is capped at 1.0. A route already safe at current HP
gets no new benefit, and missing or unknown routes stay unresolved. The parent
policy continues to decide the ordinary Heal-versus-Smith tradeoff outside the
covered public risk.

## Frozen offline behavior replay

Replay artifact SHA-256:
`d506d5277bb1eddc9b81fac6462b7808555dce9a562c73a9dff3d8a82dbd6ed9`.

- Exact additive reconstruction: 412 / 412 Rest decisions and 907 candidate
  rows.
- Covered Heal rows: 412.
- Greedy set changed on 7 decisions (1.70%), all from Smith to Heal.
- Act changes: 2 / 232 in Act 1, 4 / 150 in Act 2, and 1 / 30 in Act 3.
- Adjustment range: 0.0 to 0.93733; mean absolute adjustment 0.09676; no cap
  hits.
- The two covered missing markers fell from 412 to 0. Public-route unknowns
  remain explicit on 188 rows.

## Source-closed assembly

The complete baseline -> event -> selection -> full-route -> encounter-damage
-> reward-mechanism -> rest-heal route chain was rebuilt in an isolated stage.
The replay reproduced the public whole-run Reflections/Shatter deck-size latch
and replayed 2,805 public map observations in their original per-run order.

All 412 Rest decisions and 907 candidate rows matched the assembled parent plus
the new adjustment. Maximum additive error was 0.0. Maximum reconstructed
parent error was `1.7763568394002505e-15`, a floating-point rounding residual.
The assembled candidate SHA-256 is
`55b287eb546953267a6ee61a6e81a105179e47e784a050b231e4d99fc056c9b8`;
the assembled replay receipt SHA-256 is
`923e1849ec98881dc926cafa94eba34ec44b6fea86fd81b86adcb5d7321ac4c4`.
The prospective sampling factory constructs the model as
`whole-run-public-rest-heal-route-v1` with automatic deployment disabled.

## Limits and gate state

This replay proves source binding, exact healing, public-map latch continuity,
missing-feature reduction, and additive parent equivalence. It does not prove a
higher third-act first-boss success rate. Only 30 Act 3 Rest decisions were
available, and the candidate changes one of them. The candidate remains
`validated_not_deployed` until every parent gate passes and a separately
declared prospective evaluation is admitted.
