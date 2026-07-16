Ways to improve raw marker detection, from least disruptive to more robust:

  ## 1. Return confidence/debug data, not just progress

  Current read_progress() returns only:

  float | None

  That hides why a detection was accepted. We should make locate_marker() expose:

  {
    "progress": float,
    "box": tuple,
    "score": float,
    "method": "color" | "edge",
  }

  Then recorder/debug can log when bad splits happen:

  progress=0.04 score=0.28 method=edge

  This is the first thing I would do. Without detection telemetry, we are tuning blind.

  ## 2. Raise the bar for edge fallback

  The edge fallback is useful for light backgrounds, but also risky because it can match unrelated skill-background edges.

  Improvements:

  - Use edge fallback only if the match is inside a plausible progress-bar band.
  - Require stronger score for edge fallback.
  - Require the edge match to agree roughly with the previous accepted progress.
  - Reject edge matches that imply a huge backwards jump during an active level.

  This is likely where the current false-low detections come from.

  ## 3. Match the whole progress-bar region, not only the cookie marker

  Right now we search for the marker alone. During skills, the marker can be hard to distinguish from background effects.

  Better: detect a larger visual structure:

  progress bar track + marker + surrounding UI

  Advantages:

  - Lower false-positive risk.
  - The progress bar’s UI location is stable.
  - Background effects behind the cookie matter less if the surrounding HUD/track is included.

  Tradeoff:

  - Requires new template(s).
  - More sensitive to UI skin/theme changes if cropped too wide.

  ## 4. Use multiple marker templates

  Instead of one progress_marker.png, keep templates for different visual states:

  progress_marker_normal.png
  progress_marker_skill_light.png
  progress_marker_skill_glow.png

  Then match all and take the best valid result.

  Advantages:

  - Simple.
  - Works if the marker appearance changes predictably.

  Tradeoff:

  - Needs captures from the failure cases.
  - Can still false-match if validation is weak.

  ## 5. Track motion over time instead of detecting each frame independently

  This is probably the most important architectural fix.

  Progress is not arbitrary per frame. It moves smoothly left-to-right. So raw detection should be filtered by a tracker:

  previous progress + estimated speed + new raw detection -> accepted/rejected progress

  Reject cases like:

  0.91 -> 0.06 while still in same visible gameplay state

  unless there is evidence of an actual level transition.

  This does not replace detection; it makes detection sane.

  ## 6. Use optical flow / local tracking after first lock

  Once the marker is found reliably, track that visual patch frame-to-frame instead of re-template-matching the whole strip every frame.

  Advantages:

  - More stable during transient effects.
  - Less likely to jump to a wrong location.

  Tradeoff:

  - More code.
  - Needs recovery when tracking is lost.

  ## 7. Detect level transitions from separate evidence

  Instead of relying on progress wrap alone, detect actual transitions:

  - level banner appears
  - progress bar disappears/reappears
  - screen fade/transition
  - result screen / next level UI
  This is probably the right fix for end detection, but not raw marker detection itself.

  ## 8. Use game memory / internal state

  - Higher complexity.
  - More brittle.
  - More invasive.
  - Outside the current WGC + ADB architecture.

  ## Recommended path

  I would do this in order:

  1. Add detection telemetry:
      - method
      - score
      - box
      - raw progress
      - accepted/rejected reason

  2. Save a small debug CSV during recording:

  time, raw_progress, accepted_progress, method, score, state, reason

  3. Add a progress validator:
      - reject big backward jumps during active level
      - reject edge fallback if it jumps too far from expected progress
      - only allow wrap/end after transition-like evidence

  4. Improve marker templates only after we inspect bad debug frames.

  Most likely root fix:

  raw detection + temporal validation

  not just more thresholds.