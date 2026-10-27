# Claude native remote-tool characterization, 2026-10-27

## Scope and result

This investigation separates ordinary local native tool behavior, driver-hosted
MCP behavior, and native remote-tool serving. The executable is the unchanged npm
Linux x86-64 Claude Code **2.1.296** archive, pinned independently in
`MODULE.bazel` by its registry SHA-512 integrity. No production pin or deployment
changes.

The reproducible fixture is
[`agentplane/native/claude/x/remote_tools`](../native/claude/x/remote_tools/README.md).
It uses a scripted loopback Messages endpoint and real native stream-json/MCP
control messages. It does not impersonate an account, seed feature caches, inject
embedded exports, or contact the real Anthropic bridge. The configured model and
bridge origins are loopback. Nonessential traffic is disabled; unexpected proxy
traffic goes to a loopback rejecting endpoint.

Local native reads delivered nested instructions to the next model request;
generic MCP reads did not. Native resume retained read-before-edit state, while
an independent session did not. Explicit hook denial blocked both native and
MCP reads. Both forwarding startup variants made zero requests to the loopback
bridge destination.

Native serving is not established merely by enabling its local forwarding
switch: this fixture has a synthetic API token and custom provider endpoint,
without an eligible account or organization. The absence of a bridge connection
under these conditions cannot identify one particular gate as the cause.

## Captured ordinary CLI behavior

[RBE invocation 71a785c2](https://app.buildbuddy.io/invocation/71a785c2-51e4-428e-ba91-677e6ac92087)
ran all six pytest cases successfully (17.5 seconds including process startup and
teardown). The fixture uses the normal CLI entry point and real native tool
implementation. Its deterministic model selects calls; no model inference
quality is being tested.

| Observation                                              | On-wire or file evidence                                                                                                                                                |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Root instruction before file access                      | `native-forward-{False,True}-before-read.json`: root marker once; nested and sibling markers absent.                                                                    |
| Native Read of `nested/editable.txt`                     | Next request's `native_read` tool result includes file contents and a `<system-reminder>` containing `nested/CLAUDE.md`; nested marker once; root once; sibling absent. |
| Generic driver MCP read of the same file                 | `mcp-after-read.json`: successful file contents, root once, nested and sibling markers absent.                                                                          |
| Generic MCP Read then native Edit                        | `mcp-read-native-edit.json`: `File has not been read yet. Read it first before writing to it.`; file unchanged.                                                         |
| MCP traversal and symlink escape                         | `mcp-outside-denial.json`: both return the fixture's explicit `outside fixture workspace` error; outside contents absent and unchanged.                                 |
| Native Edit without a prior Read                         | `state-unread-edit.json`: error and unchanged `before` file.                                                                                                            |
| Native Read followed by Edit                             | `state-read-edit.json`: successful edit and `after` file.                                                                                                               |
| Native `--resume` then Edit without a new Read           | `state-resume-edit.json` and `state-outcomes.json`: success; file becomes `resume`.                                                                                     |
| Independent session, same config and workspace           | `state-independent-edit.json`: error; file remains `resume`.                                                                                                            |
| Explicit PreToolUse denial                               | `denial-Read.json` and `denial-mcp__fixture__read_file.json`: error containing the denial reason; no nested marker; MCP function never called.                          |
| Local forwarding switch off/on, bridge channel requested | `native-forward-{False,True}-bridge.json` are both `[]`; native local Read still works.                                                                                 |

Enabling `--setting-sources=project` restored project instruction loading in
this SDK fixture. The shared harness default `--setting-sources=` produced no root
marker in the first model request. That initial failure is recorded in
[RBE invocation 70039d46](https://app.buildbuddy.io/invocation/70039d46-b3df-4e81-ab60-8191a9629cae).
The experimental launcher enables only the fixture's project source; it does not
change shared launch defaults. Hooks remain enabled so the same fixture can
exercise actual native PreToolUse denial.

The distinguishing native payload is the _next model request_, not merely a
user-visible read log: the `tool_result` for `native_read` includes
`Contents of .../nested/CLAUDE.md` and the nested marker inside a system reminder.
The root marker lives in an earlier user system reminder. Both are present once
in that next request. The MCP server returns only file contents, and the CLI
does not augment it with the nested instruction reminder.

This means a generic driver-hosted MCP file service needs an explicit instruction
contract and read/edit-state policy if it is to preserve native behavior. It
cannot inherit native nested instruction loading or native prior-read state
merely by reading the same path. These observations do not
answer whether the native _remote serving kit_ preserves that behavior.

## Version-specific startup gates from embedded source

The broader [execution-placement investigation](claude_execution_placement.md)
records the source-inspection context. Static inspection of the installed
2.1.296 executable identified the following
sequence. This describes code paths, not evidence that the account can use them.
The installed binary SHA-256 was
`8ae9374664a714e8c56d18c6ed22aa024325e7d4b753ff0a69727a2571425537`.

1. `CLAUDE_CODE_REMOTE_TOOLS_FORWARD` enables the local path. The native policy
   also asks for the `tengu_violin_wood` feature; cloud-client registration adds
   `tengu_violin_willow`.
2. Serving readiness must settle. The device bridge then checks feature
   eligibility and egress/provider policy. Its diagnostic combines nonessential
   egress, non-first-party provider, and remote-session policy denial.
3. Bridge transport can additionally refuse when device proof cannot be checked
   and trusted devices are required or unknown. Account resolution and an
   organization UUID are required before tool-group registration.
4. `CLAUDE_CODE_REMOTE_TOOLS_SESSION_CHANNEL=false` selects bridge transport.
   `CLAUDE_REMOTE_TOOLS_BRIDGE_URL` can supply the bridge destination; this does
   not bypass eligibility, account, provider, or trust checks.

The public feature client has stub `getEnvironmentOverrides()` and
`readConfigOverrides()` methods. A declared internal feature-override environment
variable therefore does not establish a supported override route. Disk feature
cache values are another input in the implementation; fabricating those values
would be a source experiment, not entitlement evidence.

The serving implementation advertises native tools through a serving kit, then
uses the native tool execution pipeline. Its per-caller context carries
`readFileState` and `toolState`, but starts with `messages: []` and a no-op
`enqueuePendingMemoryUpdate`. Its attachment collector skips non-hook
attachments other than read-truncation notices, including `nested_memory`.
Those facts raise an instruction-propagation question; they do not prove what a
hosted caller receives, because another synchronization path could provide it.
That question needs a real served tool call and inspection of the caller's next
model request.

## Optional embedded-module probe

A bounded source-entry experiment tried `BUN_BE_BUN=1` with a script importing
`/$bunfs/root/chunk-bxhcgs7p.js` from the unchanged pinned binary. It did not
execute the script: the binary exited 1 with
`Not logged in · Please run /login`. No exports or tool execution were observed.
The optional probe is absent from the maintained suite; ordinary CLI captures
are the supported experiment entry point.

Evidence: [RBE invocation d1b76645](https://app.buildbuddy.io/invocation/d1b76645-9268-40b2-ba56-1a9b3d12a38d),
`test.outputs/embedded-runtime.json`:

```json
{ "returncode": 1, "stdout": "Not logged in · Please run /login\n", "stderr": "" }
```

## What remains unverified

An eligible native serving handshake, the actual served tool roster and schemas,
remote caller read/edit state and resume behavior, remote denial/path policy,
and root/nested instruction delivery in the remote caller's next model request
remain unverified. Ordinary local native behavior and generic MCP behavior are
comparators, not substitutes for these observations. No production architecture
or permission-policy change follows from this spike alone.
