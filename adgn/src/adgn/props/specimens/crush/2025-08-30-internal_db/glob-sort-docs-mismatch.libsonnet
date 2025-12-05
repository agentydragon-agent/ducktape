local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Glob tool documentation claims sorting by modification time, but implementation sorts by path length.

    Documentation at line 18 (in tool description shown to LLM agent):
    "returning matching paths sorted by modification time (newest first)"

    Actual implementation at lines 164-166:
    sort.SliceStable(matches, func(i, j int) bool {
        return len(matches[i]) < len(matches[j])
    })

    The code sorts by path length (shortest paths first), not by file modification time. No mtime checking or stat calls are present.

    Impact:
    - Agent receives misleading tool description and may make incorrect planning decisions
    - Agent might expect recently modified files when developing iterative search strategies
    - Agent gets shortest-path-first ordering (e.g., "main.go" before "internal/app/very/nested/file.go")
    - Truncation at 100 files returns shortest paths, not most relevant/recent files

    Fix: Either implement mtime sorting (stat files, sort by mtime desc) or update tool description to accurately describe length-based sorting.
  |||,
  filesToRanges={
    'internal/llm/tools/glob.go': [
      [18, 18],      // Doc claims mtime sorting
      [164, 166],    // Implementation sorts by path length
    ],
  },
)
