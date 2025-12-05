local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Line 232 uses uuid4() for test database names. The issue suggests using actual test IDs if available
    from pytest (e.g., request.node.nodeid) and applying a whitelist-based sanitizer (keep alphanumeric/underscore,
    reject special chars) instead of just replacing hyphens. The length limit could also be increased to something
    more reasonable like 128 characters if PostgreSQL allows it.
  |||,
  filesToRanges={
    'adgn/tests/props/conftest.py': [[232, 233]],
  },
)
