# Seatbelt and MCP Security Integration: Complementary Sandboxing Layers

## Overview

This document explains the relationship between **seatbelt** (macOS process-level sandboxing via SBPL policies) and **MCP approval policy** (tool-level access control), and how they work together to provide defense-in-depth security.

## Two Distinct Security Boundaries

### 1. Seatbelt: Process-Level Sandbox (Runtime Isolation)

**Location**: `/home/user/ducktape/adgn/src/adgn/seatbelt/`

**What it protects**:
- **Operating system resources**: File I/O, network access, Mach IPC, system calls
- **Process isolation**: Restricts what a sandboxed process can access on the host OS
- **Execution-time boundaries**: Enforced by macOS kernel at syscall level

**How it works**:
1. Seatbelt compiles a typed `SBPLPolicy` (Python model) into SBPL text
2. The policy specifies allow/deny rules for file operations, network, Mach services, etc.
3. At runtime, `sandbox-exec -f policy.sb <command>` enforces the policy
4. The OS kernel blocks any syscall that violates the policy
5. Denials are logged to macOS unified logs (`com.apple.sandbox` subsystem)

**Example rules**:
```python
# File access
FileRule(action=Action.ALLOW, op=FileOp.FILE_READ_STAR,
         filters=[Subpath("/usr/lib")])

# Network (loopback only)
NetworkRule(action=Action.ALLOW, op=NetworkOp.NETWORK_OUTBOUND,
           local_only=True)

# Process primitives
ProcessRule(allow_process_star=True, allow_signal_self=True)
```

**Scope**: macOS only (requires `sandbox-exec`)

### 2. MCP Approval Policy: Tool-Level Access Control (Semantic Gating)

**Location**: `/home/user/ducktape/adgn/src/adgn/mcp/approval_policy/`

**What it protects**:
- **MCP tool calls**: Specific tool invocations by name and arguments
- **Policy decisions**: Custom Python rules evaluating whether a tool call is allowed
- **User oversight**: Approval workflows for dangerous operations (e.g., manual CLI execution, file edits)

**How it works**:
1. Agent attempts to call an MCP tool (e.g., `seatbelt_exec` with a policy)
2. Policy Gateway middleware intercepts the call
3. Docker-backed evaluator runs the active approval policy (user code) against the tool call
4. Policy returns a decision: `allow | deny_continue | deny_abort | ask`
   - **allow**: Tool call proceeds
   - **deny_continue**: Tool call blocked, agent continues
   - **deny_abort**: Tool call blocked, agent's turn aborts
   - **ask**: Decision deferred to human via UI (approval item)
5. Persistence tracks all approval decisions and proposals

**Example policy rule**:
```python
# Approve any read-only file operations
if tool == "editor_read":
    return {"decision": "allow"}

# Ask for approval on shell commands
if "shell" in tool or "exec" in tool:
    return {"decision": "ask"}

# Deny dangerous Mach operations
if "mach" in tool or "signal" in tool:
    return {"decision": "deny_abort"}
```

**Scope**: All platforms (Docker-based evaluation)

## How They Work Together: Defense-in-Depth

### Layered Security Model

```
┌─────────────────────────────────────────────────────────┐
│  MCP Approval Policy Layer                              │
│  ─────────────────────────────────────────────────────  │
│  1. "seatbelt_exec" tool call arrives at agent          │
│  2. Policy decides: is this tool allowed?               │
│  3. Decision: allow | deny_continue | deny_abort | ask  │
│                                                         │
│  If blocked here, sandboxed command never runs          │
└─────────────────────────────────────────────────────────┘
                          ↓ (if allowed)
┌─────────────────────────────────────────────────────────┐
│  Seatbelt Runtime Isolation Layer                       │
│  ─────────────────────────────────────────────────────  │
│  1. sandbox-exec -f policy.sb <command>                 │
│  2. Kernel enforces SBPL rules at syscall level         │
│  3. Denials logged to macOS unified log                 │
│                                                         │
│  If blocked here, command is kernel-enforced restricted │
└─────────────────────────────────────────────────────────┘
```

### Complementary Protection

| Aspect | Seatbelt | MCP Policy |
|--------|----------|-----------|
| **Granularity** | OS-level (syscalls) | Application-level (tool names + args) |
| **Decision logic** | Static SBPL rules | Custom Python code (dynamic) |
| **Approval flow** | None (kernel enforced) | Interactive UI, audit trail |
| **Scope** | Process and descendants | MCP tool ecosystem |
| **Overhead** | Low (kernel level) | Medium (Docker evaluation) |

## Security Boundary Definitions

### What Seatbelt Protects Against

1. **Filesystem escapes**: Policy prevents access to `/etc/passwd`, system libraries, or other sensitive paths
2. **Network escapes**: Policy can restrict to loopback only, preventing exfiltration
3. **IPC escapes**: Mach service lookups can be whitelisted to prevent privilege escalation
4. **Process manipulation**: `process-exec`, `process-fork`, `signal` rules prevent process injection

**Example**: Even if the approval policy mistakenly allows a malicious policy, the kernel will still enforce its restrictions.

### What MCP Approval Policy Protects Against

1. **Semantic misuse**: Prevents an agent from calling tools it shouldn't (e.g., `delete_all_files`)
2. **Policy bypass attempts**: Detects if an agent tries to craft a suspicious policy and requires approval
3. **Dangerous operations**: Blocks dangerous tool invocations before they reach sandboxed execution
4. **Audit and visibility**: Provides human-readable approval history and decision transparency

**Example**: Even if seatbelt were somehow misconfigured, the approval policy can still reject a `run_as_root` tool call.

## Integration Points

### 1. MCP Seatbelt Exec Server

**File**: `/home/user/ducktape/adgn/src/adgn/mcp/exec/seatbelt.py`

The `seatbelt_exec` MCP server implements stateless, per-call sandboxing:

```python
class SandboxExecArgs(BaseModel):
    policy: SBPLPolicy          # SBPL policy (user-provided, per call)
    argv: list[str]             # Command to execute
    max_bytes: int              # Output size limit
    timeout_ms: TimeoutMs       # Execution timeout
    trace: bool                 # Enable seatbelt tracing
    stdin_text: str | None      # Input data
```

**Security implications**:
- Each call includes a full policy (no state carried between calls)
- Approval policy middleware evaluates whether the call is allowed **before** the policy is even compiled
- The policy text itself is validated (self-check via Docker) before activation in approval policy engine

### 2. Approval Policy Engine

**File**: `/home/user/ducktape/adgn/src/adgn/agent/approvals.py`

The `ApprovalPolicyEngine` manages the active approval policy:

```python
class ApprovalPolicyEngine:
    def self_check(self, source: str) -> None:
        """Validate policy code before activation (Docker-backed)."""
        run_policy_source(docker_client=..., source=source, ...)

    async def approve_proposal(self, proposal_id: str) -> None:
        """Approve and activate a proposed policy change."""
        self.self_check(got.content)  # Validate first
        self.set_policy(got.content)  # Activate
```

**Security implications**:
- Policy proposals are validated by executing them in an isolated container
- Activation requires explicit approval (via resource/tool)
- Changes are broadcast via MCP resource notifications for audit

### 3. Policy Gateway Middleware

**File**: `/home/user/ducktape/adgn/src/adgn/mcp/policy_gateway/middleware.py`

The middleware intercepts all tool calls:

```python
# Pseudo-pseudocode
async def call_tool(context, tool_name, arguments):
    policy_request = PolicyRequest(name=tool_name, arguments=arguments)
    decision = await policy_evaluator.decide(policy_request)

    if decision == "allow":
        return await next_handler(context, tool_name, arguments)
    elif decision == "ask":
        approval = await approval_hub.await_decision(call_id, request)
        if approval.allow:
            return await next_handler(context, tool_name, arguments)
    elif decision == "deny_abort":
        raise TurnAbortDecision("Tool blocked by policy")
```

**Security implications**:
- Every tool call is evaluated against the active policy
- The gateway ensures no tool reaches execution without a decision
- Decisions are persisted and auditable

## Seatbelt-MCP TODO Items

These are planned improvements that strengthen the seatbelt-MCP integration:

### Cross-Layer Awareness
- [ ] **MCP policy awareness of seatbelt policies**: The approval policy can inspect the proposed seatbelt policy (via `SandboxExecArgs.policy`) and make decisions based on it
  - Example: "allow seatbelt_exec only if policy.files is non-empty" (require explicit file whitelist)
  - Location: `src/adgn/agent/policies/default_policy.py`

- [ ] **Seatbelt policy templates via MCP resources**: Pre-built policies as MCP resources, with versioning
  - Example: `resources://seatbelt/templates/python-readonly` → `SBPLPolicy`
  - Location: `src/adgn/mcp/resources/server.py` (add seatbelt template resources)

- [ ] **Unified deny/approval audit log**: Combine seatbelt kernel denials with MCP approval decisions
  - Both logged under a single audit trail for visibility
  - Location: `src/adgn/agent/persist/` (extend approval history model)

### Dynamic Policy Updates
- [ ] **Live policy injection**: Allow approval policy to modify seatbelt policies before execution
  - Example: Policy says "yes, but restrict to /tmp" → modify policy before sandbox-exec
  - Location: `src/adgn/mcp/exec/seatbelt.py` + policy gateway

- [ ] **Per-tool default policies**: Define a fallback seatbelt policy when `seatbelt_exec` is called without one
  - Example: UI calls `seatbelt_exec` without args → use a safe "read-only" default
  - Location: `src/adgn/mcp/exec/seatbelt.py`

### User Experience
- [ ] **Policy proposal UI for seatbelt policies**: Let users propose new seatbelt policies as drafts, similar to approval policy proposals
  - Example: "Save this policy as a template" → persists, can be reused
  - Location: UI + `src/adgn/agent/approvals.py`

- [ ] **Policy violation explanations**: When seatbelt denies a syscall, render an explanation of why
  - Example: "Access to /etc denied by policy rule: (deny file-read* (literal \"/etc\"))"
  - Location: `src/adgn/seatbelt/runner.py` (extend trace parsing)

### Validation & Safety
- [ ] **Policy compatibility checks**: Warn if an approval policy decision conflicts with a seatbelt policy
  - Example: Approval says "yes" but seatbelt policy says "no" → log warning
  - Location: `src/adgn/agent/approvals.py` + policy evaluator

- [ ] **Seatbelt policy linting via MCP**: Expose policy validation as an MCP tool for the agent
  - Example: `seatbelt_validate_policy` tool → returns findings
  - Location: `src/adgn/mcp/exec/seatbelt.py`

## Configuration and Deployment

### Approval Policy with Seatbelt Awareness

The default approval policy can include seatbelt-specific rules:

```python
# In default_policy.py or user-defined policy
def decide(request):
    name = request["name"]
    args = request["arguments"]

    # Seatbelt-specific: require non-empty file rules
    if "seatbelt_exec" in name:
        policy = args.get("policy", {})
        if not policy.get("files"):
            return {"decision": "ask", "rationale": "Policy has no file rules; requires approval"}

        # Check for overly permissive network rules
        for net_rule in policy.get("network", []):
            if not net_rule.get("local_only"):
                return {"decision": "ask", "rationale": "Unrestricted network access requires approval"}

    return {"decision": "allow"}
```

### Seatbelt Presets for Common MCP Use Cases

Pre-built policies for common scenarios:

```python
# In seatbelt/presets.py (future)
JUPYTER_KERNEL = SBPLPolicy(
    files=[
        FileRule(action=Action.ALLOW, op=FileOp.FILE_READ_STAR,
                filters=[Subpath("/usr/lib"), Subpath("/opt/venv")]),
        FileRule(action=Action.ALLOW, op=FileOp.FILE_WRITE_STAR,
                filters=[Subpath("/tmp"), Subpath("/workspace")]),
    ],
    network=[NetworkRule(action=Action.ALLOW, op=NetworkOp.NETWORK_OUTBOUND, local_only=True)],
    process=ProcessRule(allow_process_star=True),
)

# Usage in agent
await seatbelt_exec(policy=JUPYTER_KERNEL, argv=["python", "-m", "ipykernel"], ...)
```

## References

### Seatbelt Documentation
- `docs/seatbelt/TODO.md` - Implementation roadmap
- `src/adgn/seatbelt/model.py` - SBPL policy types
- `src/adgn/seatbelt/runner.py` - Sandbox execution
- `src/adgn/seatbelt/compile.py` - SBPL compilation
- `docs/llm/sandboxer/` - Jupyter sandboxing with seatbelt

### MCP Security Documentation
- `docs/mcp-server-architecture.md` - MCP approval policy layer
- `src/adgn/mcp/approval_policy/` - Policy server implementation
- `src/adgn/mcp/policy_gateway/middleware.py` - Tool call interception
- `src/adgn/agent/approvals.py` - Approval hub and engine
- `AGENTS.md` - Approval policy conventions (see "Approval Policy" section)

### Related Components
- `src/adgn/mcp/exec/seatbelt.py` - MCP server for seatbelt execution
- `src/adgn/agent/policy_eval/runner.py` - Docker-backed policy evaluation
- `src/adgn/mcp/policy_gateway/signals.py` - Policy decision signaling

## Key Principles

1. **Layered defense**: MCP policy gates access semantically; seatbelt enforces OS-level isolation
2. **No single point of failure**: Misconfiguration in one layer doesn't compromise the other
3. **Transparency**: Both layers provide audit trails (policy decisions + seatbelt denials)
4. **User control**: Approval policy is user-writable; policies are proposals subject to review
5. **Explicit over implicit**: No hidden defaults; both policies are explicit and validated

