local obj = {
  should_flag: true,
  rationale: |||
    Progress interval is encoded as a magic float literal `1.0` (seconds) in multiple places, which makes the unit implicit.
    Either:
    (A) Preferred: Use a duration type (e.g., `PROGRESS_INTERVAL = timedelta(seconds=1)`) and compare using datetime consistently (e.g., `last_print: datetime`, `now = datetime.now(timezone.utc)`, and `if now - last_print >= PROGRESS_INTERVAL:`).
    (B) At least add _s / _seconds / similar suffix to make unit unambiguous.

    Original (multiple places):
    ```python
    if progress and time.monotonic() - last_print >= 1.0:
        ...
        last_print = time.monotonic()
    ```

    Better (use datetime consistently for time arithmetic):
    ```python
    PROGRESS_INTERVAL = timedelta(seconds=1)
    last_print = datetime.now(timezone.utc)
    ...
    now = datetime.now(timezone.utc)
    if progress and (now - last_print) >= PROGRESS_INTERVAL:
        ...
        last_print = now
    # or extract a tiny helper to avoid repetition
    ```
  |||,
  properties: ['time'],
  instances: [{ files: { 'pyright_watch_report.py': [{ start_line: 121 }, { start_line: 137 }, { start_line: 143 }, { start_line: 151 }] } }],
};

obj
