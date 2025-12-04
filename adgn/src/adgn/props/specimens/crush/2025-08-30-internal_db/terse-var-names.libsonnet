local I = import '../../lib.libsonnet';


I.issueMulti(
  rationale= |||
    Ambiguous or overly terse local/var names reduce readability. Prefer descriptive names that encode units/meaning (e.g., address/storedAddr, compressEnabled, CRUSH_PROFILE env var semantics).
  |||,
  occurrences=[
    { files: { 'internal/profile/profile.go': [{ start_line: 5, end_line: 17 }] }, note: 'addr atomic.Value stored as `v`; prefer naming like storedAddr/address in accessors to avoid confusion.', expect_caught_from: [['internal/profile/profile.go']] },
    { files: { 'internal/profile/server.go': [{ start_line: 33, end_line: 46 }] }, note: 'v variable read from CRUSH_PROFILE is ambiguous; syscall/env var pstr should be named pprofPortStr or similar.', expect_caught_from: [['internal/profile/server.go']] },
    { files: { 'e2e/setup_helpers.go': [{ start_line: 70, end_line: 76 }] }, note: 'bool `b` used to set Wire.Compress; rename to compressEnabled to highlight units/purpose.', expect_caught_from: [['e2e/setup_helpers.go']] },
  ],
)
