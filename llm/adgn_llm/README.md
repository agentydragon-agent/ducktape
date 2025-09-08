# adgn-llm

Shared library bundling:
- Properties (CLI + packaged Markdown definitions)
- Mini Codex wrapper (stub CLI; can import or proxy to llm/mini_codex)
- Optimizer stubs (future)

Install (editable):

```bash
python -m pip install -e llm/adgn_llm
```

CLI examples:

```bash
adgn-codex-properties find /path/to/repo "all files under internal/app/**"
```

```bash
python3 -m adgn_llm.inop.engine.optimizer \
  --task-type code_review \
  --iterations 2 \
  --rollouts-per-task 1 \
  --tasks-per-iteration 2 \
  --runner mini_codex \
  --config-dir "/Users/mpokorny/code/ducktape/claude/claude_optimizer/config"
```
