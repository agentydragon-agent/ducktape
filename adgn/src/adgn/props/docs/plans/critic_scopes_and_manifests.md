# Per-Snapshot Manifest Files (Future Plan)

**Status:** Proposed
**Date:** 2025-12-10

## Context

Currently, snapshot metadata is centralized in two YAML files:
- `snapshots.yaml` - source, split, bundle metadata for all snapshots
- `critic_scopes.yaml` - critic scope specifications for all snapshots

This works but has scaling issues:
- Two central files grow unboundedly
- Merge conflicts when multiple authors work on different snapshots
- Scope definitions separated from snapshots they describe
- Easy to forget adding scopes for new snapshots

## Proposed Structure

### Per-Snapshot Manifest

```
specimens/
  ducktape/
    2025-11-20-00/
      manifest.yaml        # All snapshot metadata in one file
      issues/
        *.libsonnet        # Issue definitions
      code/                # Source code (plain files)
        ...
```

### Manifest Schema

```yaml
# specimens/ducktape/2025-11-20-00/manifest.yaml

# Source definition (same as snapshots.yaml)
source:
  vcs: local
  root: code

# Split assignment (same as snapshots.yaml)
split: train

# Historical provenance (same as snapshots.yaml bundle field)
bundle:
  source_commit: b729b362de957d127d1e8ac17d8811665ce805fe
  include: [adgn/, wt/]
  exclude: [adgn/src/adgn/agent/web/, ...]

# Critic scopes (moved from critic_scopes.yaml)
critic_scopes:
  # Server initialization and lifecycle issues
  - files: [src/agent/server.py]

  # Approval hub logic and state management
  - files: [src/agent/approvals.py]

  # Check for duplicated type definitions across layers
  - files: [src/mcp/types.py, src/mcp/persist.py]

  # UI component patterns and style consistency
  - files: [src/agent/web/src/components/*.svelte]
```

## Benefits

1. **Co-location**: All snapshot metadata in one place
2. **Atomic changes**: Update metadata alongside issue definitions
3. **No merge conflicts**: Different snapshots in different files
4. **Discoverability**: Obvious where to add scopes for new snapshots
5. **Validation**: Easier to enforce "every snapshot must have scopes"

## Migration Path

1. Add loader support for per-snapshot manifests (fallback to central YAMLs)
2. Migrate existing snapshots one at a time
3. Once all migrated, make per-snapshot manifests required
4. Remove central `snapshots.yaml` and `critic_scopes.yaml`

## Implementation Notes

- Support both formats during migration (loader tries manifest first, falls back to central)
- Validation enforces completeness (every snapshot must have source, split, scopes)
- File patterns in scopes expand via glob at load time
- Preserve bundle field for provenance (historical metadata only)

## Open Questions

- Should we also move specimen docs (covered.md, not_covered_yet.md) into manifest?
- How to handle shared scopes across similar snapshots (e.g., all ducktape snapshots)?
- Should split be mandatory in manifest or optional with default?

## Status

**Not yet implemented.** This is a future enhancement to improve scaling and maintainability as the specimens dataset grows.

Current workflow (centralized YAMLs) works fine for ~10 snapshots. Consider this migration when:
- Merge conflicts become frequent
- We exceed ~50 snapshots
- Multiple people actively authoring specimens
