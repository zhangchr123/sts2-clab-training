# Merchant-item isolated smoke and paired evaluation

This archive contains the frozen integration and evaluation harness for the source-bound merchant relic and potion candidate. The allocation uses one fresh Defect A10 smoke seed and, only after that gate passes, 60 prospectively allocated paired seeds (120 games). Pair order alternates; invalid arms remain failures in the fixed denominator. The improvement gate requires more candidate-only Act 3 first-boss successes and exact one-sided paired p <= 0.05.

Neither run may retry a started seed, fit or select from natural outcomes, extend its denominator, or deploy automatically. The handoff waits for the active continuous-training batch to end at a clean boundary, runs the gates, and resumes the persistent MiniMax goal after any terminal result. At this commit both protocols are prepared and no smoke or paired-evaluation game has started.

The paired evaluation now has a separate one-shot assessor. It independently verifies the fixed allocation, audit receipts, raw source closure, model and policy binding, merchant packet readback, paired statistics, and the no-deployment contract. The handoff waits for this terminal assessment and then resumes the continuous goal whether the candidate passes, fails, or the assessment itself reports an error.
