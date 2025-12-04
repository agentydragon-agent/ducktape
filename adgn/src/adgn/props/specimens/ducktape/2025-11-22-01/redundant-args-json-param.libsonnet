local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 261-265 define `_invoke()` with parameters `function_call: FunctionCallItem` and
    `args_json: str | None`. Call sites (lines 305, 334) always pass `args_json` as
    `function_call.arguments`, making it redundant. Lines 276-280 parse `args_json` but could
    use `function_call.arguments` directly.

    This creates data duplication (same data passed twice), cognitive load (reader must verify
    args_json matches function_call.arguments), and potential inconsistency (nothing enforces
    equality). Arguments already accessible via function_call object.

    Remove `args_json` parameter from `_invoke()` signature (lines 261-265). Replace `if args_json:`
    check (line 277) with `if function_call.arguments:`. Update call sites (lines 305, 334) to pass
    only `function_call`. Establishes single source of truth, simpler signature, and type safety.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/agent.py': [
      [261, 265],  // _invoke signature with redundant args_json
      [276, 280],  // Usage of args_json (could use function_call.arguments)
      [305, 305],  // Call site passing fc.arguments redundantly
      [334, 334],  // Call site passing function_call.arguments redundantly
    ],
  },
)
