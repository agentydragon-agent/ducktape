# Haku self-hosted worker bring-up — RCA / gotchas (2026-06-23)

First real activation of the in-cluster `haku-worker` (Managed Agents Runtime B,
`ant beta:worker poll` in `haku-sandbox`). Activation surfaced a chain of
independent failures, each masking the next. Recorded so we don't re-debug.

## Headline bug (upstream `ant`): empty tool output → session deadlock

**Symptom:** a session reaches `running`, the model emits a tool call, then sits
at `status: idle` forever (Console shows a spinner on that tool call); no
`user.tool_result` is ever delivered.

**Root cause:** when a tool produces **empty output**, `ant beta:worker poll`
POSTs a tool result whose `content[0].text` is the empty string. The API rejects
it and the worker gives up:

```
ERROR tool result send hit permanent 4xx; not retrying
  POST /v1/sessions/<id>/events: 400 Bad Request
  invalid_request_error: events.0.content.0.text: minimum string length is 1
  dispatched tool=bash is_error=false posted=false
```

The 400 is treated as permanent → not retried → result never lands → the session
deadlocks on that tool. **Any** tool call whose result text is empty triggers it:
a command with empty stdout that exits 0 (`cd`, `… | head` with no input,
`grep -q`), etc.

**Confirmed in source** (repos cloned in `~/code`: `anthropic-cli`,
`anthropic-sdk-go`). `ant` 1.12.1 is a Go binary built on `anthropic-sdk-go`
**v1.50.1** (`anthropic-cli/go.mod`); its worker is `pkg/cmd/worker.go`, using
the SDK's `tools/agenttoolset`. The deadlock is the SDK's, not `ant`-CLI-specific:

- `anthropic-sdk-go tools/agenttoolset/agenttoolset.go:145 textResult(s)` builds
  `BetaTextBlockParam{Text: s}` with **no empty guard** — `s==""` → `Text:""` →
  the 400 above. **Identical in `v1.50.1` (shipped) and `main`** (the
  `v1.50.1..main` diff touches none of this) — so it is unfixed upstream, and the
  Go SDK `EnvironmentWorker` would deadlock the same way. Cloud sandboxes must
  guard empty results server-side; the self-hosted worker doesn't.
- The bash tool (`tools/agenttoolset/bash.go`) is **not** at fault: it wraps each
  command as `{ <cmd>\n} </dev/null 2>&1; printf '\n<sentinel>%d\n' $?` — it
  merges stderr (`2>&1`) and captures the real exit code. So a stderr-only,
  non-zero command yields non-empty output + `is_error=true` (no 400). Our empty
  result was a **genuinely empty stdout, exit 0** — not a capture/PTY/egress
  failure.

**Exact trigger we hit** (base-sync, session `sesn_01U9fwo…`): the agent ran
`git -C /workspace/ducktape log --oneline <pin>..HEAD -- haku/base haku/run.md 2>/dev/null | head -20`.
The `--depth 1` clone lacked `<pin>` → git `fatal` → **suppressed by the agent's
own `2>/dev/null`** → `head` got empty stdin → empty stdout, **exit 0** (head's
code) → `is_error=false`, empty text → 400 → deadlock. So it was a real
empty-output command, masked by the agent's `2>/dev/null | head`.

- Present in `ant` **1.12.1** (latest release, 2026-06-10) — no upgrade fixes it.
  **Report to Anthropic** (precise ask: `textResult`/worker must send a
  placeholder like `(no output)` for empty results).
- Diagnose by turning on `ANT_DEBUG=1` (worker Deployment env → global `ant
--debug`); the `tool result send hit permanent 4xx` line is the tell. Without
  it the worker only logs `claimed work`.
- **Mitigations / fixes (in order of robustness):**
  1. **Patch + build a custom `ant`** from `~/code/anthropic-cli` +
     `anthropic-sdk-go` with the one-line empty guard in `textResult` — fully
     robust; cost: maintenance + the repos are `no-license` (all rights
     reserved).
  2. **Reduce triggers**: full-enough clone so base-sync's `git log` resolves
     (done: `--shallow-since="1 week ago"`); instruct Haku to never emit empty
     stdout (`… || echo '(none)'`, avoid `2>/dev/null | head`). Fragile.
  3. A `/bin/bash` wrapper can't help cleanly: the bash tool drives a persistent
     interactive PTY shell, not `bash -c`.

## The full chain (all fixed unless noted)

| #   | Symptom                                                                      | Root cause                                                                                                                                                                  | Fix                                                                                                                                                                                                                                           |
| --- | ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | `ErrImagePull: wrong diff id calculated on extraction`                       | `podman import` of the `.tar.xz` records a layer whose diffID is inconsistent with the stored gzip layer                                                                    | flake emits an **uncompressed** `.tar`; import that (also drops a wasted pixz pass → faster CI). `flake.nix` `haku-worker-image` override                                                                                                     |
| 2   | Pod crash-loop, PID 1 exits 255                                              | booting systemd (`/init`) in an unprivileged container can't mount `/proc`,`/dev`,`/run` (`permission denied`)                                                              | don't boot: run the closure directly as non-root `haku` via `/sw/bin/haku-worker-run`. `nixos.nix` + `deployment.yaml`                                                                                                                        |
| 3   | `RunContainerError: stat /sw/bin/haku-worker-run: no such file`              | transient: deployment had the new `command` but an old image (pre-launcher)                                                                                                 | rolled forward to the image that has the launcher                                                                                                                                                                                             |
| 4   | entrypoint: `/home/haku/.netrc: No such file or directory`                   | `createHome` runs at NixOS activation, which we skip                                                                                                                        | mount a writable `emptyDir` at `/home/haku`; set `HOME`                                                                                                                                                                                       |
| 5   | git clone `CONNECT tunnel failed, 502`                                       | GitHub is blocked by the `haku-mitmproxy` egress allowlist                                                                                                                  | clone ducktape from the in-cluster Forgejo mirror instead                                                                                                                                                                                     |
| 6   | clone 401 / `.netrc` ignored                                                 | `HAKU_GIT_HOST=git.allegedly.works` but clone URLs use the in-cluster Service `forgejo-http.forgejo` — `.netrc` host didn't match (would have broken `haku-state` too)      | set `HAKU_GIT_HOST=forgejo-http.forgejo`; clone ducktape via the same internal URL                                                                                                                                                            |
| 7   | `haku` 404 on the ducktape mirror                                            | the `haku` Forgejo user had no read access                                                                                                                                  | grant read collaborator (manual; **not yet turnkey** — see `../../../cluster/k8s/haku/agent-worker/README.md`)                                                                                                                                |
| 8   | agent reads missing files                                                    | the Forgejo mirror was 10 days stale, predating all of `haku/`                                                                                                              | bump the mirror (manual; not auto-synced from GitHub)                                                                                                                                                                                         |
| 9   | sessions stall at `idle` (claim works, results never post)                   | `haku-mitmproxy` TLS-intercepts and breaks the worker's long-lived HTTP/2 session stream to `api.anthropic.com` (claim = short poll, works; session-drive = stream, breaks) | mitmproxy `ignore_hosts api\.anthropic\.com` (raw TCP passthrough; egress still flows through the proxy). Worker trusts the real cert — its CA bundle is system roots + the mitmproxy CA. `cluster/k8s/agents/haku-mitmproxy/deployment.yaml` |
| 10  | `bash`: `fork/exec /bin/bash: no such file`                                  | the `agent_toolset_20260401` `bash` tool execs `/bin/bash` at that literal path; absent in the unbooted closure                                                             | bake `/bin/{bash,sh}` → `/sw/bin` into the rootfs via the tarball `extraCommands` (must be a `writeScript`, and `chmod u+w bin` first). `flake.nix`                                                                                           |
| 11  | `read`/`glob`: `absolute path not permitted`                                 | the file tools are workdir-relative only; the agent prompt + manual used `/workspace/...`                                                                                   | rewrote `haku.agent.yaml` system prompt to relative paths (re-provision: `ant beta:agents update` + re-pin the deployment)                                                                                                                    |
| 12  | base-sync `git log <pin>..HEAD` → empty (then deadlock per the headline bug) | `git clone --depth 1` omits the pinned commit → `Invalid revision range` (empty)                                                                                            | clone ducktape `--shallow-since="1 week ago"`. `entrypoint.sh`                                                                                                                                                                                |

## Diagnostic recipes

- **Worker debug logs:** `ANT_DEBUG=1` on the Deployment → `ant --debug`. Look for
  `claimed work`, `executing tool`, `dispatched tool … posted=true/false`, and
  `tool result send hit permanent 4xx`.
- **Session timeline (control plane, org key):**
  `ant beta:sessions:events list <sid>` — `agent.tool_use` vs `user.tool_result`
  (match on `tool_use_id`); an unmatched `tool_use` is the stuck one. `is_error`
  shows tool-level failures.
- **Queue stats** (`ant beta:environments:work stats`) and **drain**
  (`ant beta:environments:work stop --work-id`) need an org key with scope
  `org:external_poll_sessions`; a plain `ant auth` OAuth token 400s/403s these.
  Terminating a session does **not** drain its queued work item.
- **`kubectl exec` into the worker:** PATH isn't set (no activation) — use
  absolute `/sw/bin/...` or `export PATH=/sw/bin`.

## Temporary settings to revert

- `haku.agent.yaml` model is **Sonnet** (`TEMP(debugging)`); restore
  `claude-opus-4-8` and re-pin the deployment.
- `ANT_DEBUG=1` in the worker Deployment; set to `""` once stable.
- mitmproxy `ignore_hosts` is a keeper, but has a `TODO` to tighten (currently
  passes all of `api.anthropic.com`).

## `ant` is an independent implementation (not Claude Code)

Checked whether `ant beta:worker poll` delegates tool execution to the `claude`
Claude Code CLI (whose bash harness guards empty output, captures stderr, etc.)
or reimplements the toolset. **It reimplements it.** `ant` is a statically
linked Go binary (`anthropic-sdk-go`); its strings show a native in-process tool
runner (`session-tool-runner`, `agent_toolset_20260401`, its own `start bash
pty` + `TERM=dumb` runner, `[output truncated]`, native `glob`/`grep`) and **no
`claude` CLI invocation** anywhere.

Implication for "switch to the SDK that runs Claude Code": there isn't one. The
Managed Agents **SDK** `EnvironmentWorker` (Python/TS/Go) is _also_ an
independent reimplementation of the same `agent_toolset_20260401` — not Claude
Code. So switching SDKs does **not** buy Claude Code's harness. The only real
"switch" options:

- **Go SDK `EnvironmentWorker`** — a different impl of the toolset that _might_
  guard the empty-result case better (the API requires `content.text` ≥ 1, so a
  correct worker must send a placeholder; check the SDK source before betting on
  it). Avoids the Python lockfile conflict, but means building/maintaining a
  custom Go worker instead of the stock `ant` CLI.
- **Python SDK `EnvironmentWorker`** — reopens the `anthropic` 0.103-vs-0.80
  lockfile conflict that motivated "ant-all-the-way"; avoid.

Neither is Claude Code. Recommended: stay on `ant`, mitigate triggers, and report
the empty-result→400 deadlock upstream.

## Current state & next steps (as of 2026-06-23)

**Working:** worker runs the closure unprivileged; claims sessions; executes
read/bash/kubectl/git with the agent on Sonnet v2; the mitmproxy passthrough
fixed the session-stream deadlock; a full scan pass ran with 0 tool errors until
it hit the empty-`git log` deadlock.

**Landed on `devel`:** all 12 fixes above (image diffID, closure-direct runtime,
`/bin/bash`, `/home/haku`, Forgejo mirror + `.netrc` host, mitmproxy passthrough,
relative-path prompt, `--shallow-since="1 week ago"`). Agent updated to v2
(Sonnet) and the deployment re-pinned to it via `ant`.

**Pending / open:**

- Deploy + verify the `--shallow-since` image (commit `1ac0930196`) — confirm
  base-sync's `git log <pin>..HEAD` now returns non-empty and the session
  completes (commits `haku-state`).
- **Empty-result→400 deadlock is unfixed** (upstream `ant` gap). Mitigated by the
  week-of-history clone; still bites any empty-output tool call. **Report to
  Anthropic.**
- Manual, non-turnkey prereqs: bump the Forgejo `agentydragon/ducktape` mirror;
  keep the `haku` read-collaborator grant. (TODO: Terraform-manage both.)
- Revert the temporary settings above once stable.
