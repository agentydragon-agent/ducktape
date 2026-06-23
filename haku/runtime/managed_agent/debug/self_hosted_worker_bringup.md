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
deadlocks on that tool. **Any** empty-output tool call triggers it: `grep` with
no match, `git log <range>` with no commits, a command that writes only stderr,
`echo -n`, etc.

- Present in `ant` **1.12.1**, which is the latest release (2026-06-10) — no
  upgrade fixes it. It is an upstream `ant` bug; **report to Anthropic**.
- Diagnose by turning on `ANT_DEBUG=1` (worker Deployment env → global `ant
--debug`); the `tool result send hit permanent 4xx` line is the tell. Without
  it the worker only logs `claimed work`.
- **Mitigations (no clean fix while on the CLI, by the "ant-all-the-way"
  decision):** reduce empty-output triggers (e.g. clone enough history that
  base-sync's `git log <pin>..HEAD` resolves — see below) and/or instruct Haku to
  never emit empty stdout (append `; echo "[rc=$?]"`, `grep … || echo '(none)'`).
  A `/bin/bash` wrapper can't help cleanly: the bash tool drives a persistent
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
