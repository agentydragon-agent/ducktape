# Specimen

## TODO: Automated analysis

- [x] llm/adgn_llm/src/adgn_llm/git_commit_ai/**/*.py — run open-ended review; include uncovered issues
- [x] llm/adgn_llm/src/adgn_llm/mini_codex/**/*.py — run open-ended review; include uncovered issues
- [x] llm/adgn_llm/src/adgn_llm/mcp/docker_exec/**/*.py — run open-ended review; include uncovered issues
- [x] llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/**/*.py — run open-ended review; include uncovered issues
- [x] Aggregate all section outputs into unconfirmed.md

## TODO: Follow-ups

- [ ] git_commit_ai/cli.py:L497 — Likely false positive; confirm and either document the exception pattern or add a clarifying property.
  GAP: Define conditions distinguishing acceptable patterns from swallowers; update specimen once decided.
