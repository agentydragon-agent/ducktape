local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The .envrc file exports database URLs with hardcoded password `postgres` (lines 28 and 33), but the actual PostgreSQL container (defined in devenv.nix line 40) uses password `props_admin_pass`. This password mismatch breaks database access when code attempts to connect using the environment variables.
  |||,
  filesToRanges={
    'adgn/.envrc': [[28, 33]],
    'adgn/devenv.nix': [40],
  },
  expect_caught_from=[
    ['adgn/.envrc', 'adgn/devenv.nix'],
  ],
)
