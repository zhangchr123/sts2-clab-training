# Current-engine event-outcome candidate v3 (2026-09-18)

## Scope

This candidate extends the frozen rest-heal and route parent with four
source-bound event families:

- `BUGSLAYER`: add the exact unupgraded `Exterminate` or `Squash` card;
- `SELF_HELP_BOOK`: value the best eligible public deck target for Sharp 2,
  Nimble 2, or Swift 2 with current-engine semantics;
- `THIS_OR_THAT:PLAIN`: retain the public HP/gold score and classify the
  already resolved option as deterministic;
- `THE_FUTURE_OF_POTIONS:POTION`: value the exact public precommitted card
  rarity/type distribution and the potion sacrificed by the option.

All facts are bound to current `sts2.dll` SHA-256
`14b57dbaee1b58cb919625a662831054fd714b3b75b13b7449eac0e95b98a3e4`.
The candidate uses public state and fixed current-engine source facts. It does
not inspect hidden RNG, recorded outcomes, or future states.

## The Future of Potions

The bridge now preserves public localization variables from every event
option. A live current-engine probe exported the two generated options as:

- Attack Potion -> upgraded Common Skill;
- Entropic Brew -> upgraded Rare Power.

The event source proves that an option aligns with the first three nonempty
public potion entries, offers three distinct cards uniformly without
replacement from the precommitted rarity/type pool, upgrades every offered
card, and permits skipping the later reward.

The exact current Defect A10 single-player unlocked pool contains 86 cards and
every card has a successful current-engine upgrade preview. For each option,
the wrapper scores every upgraded card with the admitted parent card-reward
policy, computes the exact expectation of the best nonnegative choice among
all three-card combinations, and subtracts a fixed potion opportunity cost.

On the real bridge state, the parent assigned both choices `-0.25`. The new
scores are `2.464294587390279` for the Common Skill option and
`3.810227756933843` for the Rare Power option, so the latter becomes the sole
greedy choice. The complete eight-pool live envelope has maximum adjustment
`4.060227756933843`, below the fixed fail-closed cap of `4.5`.

Known public reward-modifying relics cause this handler to remain unresolved.
Historical states that predate option-variable export also remain unresolved;
the wrapper never infers the precommitted card type from the later outcome.

## Validation

The bridge patch built successfully and the required headless regression
completed 25/25 natural runs: five terminating runs for each of Ironclad,
Silent, Defect, Regent, and Necrobinder, with no failures. Those random-agent
runs validate bridge termination and do not measure policy strength.

Nine focused unit tests cover exact source-bound cards, public option binding,
missing historical variables, potion mismatch rejection, modifying-relic
fail-closed behavior, malformed facts, and unchanged random options.

The final candidate was replayed over all 667 event decisions in the same 95
clean Defect A10 runs used by the frozen residual audit:

- 105 historical source-bound option rows were covered;
- all 105 removed the generic event-outcome probability marker;
- 53 decisions contained a covered option;
- 34 decisions changed their greedy set;
- parent-plus-wrapper reconstruction had maximum absolute error `0.0`;
- old Future of Potions rows remained unresolved because their public option
  variables are absent.

Artifact hashes:

- candidate model: `906d75bf6adc285df1f4835c2099420252e946849608dbc4143ea85101dc45a3`;
- frozen replay: `e89cdc69e87307393f21bcd7c739f1d61fb44fb87177dd7e376243a342867ba1`;
- live full-policy probe: `7e89a000590c2362a1e8cc87d09d8973554bc5809338dd174c99a188add935d0`.

## Gate state

Status is `validated_not_deployed`. The fixed card and potion utilities are
relative policy scores, not calibrated win probabilities. The 86-card pool is
bound to the current headless unlock state, and unlisted card-reward hooks are
not claimed to be modeled. Prospective evaluation must wait for the admitted
parent chain and use a separately declared clean trial. No current formal
evaluation runtime or deployed model was modified.
