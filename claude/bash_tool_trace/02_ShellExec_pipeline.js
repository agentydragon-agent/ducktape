// Extracted executor path: d$2() -> Ep4 -> zp4 -> Jp4 -> M$2 -> returns { result: Promise<{code, stdout, stderr, interrupted, backgroundTaskId?}>, ... }
// This file collates the execution chain and the transformations applied.

// ----- High-level entry used by Bash tool -----
function d$2() { return Ep4; }

// Ep4 = zp4: orchestrates shell binary, snapshot, wrapping the command, piping pwd capture
async function zp4(cmd, abortSignal, timeoutMs, sandbox = !1, shellExecutableOverride, onProgressCb) {
  const FallbackTimeout = Cp4; // 30 minutes in bundle
  let { binShell: I, snapshotFilePath: Y } = await B51(); // Hp4() memoized
  if (shellExecutableOverride) { I = shellExecutableOverride; Y = void 0; }

  // Generate a temp file to capture final CWD after command
  let rand = Math.floor(Math.random() * 65536).toString(16).padStart(4, "0");
  let tmp = u$2.tmpdir(); if (O9() === "windows") tmp = Xi(tmp);
  let cwdOut = `${tmp}/claude-${rand}-cwd`;

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
  if (process.env.CLAUDE_CODE_SHELL_PREFIX) full = _W1(process.env.CLAUDE_CODE_SHELL_PREFIX, full);

  let startCwd = m$2(); // resolved working dir
  if (abortSignal.aborted) return R$2();

  try {
    // Jp4 launches the shell process with "-c -l" and wires env/cwd
    let child = Jp4(I, ["-c", "-l", full], {
      env: { ...process.env, SHELL: I, GIT_EDITOR: "true", CLAUDECODE: "1", ...(sandbox ? sZ0(cmd).env : {}) },
      cwd: startCwd,
      detached: !0
    });
    // M$2 wires abort handling, progress (via onProgressCb), timeout handling; returns { result: Promise, ...}
    let handle = M$2(child, { signal: abortSignal }, timeoutMs, onProgressCb);
    return handle.result
      .then(async (res) => {
        if (res && !res.backgroundTaskId) {
          try { IE( Yp4(cwdOut, { encoding: "utf8" }).trim(), startCwd ); } catch { V1("tengu_shell_set_cwd", { success: !1 }); }
        }
      })
      .finally(() => cleanup()),
    cleanup = () => {},
    handle;
  } catch (e) {
    cleanup();
    return { background: () => null, kill: () => {}, result: Promise.resolve({ code: 126, stdout: "", stderr: e instanceof Error ? e.message : String(e), interrupted: !1 }) };
  } finally {
    cleanup();
  }
}

var Ep4 = zp4;

// Worker helpers referenced above (abbreviated signatures only for trace context):
// B51 = SA(Hp4) memoized; Hp4(): { binShell, snapshotFilePath }
//   - Kp4(): choose shell (zsh/bash/sh) present
//   - f$2(shellPath): builds a snapshot by launching a login shell and capturing env/config
// m$2(): current working directory resolver; IE(newCwd, prevCwd): update process working dir
// Jp4(shell, argv, opts): spawn shell
// M$2(child, {signal}, timeoutMs, onProgressCb): attach listeners; on data, compute W/J and call onProgressCb(W, J)
