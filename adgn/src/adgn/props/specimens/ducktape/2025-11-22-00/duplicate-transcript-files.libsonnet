local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    `TranscriptHandler` writes the same events to two nearly-identical files: `events.jsonl`
    (with timestamps) and `transcript.jsonl` (without timestamps). Lines 38-39 define both
    paths, lines 53-57 write to both files on every event.

    **Problems:**
    1. Redundant storage: same data written twice, only difference is timestamp wrapper
    2. Confusing naming: two files with similar names containing nearly identical content
    3. Performance overhead: double I/O operations for every event
    4. Storage waste: doubles disk usage for large transcripts
    5. Unclear purpose: which file should tools read?

    **Fix:** Choose one format. Keep the timestamped format (`events.jsonl`) as primary since
    it preserves temporal information (timestamps are useful for debugging, analysis, replay;
    you can strip them if needed but can't add them back). Remove `_transcript_path` and the
    second write. If both formats are needed, generate the compact format on-demand from the
    timestamped one via an `export_compact_transcript()` method. Benefits: single source of
    truth, half the I/O, no redundant data, easier maintenance.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/transcript_handler.py': [
      [38, 39],   // Both _events_path and _transcript_path defined
      [41, 42],   // Only checks _events_path.exists()
      [53, 57],   // Double write: events.jsonl and transcript.jsonl
    ],
  },
)
