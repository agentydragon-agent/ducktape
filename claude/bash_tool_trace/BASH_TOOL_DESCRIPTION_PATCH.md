# Bash tool — behavior and guardrails in this environment

Important behavior
- Commands are executed via a shell eval and the environment injects a stdin redirection:
  - `eval "<your_command>" "<" "/dev/null"`  → effectively `your_command < /dev/null`
- After running, we also capture the final working directory: `pwd -P >| <tmp>`

What breaks (and why)
- Heredocs (e.g., `<<'DELIM' ... DELIM`) — the injected `< /dev/null` discards heredoc input, so the command sees an empty/misparsed stdin (common symptom: `PY < /dev/null` in error output)
- Pipelines where the last stage reads stdin (e.g., `python -`, `node -`, `jq` with no file) — the injected `< /dev/null` prevents the last stage from receiving pipe input
- Inline scripts that contain `!` inside double-quoted strings (e.g., `node -e "if(!x){...}"`) — Bash history expansion escapes `!` to `\!` before eval; this invalid escape breaks JavaScript (`SyntaxError: Expected unicode escape`)

Do this instead
- Short Python snippets: `python -c "print('ok')"`
- Multi-line code: write a file and run it:
  ```bash
  cat > ./scratch/script.py <<'PY'
  print("ok")
  PY
  python ./scratch/script.py
  ```
- If you must use a heredoc: wrap it inside an inner shell so it’s parsed from the string, not from stdin:
  ```bash
  bash -lc "python - <<'PY'
  print('ok')
  PY
  "
  ```
  (Use double quotes outside; single-quoted heredoc delimiter inside.)
- For jq and similar tools at the end of a pipeline: pass an explicit file to the last stage (`jq '.prog' input.json`) instead of relying on stdin
- Avoid `!` in inline `-e` snippets. Prefer: write to a temp file and run (`node /tmp/script.js`), or use a single-quoted heredoc via `bash -lc`.
- If you must run a one-liner that includes `!`, disable history expansion just for that command: `set +H; node -e 'if(!x){...}'; set -H`.
- For JSON edits, prefer `jq` over `node -e` to avoid quoting/expansion pitfalls.

Examples
- Works:
  - `ls -la /etc`                 # does not rely on stdin
  - `python -c "print('ok')"`     # no heredoc or stdin required
- Broken patterns:
  ```bash
  python - <<'PY'
  print("ok")
  PY
  # Broken: heredoc input discarded due to '< /dev/null'

  echo '{}' | jq '.prog'
  # Broken: last stage wants stdin but sees /dev/null
  ```

Notes
- We may reject commands that match the broken patterns above and return a fix-it explanation.
- If you prefer, you can explicitly send the wrapped heredoc form (`bash -lc "…"`) yourself.
