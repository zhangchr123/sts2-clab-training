# Public encounter-damage route candidate (2026-09-18)

## Scope

This candidate adds a damage-burden term to the already validated complete
public-route topology candidate.  It sees only the current public HP, public
act, already revealed map node types, and public map edges.  It does not use
encounter identity, hidden `?` outcomes, future rewards, terminal run outcome,
or a simulated future deck as policy inputs.

The candidate is validated offline and is not deployed.  It must wait for the
predeclared progress, event-effect, selection-effect, and full-route parent
gates before any prospective evaluation can be queued.

## Frozen damage catalog

- Evidence: 95 clean natural Defect A10 runs; one environment-error run was
  excluded.
- Known public encounter rows: 1,344.
- Public `Unknown` combats excluded from known-node fitting: 133.
- Run-grouped deterministic split: 64 train runs / 19 validation runs / 12
  held-out test runs, or 888 / 266 / 190 encounter rows.
- Selection: smoothing was selected only by validation mean pinball loss from
  the fixed candidates `0, 5, 10, 20, 40, 80`; validation selected `0`.
- Final fit: train plus validation only after selection.  Test rows were never
  used to select smoothing or policy weights.
- Catalog artifact SHA-256:
  `ada21748c09c039627fa4e395b471e7e2d541aa67633aab93518bea2a3f3886d`.

Held-out overall metrics over 190 rows:

| Metric | Value |
| --- | ---: |
| Mean pinball across q50/q75/q90 | 0.04648 |
| Median prediction MAE | 0.11408 |
| q50 coverage | 54.74% |
| q75 coverage | 71.58% |
| q90 coverage | 86.84% |

The test mean pinball loss beats the strongest tested low-dimensional baseline
(node-type only: 0.04831), as well as act-only (0.07682) and global (0.07785).
The margin over node type alone is small.

Third-act elite and boss cells are sparse and under-covered.  The held-out
Act 3 first-boss cell has only 5 rows, median MAE 0.30578, and q50/q75/q90
coverage of 20% / 40% / 60%.  The held-out Act 3 elite cell has 6 rows, median
MAE 0.31820, and q50/q75/q90 coverage of 16.67% / 33.33% / 50%.  These cells
cannot support a direct win-rate claim.  The route utility therefore remains a
fixed conservative candidate behind prospective gates.

## Route feature and fixed prior

For every currently selectable map node, dynamic programming computes known
damage q50/q75/q90 ranges to the first public rest or act boss and to the act
boss.  Unknown rooms add no invented damage and remain explicitly unresolved.
The fixed expert prior penalizes expected and upper-tail damage, damage beyond
current HP, and known damage more strongly at low HP.  Each candidate's total
adjustment is capped at absolute value 2.0.  No replay outcome was used to fit
or select these weights.

## Offline behavior replay

Replay artifact SHA-256:
`63d05a2352759fd4581c93ee08cf1763f58c3549ad3b6a0131f9f848a8ef5495`.

- 2,805 map decisions and 4,529 candidate rows replayed.
- Exact additive score reconstruction: 2,805 / 2,805 decisions.
- Complete / partial / unavailable route observations: 2,661 / 142 / 2.
- Greedy choice changed relative to the full-route parent in 98 decisions
  (3.49%).
- Among changes, 88 moved to lower q75 known damage before the next rest or
  boss, 9 had equal q75 minimum but improved other damage terms, and 1 raised
  the q75 minimum while sharply reducing q75 maximum and damage to the boss.
- Act 3: 5 changes over 213 decisions; all 5 moved to lower q75 damage before
  the next rest or boss.
- Adjustment range: -2.0 to 0.0; mean absolute adjustment 0.42256.
- 102 / 4,529 candidate rows (2.25%) reached the declared cap.
- The known encounter-damage missing marker was cleared for covered rows only;
  98 path-unavailable candidate rows retained it.

This replay proves source use, additivity, and the direction of fixed-prior
behavior.  It does not prove a higher Act 3 first-boss success rate.

The source-closed assembled wrapper was then reconstructed with a path-migrated
copy of the admitted parent chain and replayed again.  All 2,805 decisions and
4,529 candidate rows matched exactly; maximum additive error and maximum
recorded-parent error were both 0.0.  The assembled candidate SHA-256 is
`de9e2638256038f202262f3c2106f78336f0856a11e4a6d189aad5a5ae4efb66`.
The assembled replay receipt SHA-256 is
`9ea185d4c125cf2a2829426153dd8b568e7f5e98e96e645ffd16f0f37ab46338`.

## Gate state

The candidate remains `validated_not_deployed`.  A live paired evaluation may
be created only after its entire declared parent chain has independently
passed.  Sparse Act 3 cells remain a material limitation to inspect in that
prospective evaluation.
