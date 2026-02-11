# Specimen: crush/internal/db (behavior snapshot)

- Date: 2025-08-30

## How to run critic (dry-run)

```bash
adgn-codex-properties find \
    "/Users/mpokorny/code/crush" \
    "all files under internal/db/**" \
    --dry-run \
    --embed-path ../2025-08-29-pyright_watch_report/pyright_watch_report.py \
    --embed-path ../2025-08-29-pyright_watch_report/README.md
```

Parallel runner with 1 critic per subdir: `./scratch/run_parallel_critics.sh`
