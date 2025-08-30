# Specimen: crush/internal/db (behavior snapshot)

- Source repo: agentydragon/crush
- Commit: a2a1ffa00943aa373f688ac05b667083ac3230b1
- Scope: internal/db/**
- Date: 2025-08-30

This folder will capture files under internal/db/** from the specified commit, plus notes and analysis.

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

