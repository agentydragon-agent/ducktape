local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The optimize_with_gepa function returns tuple[str, Any] where the second element
    is typed as Any. This should be replaced with a concrete type for the GEPA result,
    likely the return type of gepa.optimize(). Using Any loses type safety and IDE support.
  |||,
  filesToRanges={'adgn/src/adgn/props/gepa/gepa_adapter.py': [[373, 373], [394, 394], [406, 406]]},
)
