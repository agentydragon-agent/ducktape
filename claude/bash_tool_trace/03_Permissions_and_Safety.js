// Permission and safety path for Bash tool

// High-level checks used during tool invocation:
// - checkPermissions(input, ctx) -> dq0(input, ctx)
// - validateInput(input, ctx) -> hq0(input, cwd, permCtx)
// - isReadOnly(input) -> MG1/kF8 over subcommands from VS()
// - command injection / prefix inference via qOB (prompted model), MOB/JF8 for pipes

// Splitters and validators:
function VS(command) { /* splits composed command into subcommands; see bundle */ }
function MG1(cmd) { /* returns false if dangerous shell constructs are detected */ }
function kF8(cmd) { /* whitelisted patterns (echo, git status, etc.) */ }

// cd/ls boundary checks per allowed working directories
function hq0(input, cwd, permissionContext) {
  // Parses subcommands, finds cd/ls, validates against allowed roots
  // When ask/deny conditions hit, returns an object { behavior: 'ask'|'deny', message }
}

// Permission engine
async function dq0(input, ctx, prefixInspector = qOB) {
  // 1) Exact/prefix allow/deny rules
  // 2) If pipelines present, evaluates both sides via MOB/JF8 and read-only determination
  // 3) Uses MG1 to detect command injection-like patterns
  // 4) Calls qOB to infer approved prefix or flag injection (command_injection_detected)
  // Returns { behavior, updatedInput?, message?, decisionReason?, ruleSuggestions? }
}

// Pipeline handler: splits "a | b" into left/right; right must be read-only
async function MOB(input, recur) { /* calls JF8 for pipes else passthrough */ }
async function JF8(input, left, right, recur) { /* aggregate decisions over both sides */ }

// Return-code interpretation (maps common UNIX tool non-zero codes to non-error semantics)
function _OB(cmd, code, stdout, stderr) {
  // Looks up tool-specific handlers via UF8 map; e.g., grep 1 => "No matches found"
  // Returns { isError: boolean, message?: string }
}

// Model-aided prefix/injection detector (qOB):
// Prompted with policy_spec and a Command; outputs prefix|none|git|command_injection_detected
// The result is consumed by dq0 to bias allow/ask decisions and ruleSuggestions
