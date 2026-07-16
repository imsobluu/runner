# MuMu Launcher Reactive Removal Design

## Goal

Make the MuMu friend-farm launcher finish successfully after tapping
`play_3`, so a later change can hand off to level recording instead of the
reactive runner.

## Scope

Change only `scripts/launch_mumu_cookierun.py`:

- Remove the launcher-only reactive asset and result-template constants.
- Remove `run_reactive_gameplay`.
- Remove reactive parameters from `run_friend_farm_sequence`.
- Return success immediately after the `play_3` template is tapped.
- Remove the reactive friend-farm command-line options and validation.
- Remove reactive arguments from the concurrent friend-farm invocation.

Do not change or delete the general reactive implementation, `auto_runner`
mode, reactive tests, debug scripts, or reactive assets. Do not add level
recording yet.

## Runtime Behavior

MuMu launch, ADB readiness, landscape detection, window arrangement, WGC
capture, and all friend-farm steps through `play_3` remain unchanged. A
successful `play_3` tap completes that instance's friend-farm sequence; a
failed or timed-out tap still fails it. Existing multi-instance aggregation
and exit-code behavior remain unchanged.

## Compatibility

The launcher options `--friend-farm-reactive-assets`,
`--friend-farm-reactive-timeout`, and `--no-friend-farm-reactive` are removed
rather than retained as ignored compatibility flags. Reactive functionality
outside this launcher remains available.

## Verification

- Compile the launcher with `py_compile`.
- Check `--help` succeeds and no longer lists reactive options.
- Search the launcher for stale reactive references.
- Run the smallest relevant existing checks that do not require a live MuMu
  instance.
