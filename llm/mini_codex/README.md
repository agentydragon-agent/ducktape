# mini_codex

A minimal Python agent loop with Linux sandbox (bubblewrap) and OpenAI Responses API.

Constraints
- Linux-only
- Single sandbox (bubblewrap/bwrap)
- No project docs; system instructions only (env var)
- No apply-patch initially
- No streaming; no approval policy; sandbox executes all
- Assistant messages printed to stdout; run results printed as compact JSONL

Quick start
```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ./mini_codex
export OPENAI_API_KEY=sk-...
# optional
export OPENAI_BASE_URL=...
export OPENAI_MODEL=o4-mini
export SYSTEM_INSTRUCTIONS='You are a code agent. Use shell.run to execute commands. Respond with helpful text.'

mini-codex
```
