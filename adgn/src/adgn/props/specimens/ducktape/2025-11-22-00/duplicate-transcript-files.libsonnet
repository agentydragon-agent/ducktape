local I = import '../../lib.libsonnet';

// iss-019: Duplicate transcript files with nearly identical content

I.issue(
  rationale= |||
    `TranscriptHandler` writes the same events to two nearly-identical files:
    `events.jsonl` (with timestamps) and `transcript.jsonl` (without timestamps).
    This duplication is confusing and wasteful - one file format should be chosen.

    **Current implementation (transcript_handler.py, lines 38-57):**
    ```python
    def __init__(self, *, dest_dir: Path) -> None:
        self._root = dest_dir
        self._root.mkdir(parents=True, exist_ok=True)
        self._events_path = self._root / "events.jsonl"
        self._transcript_path = self._root / "transcript.jsonl"
        # Fail fast if a transcript already exists at destination
        if self._events_path.exists():
            raise FileExistsError(f"Transcript already exists: {self._events_path}")

    def _write_event(self, evt: Any) -> None:
        rec = to_jsonl_record(evt)
        # Timestamped envelope (events.jsonl)
        out = {"ts": datetime.now(timezone.utc).isoformat(), **rec}
        with self._events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
        # Compact transcript (transcript.jsonl)
        with self._transcript_path.open("a", encoding="utf-8") as g:
            g.write(json.dumps(rec, ensure_ascii=False) + "\n")
    ```

    **Problems:**

    1. **Redundant storage**: Same data written twice, only difference is timestamp wrapper
    2. **Confusing naming**: Two files with similar names containing nearly identical content
    3. **Maintenance burden**: Must keep both files in sync
    4. **Performance overhead**: Double I/O operations for every event
    5. **Unclear purpose**: Why have both formats? Which one should tools read?
    6. **Storage waste**: For large transcripts, this doubles disk usage

    **The correct approach:**

    Choose one format and stick with it. The timestamped format (`events.jsonl`) is
    more useful since it preserves temporal information:

    ```python
    def __init__(self, *, dest_dir: Path) -> None:
        self._root = dest_dir
        self._root.mkdir(parents=True, exist_ok=True)
        self._events_path = self._root / "events.jsonl"
        # Fail fast if a transcript already exists at destination
        if self._events_path.exists():
            raise FileExistsError(f"Transcript already exists: {self._events_path}")
        (self._root / "metadata.json").write_text(
            json.dumps({"started": datetime.now(timezone.utc).isoformat()}, indent=2),
            encoding="utf-8"
        )

    def _write_event(self, evt: Any) -> None:
        rec = to_jsonl_record(evt)
        # Timestamped envelope
        out = {"ts": datetime.now(timezone.utc).isoformat(), **rec}
        with self._events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
    ```

    **If you need both formats:**

    Generate the compact format on-demand from the timestamped one:

    ```python
    def export_compact_transcript(self, output_path: Path) -> None:
        """Export transcript without timestamps for tools that don't need them."""
        with self._events_path.open("r") as f, output_path.open("w") as g:
            for line in f:
                event = json.loads(line)
                # Remove timestamp wrapper
                event.pop("ts", None)
                g.write(json.dumps(event, ensure_ascii=False) + "\n")
    ```

    **Benefits:**

    1. **Single source of truth**: One file format, no duplication
    2. **Clear naming**: `events.jsonl` clearly indicates timestamped events
    3. **Better performance**: Half the I/O operations
    4. **Less storage**: No redundant data
    5. **Easier maintenance**: Only one format to maintain
    6. **On-demand conversion**: Generate compact format when needed

    **Recommendation:**

    Keep the timestamped format (`events.jsonl`) as the primary transcript format
    because:
    - Timestamps are generally useful for debugging, analysis, and replay
    - You can always strip timestamps if needed (can't add them back)
    - The overhead is minimal (one ISO timestamp string per event)
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/transcript_handler.py': [
      [38, 39],   // Both _events_path and _transcript_path defined
      [41, 42],   // Only checks _events_path.exists()
      [53, 57],   // Double write: events.jsonl and transcript.jsonl
    ],
  },
)
