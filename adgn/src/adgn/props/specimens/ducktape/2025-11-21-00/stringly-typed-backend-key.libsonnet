local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Line 80 declares `_backend_apps: dict[str, ASGIApp]` with string keys. Lines 93-108 construct
    string keys ("human" or f"agent:{agent_id}") from strongly-typed TokenInfo discriminators, then
    use these strings for dict lookups.

    Stringly-typed keys lose type safety (typos in format strings uncaught), fragility (adding new
    TokenInfo types requires remembering string format), and IDE support (no autocomplete/refactoring).
    The match statement already discriminates on TokenInfo types; converting to strings duplicates
    this discrimination in a weaker form.

    Use TokenInfo directly as dict keys: change to `dict[TokenInfo, ASGIApp]` and replace `backend_key`
    string construction with `token_info` directly. Requires making HumanTokenInfo and AgentTokenInfo
    frozen Pydantic models (`model_config = ConfigDict(frozen=True)`) so they're hashable and can serve
    as dict keys. This preserves type information throughout the caching layer.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/mcp_routing.py': [
      [80, 80],   // _backend_apps dict with string keys
      [93, 108],  // _get_backend_app method creating string keys
      [38, 41],   // HumanTokenInfo - needs frozen=True
      [44, 48],   // AgentTokenInfo - needs frozen=True
    ],
  },
)
