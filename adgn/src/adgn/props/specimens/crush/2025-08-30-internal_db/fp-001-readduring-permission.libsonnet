local I = import '../../lib.libsonnet';

// fp-001-readduring-permission
// False positive: double-read before vs after permission request in internal/llm/tools/write.go

I.falsePositive(
  rationale=|||
    A past critique flagged the two reads surrounding the permission gate in write.go as an
    "unnecessary re-read". This is a false positive. The first read is a lightweight early
    equality check to short-circuit a no-op; the subsequent read (after directory creation and
    before permission request) populates oldContent for canonical diff/history recording. 

    Keeping these reads separate is defensible: if permission.Request blocks (user prompt) the
    file may change in the meantime and re-reading after the permission decision ensures the
    recorded history reflects the state at the time of the write. Therefore this pattern should
    not be flagged as an issue. Leave as-is.
  |||,
  filesToRanges={
    'internal/llm/tools/write.go': [[148, 151], [161, 167], [174, 182]],
  },
)
