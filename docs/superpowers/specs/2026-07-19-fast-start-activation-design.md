# Fast Start Activation Design

## Goal

Add an opt-in `--fast-start` flag that taps `assets/activate_fast_start.png` during gameplay in every gameplay mode.

## Behavior

Fast Start purchasing during menu setup remains unchanged. Without `--fast-start`, no in-run Fast Start activation check occurs. With the flag, the gameplay runner checks for the activation template during the existing periodic full-screen result and Cookie Relay scan.

After the first successful Fast Start tap, that runner stops checking for the Fast Start template. Gameplay, result-screen detection, Cookie Relay handling, and recorded level replay continue normally.

## Design

`scripts/auto_runner.py` defines `ACTIVATE_FAST_START_TEMPLATE`, parses `--fast-start`, and passes the template to `build_gameplay_runner()` only when the flag is enabled. The existing optional `relay_template` remains separate because Cookie Relay has level-replay-specific behavior that Fast Start must not share.

`LevelReplayer`, `ReactiveRunner`, and `NoneRunner` each accept an optional `fast_start_template`. During their existing every-15th-frame full-screen check, they look for the template until it matches. A match is tapped through the runner's existing input method and marks Fast Start handled so the check is not repeated.

In `LevelReplayer`, Fast Start handling must not change `replay_enabled`, `recorded`, the current tap index, or level progress tracking. Cookie Relay retains its existing behavior of disabling recorded replay after relay activation.

No generic activation-policy abstraction is added.

## Failure Behavior

If the Fast Start template does not appear, gameplay continues until its normal result or timeout condition. A missing match is not an error. Existing gameplay, relay, and result failure behavior remains unchanged.

## Tests

Extend the existing plain-Python self-checks to verify:

- `--fast-start` defaults to false and parses as true when supplied.
- `auto_runner` passes `activate_fast_start.png` to every gameplay mode only when enabled.
- `LevelReplayer`, `ReactiveRunner`, and `NoneRunner` tap Fast Start once and stop checking it afterward.
- level replay remains enabled after Fast Start activation.
- Cookie Relay behavior remains unchanged.

Update `README.md` to document `--fast-start` as opt-in in-run activation.
