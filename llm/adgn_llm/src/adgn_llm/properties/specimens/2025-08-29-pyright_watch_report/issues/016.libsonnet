local obj = {
  should_flag: true,
  rationale: |||
    Prefer Path.write_text for concise dump writing when appropriate.

    The code currently writes out the dumped file with an explicit open + loop which is fine,
    but when the whole file content can be constructed in memory the `Path.write_text`
    helper is shorter and clearer.

    Before:
    ```python
    with dump_path.open("w", encoding="utf-8") as f:
        for p in sorted(kept_union):
            f.write(str(p) + "\n")
    ```

    After (shorter):
    ```python
    dump_path.write_text("\n".join(str(p) for p in sorted(kept_union)), encoding="utf-8")
    ```

    Note: this is appropriate when the dumped content comfortably fits in memory. If the list
    can be very large (streaming required), keep the streaming form; prefer clarity over micro-optimizations.
  |||,
  // properties: [],
  instances: [{ files: { 'pyright_watch_report.py': [{ start_line: 292, end_line: 299 }] } }],
};

obj
