local I = import '../../lib.libsonnet';

// iss-003b: Extension list is misleading and duplicated

I.issue(
  snapshot='misc/2025-08-29-pyright_watch_report',
  rationale=|||
    Extension list is misleading and duplicated.
    Printed list is hard-coded `.py/.pyi/.pyx` which does not match `CODE_EXTS` (set to `{'.py', '.pyi'}`).

    ```python
    print(f"  of which code (.py/.pyi/.pyx): {total_code}")
    ```

    Derive from one source of truth - `CODE_EXTS` - instead:

    ```python
    print(f"  of which code ({'/'.join(sorted(CODE_EXTS))}): {total_code}")
    ```

    This makes the message not misleading and avoids future drift.
  |||,
  filesToRanges={
    'pyright_watch_report.py': [36],
  },
)
