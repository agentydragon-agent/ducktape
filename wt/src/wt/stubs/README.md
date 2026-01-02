Local type stubs

This directory contains local type stubs used by mypy. We check them into the repo so CI and all dev environments get consistent, deterministic type checking.

Currently covered

- pygit2 (vendored minimal upstream stubs via stubgen)

How to regenerate pygit2 stubs

1) Ensure you have mypy and pygit2 installed in your environment:
   - pip install mypy pygit2
2) From the repo root (this directory is wt/), run:
   - stubgen -m pygit2 -o ./stubs
   This overwrites ./stubs/pygit2/__init__.pyi with a fresh export from your local pygit2 installation.
3) Optional: Trim or augment
   - If mypy reports missing attributes we actually use, you can add them to the generated .pyi files.
   - Keep edits minimal and add a short inline comment like  # wt: added for X.Y usage
4) Verify
   - Run: python -m mypy wt
   - Fix remaining errors or adjust stubs as needed.

Configuration

- pyproject.toml points mypy at this folder via:
  [tool.mypy]
  mypy_path = ["stubs"]

Versioning guidance

- If you upgrade pygit2, re-run the stubgen step to refresh the stubs.
- Commit the changes along with any code updates that rely on new pygit2 APIs.

Notes

- These stubs are auto-generated starting points. Small manual additions are acceptable when upstream typing is incomplete, but prefer re-generating first and only adding what we actually use.
