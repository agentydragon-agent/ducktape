# Experimental contract

This experiment supports one user prompt, sequential Responses sampling, and `exec` code-mode calls
that run to completion within the CLI deadline. The nested tool set consists of:

- `exec_command({cmd, workdir?})`: `/bin/sh -c`, no PTY or stdin; output is UTF-8 replacement-decoded
  combined stdout/stderr, capped at 1 MiB, and returned as `{output, exit_code}`. Only those arguments
  are accepted. This omits upstream shell startup, sandbox policy and result metadata.
- `apply_patch(patch)`: the executor's pinned Codex hidden apply-patch entrypoint, invoked by argv;
  its patch parser and filesystem behavior are upstream's. Output follows the same shape above.

Postgres contains the ordered provider items and completed tool outputs. Provider output dictionaries,
including encrypted reasoning and unknown fields, are stored without projection or normalization.
The input is rebuilt as a Responses Lite `additional_tools` declaration followed by these items;
sampling requests ask for encrypted reasoning and do not use provider-side conversation storage.
Only a complete `response.completed` event permits committing a provider response or running a tool.
There is no automatic provider retry or `previous_response_id` continuation.

Before sampling, a cell, or a nested tool starts, the sampler commits its intent. Completed provider
output and completed cell output each commit atomically with clearing the outer pending intent.
A resumed process refuses every unresolved intent, identifying sampling separately from cell/tool
uncertainty. Nested results alone do not make an interrupted JavaScript cell resumable.
There is no operator reconciliation interface in this experiment.

A row lock serializes lease acquisition; the database clock and a monotonically increasing generation
fence reads and writes. Every conversation transition, nested intent, and nested result verifies that
the owner and unexpired lease still match. CLI advances have a 90-second deadline and a 120-second
lease; a crashed owner can delay takeover until expiry. There is no heartbeat or forced takeover.

The database cannot atomically fence a remote process side effect. A takeover can race after intent
commit and before dispatch; an old already dispatched request may still run. Generation checks reject
its later database writes. Lost replies, executor death, or sampler death never cause automatic effect
replay. This is single-writer conversation fencing, **not exactly-once execution**.

The sampler performs no local shell or filesystem tool fallback when the executor fails. Conversation
reads and sampling do not require an executor connection. The CLI bounds failures but does not certify
that executor descendants were killed; that belongs to executor supervision.

There is no `wait`, yielded-cell continuation, interactive stdin, interrupt API, compaction,
instruction discovery, persistent JavaScript `store`/`load`, subagents, skills, MCP, approvals, hooks,
memory retrieval, History export or frontend trace. A fresh upstream JS host is created for every
cell. Unsupported provider item types and non-`exec` tools fail explicitly. The full native harness
remains responsible for every capability outside this experiment.
