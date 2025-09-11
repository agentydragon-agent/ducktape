local obj = {
  id: "iss-010",
  should_flag: true,
  rationale: |||
    Repeated periodic progress-logging block.

    The same 3-line progress-logging snippet is duplicated in four places inside
    gather_files_single_pass. Extract a small helper to reduce duplication,
    make intent obvious, and avoid copy/paste drift.

    Before (examples taken verbatim from the specimen):

    ```python
    if progress and time.monotonic() - last_print >= 1.0:
        sys.stderr.write(
            f"scan dirs={scanned_dirs} files={scanned_files} kept={len(kept_union)} at {rp}\n",
        )
        sys.stderr.flush()
        last_print = time.monotonic()
    ```

    After (recommended helper and call sites):

    ```python
    def maybe_log_progress(scanned_dirs, scanned_files, kept_union, rp, last_print, progress) -> float:
        """Log periodic progress and return updated last_print."""
        if progress and time.monotonic() - last_print >= 1.0:
            sys.stderr.write(
                f"scan dirs={scanned_dirs} files={scanned_files} kept={len(kept_union)} at {rp}\n",
            )
            sys.stderr.flush()
            return time.monotonic()
        return last_print

    # call sites (replace the duplicated block):
    last_print = maybe_log_progress(scanned_dirs, scanned_files, kept_union, rp, last_print, progress)
    ```
  |||,
  properties: ['no-oneoff-vars-and-trivial-wrappers'],
  instances: [
    { files: { "pyright_watch_report.py": [ { start_line: 123, end_line: 132 } ] } },
    { files: { "pyright_watch_report.py": [ { start_line: 142, end_line: 150 } ] } },
    { files: { "pyright_watch_report.py": [ { start_line: 151, end_line: 158 } ] } },
    { files: { "pyright_watch_report.py": [ { start_line: 162, end_line: 167 } ] } },
  ],
};

obj
