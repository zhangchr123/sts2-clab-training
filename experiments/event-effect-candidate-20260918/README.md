# Public event-effect candidate

This candidate adds fixed expert utility for public event outcomes to the
validated parent acquisition policy.  It reads the public event title,
description, referenced variables, the exact engine event catalog, and Ancient
relic identity.  It does not read hidden rewards, future state, or natural run
outcomes, and it leaves the existing gold and HP risk scoring unchanged.

The final catalog contains 66 events, 157 options, and 102 Ancient relics.  Its
SHA-256 is `e07aa9f039196b9cb4ba1fa6e45d010e2da4c2be9d796503704d2e7354ad6549`.
The engine DLL bound by the catalog has SHA-256
`14b57dbaee1b58cb919625a662831054fd714b3b75b13b7449eac0e95b98a3e4`.

Coverage analysis over 95 valid natural runs found 667 event decisions and
1,597 actionable options.  The final offline replay reduced fully uniform
event decisions from 520 to 114, changed the greedy set on 448 decisions, and
reduced mean greedy-set size from 2.174 to 1.312.  These are score-impact
diagnostics only: recorded actions and outcomes were not changed, and no win
rate claim follows from them.

The assembled wrapper reproduced the migrated parent exactly before applying
the event adjustment on all 667 decisions.  All 667 candidate decisions passed
the exact-additivity check.  Its combined replay SHA-256 is
`c2e65d4d653a0b7ae17f74180c665fc6c21e409fc848ef8cd1c3952dcefeb78b`.

The candidate model SHA-256 is
`29cfd41a47dab503565404a97c9574a6c1cae91b9db6df38308a8f3260826f31`.
An isolated one-game smoke protocol is frozen with SHA-256
`9e1ca3ec2a5f4bb8d05d72d41907ef281786e3d49f93c18aba0090c804da1030`.
It uses one new seed, cannot retry, and is ineligible for fitting, selection,
sample extension, or automatic deployment.  A systemd handoff waits for the
active progress-auxiliary paired evaluation to finish, acquires a clean sampling
boundary, and runs this smoke once.

If and only if the smoke passes its full integration audit, the same serialized
handoff starts a frozen 60-pair, 120-game natural evaluation.  The paired
protocol SHA-256 is
`01c7db5ac45b8bb5f39098045503a56e2be39564a48ed403bccb307a790cc579`.
Each pair shares one new seed, control and candidate run first in 30 pairs each,
invalid games remain failures, and the first pair is an integration gate.  The
trial cannot retry, refit, extend its sample, or automatically deploy.  The
continuous goal resumes after the paired service reaches either success or
failure.  A separate read-only assessor then recomputes the paired statistics,
checks all 120 audit receipts and the raw source closure, and exposes only a
bounded verified summary to the MiniMax goal driver.
