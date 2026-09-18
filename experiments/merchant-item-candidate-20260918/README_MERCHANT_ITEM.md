# Source-bound merchant item candidate

This candidate fixes a measured policy blind spot: across 95 clean Defect A10 runs, the parent selected none of 307 potion-purchase, 349 relic-purchase, or 658 potion-discard candidates.

It covers Data Disk, Runic Capacitor, Lee's Waffle, and 11 current-engine potions. Purchase utility keeps the parent's existing gold opportunity cost. Potion discards compare the held potion with affordable visible shop replacements. All coefficients were frozen before replay and reuse existing parent effect scales; natural outcomes were not used to select parameters.

Validation:

- 6 focused unit tests pass.
- 95 clean runs / 403 shop decisions replayed.
- 462 covered rows adjusted and 41 greedy decisions changed.
- New greedy actions: 5 relic purchases, 20 potion purchases, 17 explicit replacements.
- Five real parent/candidate policy probes pass; uncovered actions have zero score drift.
- Maximum absolute adjustment is 3.600, below the fixed 4.5 cap.

Status: offline validated, not deployed. A fresh-seed isolated integration smoke and a predeclared paired evaluation are still required.
