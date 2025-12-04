local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Lines 244-265 in reducer.py define `NotificationsHandler(BaseHandler)` that overrides 7 event
    methods (`on_response`, `on_error`, `on_user_text`, `on_assistant_text`, `on_tool_call`,
    `on_tool_result`, `on_reasoning`) that all just `return None`. Base class already provides these
    no-op defaults.

    This creates unnecessary code (7 methods × 3 lines = 21 lines of no-ops), maintenance burden
    (must sync with base class changes), false signal (suggests methods do something different from
    base), and misleading comment ("Event forwarding (typed, observer-only)" but they just return None).

    Delete the 7 no-op method overrides (lines 244-265). Keep only `__init__` and `on_before_sample`
    which have actual implementation. Subclasses should override only what they specialize, not what
    returns base defaults. Saves 21 lines, clear intent (only overrides what matters), standard pattern,
    self-documenting (missing overrides signal "uses base behavior").
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/reducer.py': [
      [244, 265],  // 7 unnecessary no-op method overrides
    ],
  },
)
