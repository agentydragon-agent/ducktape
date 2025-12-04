local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    `dump_path` type annotation is misleading - it types it as `Path | None`, but the rhs is never `None`:

    ```python
    dump_path: Path | None = Path(args.dump).resolve() if args.dump else (root / "scratch/pyright_watched_files.txt")
    ```

    Annotate as `Path` (not `Path | None`).
  |||,
  filesToRanges={
    'pyright_watch_report.py': [50],
  },
)
