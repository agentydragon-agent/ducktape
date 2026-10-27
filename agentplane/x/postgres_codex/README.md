# Postgres Codex sampler experiment

A headless, code-mode-only sampler with Postgres as its conversation authority. It reuses the
**actual pinned Codex 0.162.1 code-mode host and exec-server**, including upstream `apply_patch`.
It does not run an app-server, write native rollouts, or use a Runner conversation journal.
This is a runnable experiment, with deliberately narrow tool behavior; see [SPEC.md](SPEC.md).

`main_bin init` creates the experiment's isolated tables in a dedicated database and inserts a prompt.
Each `main_bin advance` performs one sampling or code-cell transition and exits. A later process
uses Postgres checkpoints to continue. `main_bin run` retains a real code-mode host across sampling
and model-facing `wait` calls, supporting yielded JavaScript cells. No production database, migration runner, deployment or service
reads these tables. The package is test-only and has no shipped caller.

```sh
bbr test //agentplane/x/postgres_codex:test_sampler \
  //agentplane/x/postgres_codex:test_controls //agentplane/x/postgres_codex:test_interrupts
```

The integration test uses real PostgreSQL 18, the pinned upstream binaries, and Agentplane's
scripted Responses endpoint. It drives that same wire fixture through the full upstream Codex
app-server as an independent protocol consumer. No live inference, provider subscription or
account compatibility is established by this test.

To run by hand, use a disposable PostgreSQL database and a separately supervised `codex exec-server`:

```sh
bb run //agentplane/x/postgres_codex:main_bin -- \
  --database-url "$SPIKE_DATABASE_URL" init 'Write a file and report the result.'

# SPIKE_MODEL_CREDENTIAL contains the configured provider credential placeholder.
bb run //agentplane/x/postgres_codex:main_bin -- \
  --database-url "$SPIKE_DATABASE_URL" advance "$SPIKE_CONVERSATION_ID" \
  --executor-url ws://127.0.0.1:4500 --executor-codex /absolute/executor/path/codex \
  --code-mode-host /absolute/sampler/path/codex-code-mode-host \
  --cwd /absolute/executor/workspace --logs /tmp/spike-code-mode.log \
  --endpoint http://configured-provider/v1/responses --model configured-code-mode-model
```

Use `run` with the same options to retain live JavaScript cells; repeat `advance` only for completed-cell checkpoints until it prints `done`. The credential is an environment variable so it is absent
from persisted request bodies and CLI arguments. These example URLs supply no authentication or
network isolation; the local integration fixture is the supported test setup.

A running `exec_command` can yield a process `session_id`; `tools.write_stdin` sends input or polls it.
PTY sessions support terminal EOF and Ctrl-C semantics. A yielded `exec` returns a separate `cell_id`
for the model-facing `wait` tool. Process handles persist across sampler restarts only within the
upstream executor session's 30-second detached retention window. Live JavaScript requires the same
host and cannot be recovered from Postgres after host loss.

From a second process, `status` returns the active generation; target it explicitly to interrupt:

```sh
bb run //agentplane/x/postgres_codex:main_bin -- \
  --database-url "$SPIKE_DATABASE_URL" status "$SPIKE_CONVERSATION_ID"
bb run //agentplane/x/postgres_codex:main_bin -- \
  --database-url "$SPIKE_DATABASE_URL" interrupt "$SPIKE_CONVERSATION_ID" --generation 1
```

Inspect `status` again for the durable request outcome. Successful interruption stops sampling and
records observed process exits plus possible partial effects. Explicit `input CONVERSATION PROMPT`
can continue after this terminal interrupted state. Unknown cleanup outcomes block continuation;
there is no automatic replay or reconciliation interface. These controls cover known supervised
processes, not arbitrary escaped descendants. Existing disposable experiment databases need the
additive `migrations/0002_process_controls.sql`; `init` creates the current schema for a fresh database.

`store.py` owns the isolated schema, intent checkpoints and lease generations. `sampler.py` owns
Responses Lite request assembly and terminal SSE handling. `code_mode.py` speaks upstream's
length-prefixed JSON protocol V1, while `executor.py` speaks its WebSocket process RPCs. `main.py`
owns process lifetimes and deadlines; `control.py` watches generation-targeted interrupts. Experiment results and cost accounting live in
[the investigation](../../debug/postgres_codex_spike.md).
