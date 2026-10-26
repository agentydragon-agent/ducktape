# Runner configuration

The Runner has a Pod entry point and a KubeVirt guest entry point. Both build one explicit
configuration before opening the state directory. The Pod supplies command-line arguments and
container environment; the VM reads a versioned seed and launch file from read-only disks. Session
behavior is shared across those entry points. The protocol and lifecycle contract is in
[`SPEC.md`](SPEC.md).

## Entry points and flags

The Pod starts `/run/agentplane/runner/bin/agentplane-runner`. The VM starts
`/run/agentplane/runner/bin/agentplane-runner-vm`, a symlink to the same executable. That symlink
selects guest configuration from `/run/agentplane/config.json` and `/run/agentplane/launch.json`.
The public `--guest` switch selects the same guest path when invoking the executable directly.

The Pod entry point accepts these flags. Required flags must be supplied together as shown; unknown
flags and positional arguments are rejected.

| Flag                                               | Source and behavior                                                                                                                                                                               |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--state-dir DIR`                                  | Required. Persistent runner state. The deployed Pod uses `/state`.                                                                                                                                |
| `--control-target HOST:PORT`                       | Required Runner Gateway control-stream address.                                                                                                                                                   |
| `--control-bearer VALUE`                           | Required egress-proxy placeholder for the Runner Gateway audience.                                                                                                                                |
| `--ingress-target HOST:PORT`                       | Required History ingress address.                                                                                                                                                                 |
| `--ingress-bearer VALUE`                           | Required egress-proxy placeholder for the ingress audience.                                                                                                                                       |
| `--launch-file PATH`                               | Required strict JSON file written for this Sandbox by the Sandbox Controller.                                                                                                                     |
| `--platform-instructions-file PATH`                | Required deployment-wide Session guidance rendered from the platform template.                                                                                                                    |
| `--claude-binary PATH`                             | Optional Claude Code executable. When set, also requires `--anthropic-base-url` and `ANTHROPIC_AUTH_TOKEN`.                                                                                       |
| `--anthropic-base-url URL`                         | Anthropic Messages base URL for the Claude provider. It must be an HTTP(S) origin.                                                                                                                |
| `--codex-binary PATH`                              | Optional Codex executable. When set, also requires `--openai-base-url` and `OPENAI_API_KEY`.                                                                                                      |
| `--openai-base-url URL`                            | OpenAI Responses API base URL for Codex, normally the HTTP(S) LLM-ingress `/v1` URL.                                                                                                              |
| `--harness-env NAME` or `--harness-env NAME=value` | Repeatable. Add one explicit environment value to every native harness. A bare name copies the Runner's value if present; `NAME=value` sets it directly. Later declarations replace earlier ones. |
| `--harness-inherit-env NAME`                       | Repeatable. Forward a Runner-image-owned variable to harnesses when it is present.                                                                                                                |
| `--test-debug-checkpoint-name VALUE`               | Test-only durable checkpoint name; must be paired with the command ID flag.                                                                                                                       |
| `--test-debug-checkpoint-command-id VALUE`         | Test-only command ID for the paired durable checkpoint.                                                                                                                                           |

The two provider token variables are read by the Runner and installed into the corresponding native
harness by its adapter. The deployed Pod and VM set them to
`agentplane-credential-agentplane-workload`; the egress proxy substitutes the credential when a
request leaves the box. Do not configure a provider secret directly in a template or Session.
The control and ingress bearers are also placeholders. The deployed VM seed uses the same workload
placeholder for both service routes.

Harness environments are allowlists, not copies of the Runner environment. The Pod template passes
the deployment's workload variables, egress proxy and CA variables, `agentplane` service URLs and
explicit additions through `--harness-env`. Image-owned names such as `TZDIR` use
`--harness-inherit-env`. Each Session adds its own `AGENTPLANE_DESTINATION`. Provider credentials
and provider URLs are set by the adapters. The VM sets its fixed proxy, CA, PATH, HOME and kubeconfig
values itself, then adds the seed's optional `harness_env` map; the Runner rejects entries that
override a guest-owned name.

## Files, identities, and deployment sources

The Sandbox Controller creates a per-Sandbox launch ConfigMap containing the Sandbox namespace,
name, UID and optional bootstrap source. A Pod mounts it at `/run/agentplane/sandbox/launch.json`;
the VM attaches it as the `agentplane-launch` ConfigMap disk, which the NixOS guest links to
`/run/agentplane/launch.json`. The bootstrap runs once before Session setup or harness launch. A
failed or interrupted bootstrap is terminal for that Sandbox incarnation.

The VM's version-2 seed is typed in
[`agentplane/sandboxes/guest_config.py`](../sandboxes/guest_config.py) and written by
[`runner_vm.py`](../../cluster/cdk8s/agentplane/runner_vm.py). Its `control` and `ingress` endpoints
are host:port plus proxy-substituted bearer placeholders; it also carries LLM and HTTP proxy origins,
platform instructions, optional harness environment additions, console behavior and resource
budgets. The runner rejects unknown JSON fields and invalid resource limits.

| Guest path                                                                      | Contents and owner                                                               |
| ------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `/run/agentplane/config.json`                                                   | Versioned per-environment seed on the read-only ConfigMap disk.                  |
| `/run/agentplane/launch.json`                                                   | Sandbox identity and optional bootstrap from the Sandbox Controller.             |
| `/run/agentplane/runner.env`                                                    | Runner-only OpenTelemetry SDK settings from the VM template.                     |
| `/run/agentplane/kubeconfig`                                                    | The guest workload ServiceAccount's kubeconfig.                                  |
| `/run/agentplane/ca-certificates.crt` and `/run/agentplane/ca-certificates.p12` | Egress proxy CA trust bundle.                                                    |
| `/run/agentplane/runner`                                                        | Read-only runner disk containing the Runner executable and `agentplane` command. |
| `/state`                                                                        | Durable Session journals and native persistence, shared with the Pod layout.     |
| `/state/workspaces`                                                             | Sandbox-owned workspace disk and bootstrap working directory.                    |
| `/dev/disk/by-id/virtio-workspace`                                              | Workspace block device receiving the configured I/O throttles.                   |

The VM runs the Runner as root with only the capabilities needed for ownership and child-process
management. Native harness processes run as uid/gid 107 (`agent`), matching the KubeVirt virtiofs
owner. Their delegated cgroup root is
`/sys/fs/cgroup/system.slice/agentplane-runner.service/workloads`.

Before the Runner starts, `ExecStartPre` invokes the private
`--guest-resource-properties <config>` mode. It strictly decodes the seed, checks version 2 and all
resource relationships, reads live `/proc/meminfo`, and prints the exact systemd properties only
after validation succeeds. It requires the service memory cap to remain below live `MemTotal`,
catching a stale VM template after a seed resize that raises the cap beyond the VM's actual RAM.
systemd then receives `MemoryHigh`, `MemoryMax`, `MemorySwapMax=0`, `CPUQuota` and
`TasksMax`; `OOMPolicy=continue` keeps a child OOM from stopping the whole Runner service. The
aggregate and process cgroups use their seed budgets. Swap remains disabled, aggregate
`memory.oom.group` is 0, and each process leaf uses `memory.oom.group=1`.

## Provider and Session settings

Claude and Codex use the deployment's authenticated LLM ingress, not direct provider credentials.
The Pod template resolves `LITELLM_URL` into the base URLs and sets the workload token placeholder.
The VM seed supplies the ingress origin and its Runner installs the workload placeholder; Claude
uses that origin directly and Codex uses its `/v1` API base and the catalog route on the same
origin. Claude obtains its context budget from ingress model configuration and retains the resolved
budget for resume. Codex reads model metadata from the ingress model catalog per turn.

`SessionSpec` selects `harness`, absolute `cwd`, `model`, optional `reasoning_effort`, and standing
`instructions`. The Runner composes deployment-wide platform instructions, a notification
destination made from the Sandbox identity and Session ID, and the caller's Session task in that
order. They are persisted with the Session and must match when it is reopened. Session setup scripts
are separate from the Sandbox bootstrap and run once for that Session.

Each Claude Session has a separate harness process and persistence directory. All Codex Sessions on
one Runner are threads hosted by one shared Codex app-server; the server binary, provider endpoint,
Codex home and credential apply to every thread, while model, reasoning effort, working directory,
instructions and notification destination belong to each Session. A Codex server exit affects all
threads it hosts; the Runner resumes them from their stored identities as needed.

## Telemetry

The Runner uses the standard OpenTelemetry environment contract. Pod templates and the VM seed disk
set `OTEL_SERVICE_NAME=agentplane-runner`, `OTEL_RESOURCE_ATTRIBUTES` with the Agentplane namespace
and deployment environment, OTLP/gRPC protocol and endpoint, and the parent-based always-on sampler.
SDK settings are read by the Runner process; VM `runner.env` is not forwarded to native harnesses.
The SDK also accepts the standard `OTEL_*` variables and supports `OTEL_SDK_DISABLED=true`,
`OTEL_TRACES_SAMPLER`, and `OTEL_TRACES_SAMPLER_ARG`.

Runner spans cover tunneled RPC calls and selected lifecycle operations. HTTP instrumentation records
method, route and response status without URLs, query strings, headers or bodies. W3C trace context
is propagated across Runner RPCs and outbound HTTP/gRPC calls. Telemetry does not carry harness
prompts, model content or event payloads.
