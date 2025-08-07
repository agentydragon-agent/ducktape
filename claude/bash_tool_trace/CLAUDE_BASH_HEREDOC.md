# Claude Code Bash tool + heredoc: failure analysis and repro

This document explains why Python heredocs (e.g., `python - <<'PY' ... PY`) can break when executed via Claude Code’s Bash tool, shows how the Bash tool transforms commands, and provides concrete repros and workarounds.

## Summary

- The Bash tool wraps your command in an `eval` call and appends additional tokens and commands (notably a redirection and a `pwd` capture).
- In the non-pipeline path, it quotes and passes three arguments to `eval`: `[cmd, "<", "/dev/null"]`. This reconstructs an eval string like: `python - <<'PY' ... < /dev/null`.
- Combining a heredoc (`<<'PY' ... PY`) with an added stdin redirection (`< /dev/null`) causes the heredoc body to be ignored (or otherwise misparsed), producing confusing failures. Observed symptom: a Python `SyntaxError` pointing at `PY < /dev/null`.

## The Bash tool execution path

Implementation reference: `personal/agentydragon/agents/bash_tool_trace/02_ShellExec_pipeline.js`

Key excerpt (lines 19–33):

```js
// 02_ShellExec_pipeline.js:19-33
// Quote command for eval, supporting pipeline and sandbox mode
let quoted = AR1.default.quote([cmd, "<", "/dev/null"]);
if (I.includes("bash") && !sandbox && cmd.includes("|")) quoted = k$2(cmd); // special pipeline quoting
if (sandbox) { cmd = j$2(cmd); let wrap = S$2(quoted); quoted = wrap.finalCommand; var cleanup = wrap.cleanup; } else cleanup = () => {};

// Source snapshot if present, then eval command, then emit pwd -P into cwdOut
const lines = [];
if (Y) {
  if (!Wp4(Y)) { B51.cache?.clear?.(); Y = (await B51()).snapshotFilePath; }
  if (Y) { let p = O9() === "windows" ? Xi(Y) : Y; lines.push(`source ${AR1.default.quote([p])}`); }
}
lines.push(`eval ${quoted}`);
lines.push(`pwd -P >| ${cwdOut}`);
let full = lines.join(" && ");
```

And it is launched as a login shell:

```js
// 02_ShellExec_pipeline.js:39-46
let child = Jp4(I, ["-c", "-l", full], {
  env: { ...process.env, SHELL: I, GIT_EDITOR: "true", CLAUDECODE: "1", ...(sandbox ? sZ0(cmd).env : {}) },
  cwd: startCwd,
  detached: !0
});
```

Effectively, for non-pipeline commands the tool builds the equivalent of:

```bash
# Pseudocode of the assembled command chain
[ optional ] source "<snapshot>"
# Eval string reconstructed from arguments to eval:
#   AR1.quote([cmd, "<", "/dev/null"]) → eval "cmd" "<" "/dev/null"
# Which becomes eval("cmd < /dev/null")
# Then followed by current-dir capture:
pwd -P >| <tmp_cwd_path>
```

## Why heredocs break here

- A here-document (`<<WORD … WORD`) feeds its body into the command’s stdin.
- Appending `"<" "/dev/null"` into the eval-constructed command makes the effective command string end with `… < /dev/null`.
- In the shell, multiple stdin sources compete; the later redirection usually takes precedence, discarding the heredoc body or changing parse timing.
- Because the Bash tool also wraps everything in a single `eval` string and then appends `&& pwd -P >| …`, quoting/parse boundaries become fragile. In practice we observed Python getting invalid/empty input and errors like:

```text
File "<stdin>", line N
    PY < /dev/null
       ^
SyntaxError: invalid syntax
```

This matches the CLI’s behavior in our logs when attempting to run `python - <<'PY' ... PY` through the Bash tool.

## Concrete reproduction cases

### 1) Repro through Claude Code Bash tool (as observed in logs)

The router logs contain full JSON records where the tool attempted heredocs, for example:

```json
{
  "event": "frontend.request.received",
  "path": "/v1/messages?beta=true",
  "body": {
    "messages": [
      {"role": "user", "content": [{"type": "text", "text": "..."}]}
    ]
  },
  "function": {
    "name": "Bash",
    "arguments": {
      "command": "python - <<'PY'\nprint('ok')\nPY",
      "description": "..."
    }
  }
}
```

When this flows through the Bash tool, the command becomes part of an `eval` string with a trailing `< /dev/null` and `&& pwd -P …` appended as shown above, yielding the heredoc failure.

Artifacts you can inspect (full router objects with heredocs):

- `personal/agentydragon/agents/bash_tool_trace/samples/bash_python_heredoc_full_lines.jsonl`
- Pretty-printed examples:
  - `personal/agentydragon/agents/bash_tool_trace/samples/example_heredoc_full_1.pretty.json`
  - `personal/agentydragon/agents/bash_tool_trace/samples/example_heredoc_full_2.pretty.json`

### 2) Simulate the tool’s shaping with plain bash

You can emulate the relevant parts of the Bash tool (eval + added stdin redirection) to see why heredoc input is lost:

```bash
# Minimal emulation of the tool’s eval arguments construction:
#   eval <arg1> <arg2> <arg3>  → eval("<arg1> <arg2> <arg3>")
# where arg1 = your heredoc command, arg2 = "<", arg3 = "/dev/null"
# The effective eval string becomes:  python - <<'PY' ... PY < /dev/null

bash -lc 'eval "python - <<\'PY\'
print(\"ok\")
PY" "<" "/dev/null"'
# Expect: here-doc body is discarded/ignored; Python doesn’t see the script.
```

Note: The exact quoting here mirrors the tool’s `AR1.default.quote([cmd, "<", "/dev/null"])` behavior. Small differences in quoting can shift the failure signature, but the fundamental issue is the competing stdin sources when heredoc is combined with `< /dev/null` in the same eval’d string.

## Workarounds and recommendations

- Avoid heredocs in Bash tool invocations.
  - Use a scratch file instead (recommended; matches our own Bash-tool guidance):

```bash
# 1) Write your Python script to a temp file
cat > ./scratch/heredoc_test.py <<'PY'
print("ok")
PY

# 2) Execute via Bash tool with a simple one-liner
python "./scratch/heredoc_test.py"
```

- For short snippets, prefer `python -c 'code'` over heredocs (keeps a single, short command string):

```bash
python -c "import sys; print('ok')"
```

- If you must assemble multi-line code dynamically, write the content with the file Write tool (or `tee`) and execute it in a separate call.

## Appendix: What the tool appends and why

- The Bash tool appends `pwd -P >| <tmp>` to capture the final working directory after the command. This is harmless alone, but when heredocs fail (due to the stdin redirection), this additional chained command can make debugging harder since `&&` binds the commands together.
- Snapshot sourcing (`source <snapshot>`) precedes `eval`, and is unrelated to heredoc failures—mentioned here for completeness.

## References

- Execution chain (extracted): `personal/agentydragon/agents/bash_tool_trace/02_ShellExec_pipeline.js`
  - Quoting and eval construction: lines 19–33
  - Shell spawn: lines 39–46
- Full JSON repro artifacts:
  - `personal/agentydragon/agents/bash_tool_trace/samples/bash_python_heredoc_full_lines.jsonl`
  - `personal/agentydragon/agents/bash_tool_trace/samples/example_heredoc_full_1.pretty.json`
  - `personal/agentydragon/agents/bash_tool_trace/samples/example_heredoc_full_2.pretty.json`

---

If you want, I can add a lint to flag heredocs in Bash tool payloads and suggest the scratch-file fallback automatically.

## Mitigation strategy (without patching the CLI)

We will address this in two layers you control:

1) Tool description enrichment (preferred immediate step)
- Expand the Bash tool description to state explicitly that:
  - Commands are eval-wrapped and have `< /dev/null` injected
  - Heredocs and last-pipeline stdin consumers (e.g., `python -`, `node -`, `jq` without a file) will break
  - Safer patterns: `python -c '…'` for short code; write a file then run it for multi-line; or wrap heredoc explicitly via `bash -lc "…heredoc…"`

2) Pre-command hook (selectively blocks and explains)
- Detects:
  - Heredoc presence (high confidence)
  - Likely-broken pipelines where the last stage reads stdin
- Behavior:
  - Reject with tailored, actionable guidance
  - Offer an opt-in run path (e.g., explicit `bash -lc "…heredoc…"`) and show the exact command that would be executed
  - Never silently rewrite; if you do transform, always tell the model and show bytes

Non-goals
- Do not blanket-wrap with `sh -c`/`bash -lc` (breaks `cd`/`export` persistence, can alter dialect)
- Do not rely on adding a trailing newline (doesn’t fix the `< /dev/null` conflict)
- Avoid shell-prefix tricks to “cancel” the inner redirection (not reliable)

## Alternatives considered (trade-offs)

- Router rewrite heredoc → temp file (and tell the model)
  - Pros: robust against the CLI’s stdin redirection; preserves code verbatim
  - Cons: changes the visible filename in error traces; heavier to implement safely for multiple languages

- Blanket `sh -c`/`bash -lc` on all commands
  - Pros: fixes heredocs
  - Cons: breaks shell state persistence; risks dialect mismatches; doesn’t fix last-stage-stdin pipelines; quoting is brittle at scale

- Shell prefix hacks (`CLAUDE_CODE_SHELL_PREFIX`)
  - Pros: minimal intrusion
  - Cons: cannot reliably neutralize the inner `eval … < /dev/null`; still fragile

- “Just add a newline” to the command
  - Cons: core issue remains stdin redirection; not a fix

- Rewrite error text
  - Cons: worse than a pre-hook; better to intercept pre-exec and explain

## Five additional ideas to consider

1) Provide a new MCP tool that bypasses the CLI’s Bash wrapper
- Example: `RouterBash` (executes `/bin/bash -lc` directly without eval/`< /dev/null`), with light safety checks
- Make it the preferred tool for multi-line commands; retain the built-in Bash for legacy use

2) Post-failure annotator (no text rewriting)
- When stderr matches known signatures (e.g., `SyntaxError: …\nPY < /dev/null`, or jq parse errors with piped stdin), emit an assistant-side explanatory note with precise fixes
- Keeps original error intact; adds helpful context after the fact

3) Advertise an explicit helper on PATH (no silent change)
- Ship `ccr-run-heredoc` that safely executes heredocs via `bash -lc` or a temp-file route
- Tool description encourages models to call `ccr-run-heredoc "python <<'PY'…PY"` for heredocs

4) Add structured single-language tools for multi-line code
- `RunPythonScript(code: string, args?: string[])` that writes a secure temp file and executes it; LLM uses this instead of Bash for multi-line Python
- Similar tools can exist for Node/JS or shell scripts; avoids Bash quoting entirely for these cases

5) Provide a jq-friendly wrapper (`jqf`) on PATH
- `jqf 'program'` records stdin to a temp file when running under this CLI and then runs `jq` on that temp file (so the last stage doesn’t need stdin)
- Document in the tool description that `jqf` should be used for pipeline inputs

## Pre-hook detector sketches (for reference)

- Heredoc (high confidence): find `<<'DELIM'` or `<<DELIM`, verify a closing `\nDELIM\n`
- Likely pipeline-stdin (best-effort): last stage matches `python -`, `node -`, `jq` without explicit file, `awk` with no file, etc.

## Recommended rollout

- Step 1: Enrich tool description immediately with the do/don’t list and safe alternatives
- Step 2: Add a pre-command hook that rejects heredocs and likely broken pipelines with concrete guidance and optional, transparent run choices
- Step 3 (optional): Introduce `RouterBash`/`RunPythonScript`/`jqf` as explicit, documented alternatives
