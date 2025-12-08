local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The `_start_container` function returns `dict[str, Any]` wrapping the container ID, but all call sites immediately extract `["Id"]` from the dict. This unnecessary dict wrapper weakens types:
    - Function returns `dict[str, Any]` instead of `str`
    - State field `container` is `dict[str, Any] | None` instead of `container_id: str | None`
    - All usages perform dict access `container["Id"]` instead of working with the string directly

    The dict wrapper serves no purpose and makes the code less type-safe. The function should return `str` (the container ID) directly, and the state field should store `container_id: str | None`.
  |||,
  filesToRanges={'adgn/src/adgn/mcp/_shared/container_session.py': [[136, 153]]},
)
