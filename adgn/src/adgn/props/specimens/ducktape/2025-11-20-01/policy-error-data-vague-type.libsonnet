local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    The `PolicyGatewayError` model (lines 33-37) has a `data: dict[str, Any] | None`
    field that's too vague.

    Field name "data" is generic; type `dict[str, Any]` provides no guidance on
    structure/contents; no documentation. Usage (line 136) checks for
    POLICY_GATEWAY_STAMP_KEY, but this isn't reflected in type or name. Unclear what
    other fields exist besides stamp key.

    **Fix options:**
    1. Create typed model `PolicyGatewayErrorData` with `_policy_gateway_stamp: bool`
       field (plus other discovered fields), use as type
    2. Add Field description documenting exact contents (must contain stamp key, list
       other specific fields)
    3. Rename to more specific name (e.g., `mcp_error_metadata`)

    Don't add generic documentation like "data associated with the error". Real
    documentation requires understanding what actually gets stored and documenting
    specifics.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/policy_gateway/signals.py': [
      [33, 37],   // PolicyGatewayError model with vague 'data' field
      [133, 133], // Line extracting data from error_data
      [136, 136], // Line checking for POLICY_GATEWAY_STAMP_KEY in data
      [142, 142], // Line passing data to PolicyGatewayError constructor
    ],
  },
)
