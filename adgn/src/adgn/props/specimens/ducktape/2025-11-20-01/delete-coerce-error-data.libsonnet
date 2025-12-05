local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 62-93 define _coerce_error_data that tries to coerce various error representations
    to mtypes.ErrorData with extensive defensive fallbacks. Lines 56-60 define a Protocol
    for attribute-based fallback. This overly defensive function should be deleted entirely.

    Problems: swallows validation errors and tries manual construction (lines 75-85), has
    attribute-based fallback for objects with .code/.message (lines 87-92), mixes validation
    with data extraction, violates fail-fast principle, makes debugging harder.

    Delete _coerce_error_data and _ErrorFields Protocol. Replace three usage sites (lines
    116, 119, 122) with direct mtypes.ErrorData.model_validate() calls. If data doesn't
    match schema, Pydantic raises clear validation errors instead of silently constructing
    minimal ErrorData or returning None.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/policy_gateway/signals.py': [
      [56, 60],   // _ErrorFields protocol - should be deleted
      [62, 93],   // Entire _coerce_error_data function - should be deleted
      [116, 116], // Usage in detect_policy_gateway_error
      [119, 119], // Usage in detect_policy_gateway_error
      [122, 122], // Usage in detect_policy_gateway_error
    ],
  },
)
