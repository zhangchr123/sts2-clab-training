# Public selection-effect candidate

This candidate extends the frozen public event-effect policy with fixed utility
for canonical card-upgrade previews. It applies only to `card_select` decisions
whose public selection purpose is `upgrade`. Remove, transform, enchant, acquire,
and every non-selection decision receive an exact zero adjustment.

The scorer uses only the current public card and its public `after_upgrade`
preview. It values cost reduction, damage, block, draw, energy, Weak,
Vulnerable, Focus, Strength, Dexterity, Buffer, repeat/loop/scaling changes,
keyword removal, Retain, and Innate. It does not assume copied instance
modifiers, inspect hidden rewards or future state, or fit weights from natural
outcomes. Each candidate adjustment is capped at an absolute value of 3.

Offline replay covers 95 valid natural runs, 91 upgrade decisions, and 3,604
candidate score rows. All 91 decisions passed exact additivity. The fixed prior
changed the greedy set on 46 decisions, reduced mean greedy-set size from 2.736
to 1.352, and increased the median top-two margin from 0.005 to 0.175. Manual
review found the common shifts were from ordinary numeric attack/block upgrades
to public cost, energy, draw, Focus, and scaling upgrades. Recorded actions and
outcomes were not changed, and these diagnostics make no win-rate claim.

The offline replay SHA-256 is
`aa56b783c8fd95e961f202e0f5a47fb91152905a0893fe448ee7d5684b692e80`.
The isolated candidate model SHA-256 is
`af1539d4c85ca4bd340ac2d8fe315a05ce719672ffbef5034f5a438891afc983`.
The assembled wrapper independently reproduced the migrated event parent on
all 91 decisions and 3,604 rows before adding the selection adjustment. Its
combined replay SHA-256 is
`bbe3d588570ae6fd31b7d844d06481e413399667b36fe7fd8f1d62ca38921487`.

This candidate has not run a prospective natural-game smoke or paired
evaluation and is not deployed. Its parent event-effect candidate is itself
still waiting behind the active progress-auxiliary paired evaluation. Any later
live trial must use new seeds, preserve failures, prohibit retries and fitting,
and remain gated on the parent event candidate's independent result.

`sts2-selection-effect-smoke-handoff.service` now waits for that independent
parent assessment. It prepares and runs exactly one fresh-seed smoke only when
the parent assessment is complete and its candidate improvement gate passed.
If the parent is rejected, its smoke fails, or the assessment is unavailable
after the parent chain terminates, the selection smoke is not run and the
continuous goal remains active. The handoff never retries a started allocation.

If that one-game smoke passes its complete integration audit, the same handoff
prepares and starts a frozen 60-pair, 120-game evaluation against the admitted
event parent. Each pair shares a fresh seed, arm order alternates for 30 pairs
each, invalid games remain failures, and the first pair is an integration gate.
The evaluation cannot retry, refit, extend its denominator, or deploy either
model. A separate assessor recomputes the exact paired test and verifies all
audit receipts and raw-source hashes before exposing a bounded result to the
persistent MiniMax goal.
