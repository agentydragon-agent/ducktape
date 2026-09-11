# SSH Executor for Agentplane

Status: **planned**, replacing the earlier `HOSTEXEC`/hostexecd adapter direction. This is a plan
change only; it does not yet alter the existing Haku Console hostexec implementation.

## Outcome

An approved Agentplane Action can run one non-interactive command as a configured Unix user on a
configured machine over ordinary SSH, using a private key held by Kubernetes. The Action Service
records the existing Action/Execution lifecycle and a bounded terminal result. A lost connection
never causes a blind retry: the result is `execution_unknown` when Agentplane cannot establish
whether the remote command ran or completed.

The executor is a transport and credential-selection layer. It does **not** decide which commands
are allowed. The existing decider/Decision layer remains responsible for human or policy approval
of the complete Action, including the command, machine, user, and any key-selection input.

## Initial slice (P0 behavior)

- Add an Agentplane `ssh` Executor binding and adapter behind the existing `Executor` contract.
- Define and register the executor's `list_targets` and `exec` Actions, including their input
  schemas and descriptions, in executor code. Configuration selects the executor and supplies
  deployment data; it does not define or override the Action catalog contract.
- Execute through the OpenSSH client rather than inventing a remote command protocol.
- Provide a read-only introspection Action such as `list_targets` so an Agent can discover which
  machine/user pairs have registered SSH credentials before requesting execution. This is an
  Action, not a projection of hidden executor configuration, and therefore remains auditable and
  subject to the existing decider/human approval path.
- Support non-interactive command execution only; no PTY, shell session, forwarding, or interactive
  stdin in the first slice.
- Let `exec` request a per-Execution timeout, defaulting to the configured maximum and never
  exceeding it. The timeout is part of the approved Action arguments and is enforced by the SSH
  executor as an execution bound, not as a command-policy decision.
- Capture bounded stdout and stderr, with explicit connect, execution, and output limits.
- Preserve Action Service exactly-once dispatch and lease semantics: one claimed Execution may cause
  one SSH invocation, and a lost lease or disconnected executor must not retry it.
- Return safe, bounded terminal errors for connection/auth/exit failures. If the SSH process or
  broker disappears after a command may have started, return or retain `execution_unknown`.
- Record which configured SSH key binding, host, Unix user, and command outcome were used as
  redacted provenance. Never persist or project private-key material.

`list_targets` returns only the stable target availability needed for selection, for example
`host` and `user` (and, if needed for explicit selection, a reviewed non-secret key identifier).
It must not return Secret names, mounted paths, private-key contents, fingerprints, filesystem
metadata, or other credential-bearing configuration. It must not probe the remote hosts merely to
answer the inventory question: registration in the reviewed ConfigMap is the source of availability.

The first implementation should exercise the real SSH process seam with a local test SSH server or
an equivalent deterministic fixture. A test that only mocks the entire SSH client is insufficient.

## Kubernetes configuration

Private keys are Kubernetes Secrets. A reviewed ConfigMap YAML maps each key to the machine and
Unix user for which it may be used. The mapping is routing metadata, not a command allowlist.
Conceptually:

```yaml
keys:
  - id: wyrm2-coder
    secret:
      name: agentplane-ssh-keys
      key: wyrm2-coder
    host: wyrm2.example
    user: coder
  - id: rugged-coder
    secret:
      name: agentplane-ssh-keys
      key: rugged-coder
    host: rugged.example
    user: coder
```

The exact schema remains to be aligned with the deployment's existing SOPS/Secret-controller
conventions. The implementation must validate at startup that every referenced Secret-mounted key
has a unique mapping and that host/user/key lookups are unambiguous. The Action Service pod receives
only the mounted private-key files (or an SSH-agent socket); keys never enter PostgreSQL, Action
payloads, logs, or transcripts.

The first deployment may use long-lived keys, as explicitly accepted for this slice. Key rotation
is a deployment concern: update the Secret and roll/reload the Action Service so no stale key
material remains in the running process. Terraform/GitOps/SOPS or an external-secrets controller
may own rotation and distribution; do not make Agentplane a second secret-management authority.

`known_hosts` is configuration-owned and must be mounted alongside the keys. Strict host-key
checking is required. Unknown or changed host keys fail closed; the executor must not accept a
caller-supplied host-key policy.

## Request and selection contract

The executor receives an already-approved immutable `ExecutionRequest`. Its action arguments identify
the target machine and Unix user, and may identify one configured key mapping when more than one key
is valid for that pair. The executor performs only the mechanical lookup and SSH invocation:

- reject a missing or ambiguous host/user/key mapping;
- reject a key whose configured host/user does not match the request;
- use the exact approved command arguments without applying a second command policy;
- resolve the key file and `known_hosts` from process configuration;
- invoke OpenSSH with forwarding and PTY disabled.

The decider must bind approval to the complete target and command. This prevents a caller from
reusing an approval for `wyrm2/coder` against `rugged/root`, while keeping command authorization out
of the SSH layer as requested.

The SSH executor owns the stable Action names and schemas: `list_targets` is the inventory read and
`exec` accepts the target tuple, command, and optional bounded timeout. The reviewed settings file contains only the
executor binding and SSH target/transport configuration; it cannot add arbitrary SSH Actions, change
their schemas, or turn a configuration entry into an unreviewed execution surface.

`exec.timeout_seconds`, when supplied, must be a positive number no greater than the configured
`command_timeout_seconds`; omission uses that configured maximum. A timeout after the remote command
may have started is an `execution_unknown` outcome, never an automatic retry.

The introspection result is derived from the same validated in-process configuration used for
execution. A target is listed only when its key mapping is structurally valid and its referenced
key file is present at executor startup; `list_targets` does not disclose why an individual target
was omitted beyond the safe availability result.

## Credential and process boundary

Prefer the boring first implementation: OpenSSH reads a mounted key file with restrictive
permissions. Evaluate an SSH-agent sidecar only if it materially improves rotation or prevents key
material from being readable by the Action Service process. An agent is not automatically better:
its socket becomes a bearer for every loaded key, so the socket must be private to the executor,
never mounted into the Action caller or general workload, and its key inventory must remain
configuration-controlled.

A later migration may use short-lived SSH certificates or an external signer. That is not required
for the initial long-lived-key slice. Whichever mechanism is selected, the Action Service must not
become the durable authority for issuing credentials.

## Future: reconnectable remote processes

Do not add Ctrl+C, stdin streaming, PTYs, or process-control APIs to the first slice. Design the
execution result so a later process-control extension can bind controls to the same durable
Execution/request identity rather than launching a second command. That future extension needs a
remote process handle or durable session primitive (for example a managed `tmux`/systemd scope or a
purpose-built remote helper), reconnect/authentication rules, signal authorization, and tests proving
that Ctrl+C targets the original process and cannot target an unrelated PID. Plain one-shot SSH
exec by itself does not provide a safe durable process identity after disconnect.

## Acceptance evidence

1. A reviewed Action reaches the SSH executor and runs exactly once on `wyrm2` as `coder` with the
   configured key; the durable Execution contains bounded output and redacted target/key provenance.
2. The same configuration works for `rugged`, while a mismatched host/user/key selection fails
   before SSH invocation.
3. Unknown and changed host keys fail closed.
4. Oversized stdout/stderr is truncated or rejected according to the documented bound and never
   escapes through an error or transcript.
5. SSH authentication failure and non-zero remote exit are terminal failures with safe bounded
   error codes.
6. Disconnecting the executor after SSH may have started produces `execution_unknown`; recovery
   never blindly starts the command again.
7. A duplicate dispatch/claim cannot create two SSH invocations.
8. Rotating a Kubernetes Secret and rolling the executor causes subsequent Actions to use the new
   key without exposing either key in Action state or logs.
9. A real staging run proves the existing decider/human approval path authorizes the full target and
   command, while the SSH executor itself performs no command allowlist check.
10. A reviewed introspection Action lists the configured `wyrm2/coder` and `rugged/coder` targets
    without exposing Secret names, key paths, fingerprints, or private-key material, and does not
    initiate network connections to either host.
11. `exec` accepts a shorter timeout, defaults it when omitted, rejects a timeout above the
    configured maximum, and reports a timed-out command as `execution_unknown` once it may have
    started remotely.
