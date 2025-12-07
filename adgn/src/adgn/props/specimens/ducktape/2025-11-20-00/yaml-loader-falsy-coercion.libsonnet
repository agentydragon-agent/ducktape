local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    _load_yaml coerces any falsy YAML payload to {} before the type check (line 35:
    `data = yaml.safe_load(f) or {}`). This means non-mapping presets like [], 0, false, or None
    are silently treated as empty mappings, bypassing the isinstance(data, dict) check on line 36
    that should raise "preset must be a mapping". The `or {}` should be removed - let yaml.safe_load
    return whatever it returns, and let the isinstance check fail naturally for non-dict values.
    This hides malformed presets and causes downstream validation errors instead of clear early
    failures.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/presets.py': [[35, 35]],
  },
)
