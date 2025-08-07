// Relevant pieces of the Bash tool object and its call pipeline.
// This is not a runnable module; it’s a verbatim extraction for inspection.

// --- Input schema snippets (uses a zod-like `g` in the original bundle) ---
// var fOB = g.strictObject({...});
// var RF8 = fOB.extend({...});
// These schemas define the Bash tool input: { command, timeout?, description?, (run_in_background?) }

// Short helpers used by the tool (full bodies are extracted in other files):
// - MG1(command: string) => boolean  // command injection-ish check
// - kF8(command: string) => boolean  // is allowed/safe command pattern
// - _F8(command: string) => boolean  // ok for auto-background
// - dq0(input, ctx, qOB?)            // permission + prefix analysis
// - hq0(input, cwd, permCtx)         // cd/ls boundary checks
// - _OB(cmd, code, stdout, stderr)   // return-code interpretation
// - d$2()                            // returns executor (Ep4)

// ----- Bash tool object (aka xQ) -----
var xQ = {
  name: EX, // EX resolves to the string "Bash" in user-facing name

  async description({ description: A }) {
    return A || "Run shell command";
  },

  async prompt() {
    return MLB();
  },

  isConcurrencySafe(A) { return this.isReadOnly(A); },

  isReadOnly(A) {
    let { command: B } = A;
    if ("sandbox" in A ? !!A.sandbox : !1) return !0;
    if (!MG1(B)) return !1;
    return VS(B).every((D) => { if (!MG1(D)) return !1; return kF8(D); });
  },

  inputSchema: eM1() ? RF8 : fOB,

  userFacingName(A) {
    if (!A) return "Bash";
    return ("sandbox" in A ? !!A.sandbox : !1) ? "SandboxedBash" : "Bash";
  },

  isEnabled() { return !0; },

  async checkPermissions(A, B) {
    if ("sandbox" in A ? !!A.sandbox : !1) return { behavior: "allow", updatedInput: A };
    return dq0(A, B);
  },

  async validateInput(A, B) {
    let Q = hq0(A, s0(), B.getToolPermissionContext());
    if (Q.behavior === "ask") return { result: !1, message: Q.message, errorCode: 1 };
    return { result: !0 };
  },

  renderToolUseMessage(A, { verbose: B }) {
    let { command: Q } = A; if (!Q) return null; let D = Q;
    // Pretty-print HEREDOC cat subs, for display only
    if (Q.includes(`"$(cat <<'EOF'`)) {
      let Z = Q.match(/^(.*?)"?\$\(cat <<'EOF'\n([\s\S]*?)\n\s*EOF\n\s*\)"(.*)$/);
      if (Z && Z[1] && Z[2]) { let G = Z[1], F = Z[2], I = Z[3] || ""; D = `${G.trim()} "${F.trim()}"${I.trim()}`; }
    }
    if (!B) {
      let Z = D.split("\n"), G = Z.length > bOB, F = D.length > cq0;
      if (G || F) { let I = D; if (G) I = Z.slice(0, bOB).join("\n"); if (I.length > cq0) I = I.slice(0, cq0); return _7.createElement(P, null, I.trim(), "…"); }
    }
    return D;
  },

  renderToolUseRejectedMessage() { return _7.createElement(U5, null); },

  renderToolUseProgressMessage(A) {
    let B = A.at(-1);
    if (!B || !B.data || !B.data.output) return _7.createElement(yA, { height: 1 }, _7.createElement(P, { color: "secondaryText" }, "Running…"));
    let Q = B.data; return _7.createElement(iv1, { lastLines: Q.output, elapsedTimeSeconds: Q.elapsedTimeSeconds, totalLines: Q.totalLines });
  },

  renderToolUseQueuedMessage() { return _7.createElement(yA, { height: 1 }, _7.createElement(P, { color: "secondaryText" }, "Waiting…")); },

  renderToolResultMessage(A, B, { verbose: Q }) { return _7.createElement(om, { content: A, verbose: Q }); },

  mapToolResultToToolResultBlockParam({ interrupted: A, stdout: B, stderr: Q, summary: D, isImage: Z }, G) {
    if (Z) { let Y = B.trim().match(/^data:([^;]+);base64,(.+)$/); if (Y) { let W = Y[1], J = Y[2]; return { tool_use_id: G, type: "tool_result", content: [{ type: "image", source: { type: "base64", media_type: W || "image/jpeg", data: J || "" } }] }; } }
    if (D) return { tool_use_id: G, type: "tool_result", content: D, is_error: A };
    let F = B; if (B) F = B.replace(/^(\s*\n)+/, ""), F = F.trimEnd();
    let I = Q.trim(); if (A) { if (Q) I += nv1; I += "<error>Command was aborted before completion</error>"; }
    return { tool_use_id: G, type: "tool_result", content: [F, I].filter(Boolean).join("\n"), is_error: A };
  },

  async* call(A, { abortController: B, getToolPermissionContext: Q, readFileState: D, options: { isNonInteractiveSession: Z }, setToolJSX: G, messages: F }) {
    let I = "", Y = "", W, J = 0, X = !1, V;
    try {
      let j = xF8({ input: A, abortController: B, setToolJSX: G }), f;
      do if (f = await j.next(), !f.done) { let y = f.value; yield { type: "progress", toolUseID: `bash-progress-${J++}`, data: { type: "bash_progress", output: y.output, elapsedTimeSeconds: y.elapsedTimeSeconds, totalLines: y.totalLines } }; } while (!f.done);
      if (V = f.value, yF8(A.command, V.code), I += (V.stdout || "").trimEnd() + nv1, W = _OB(A.command, V.code, V.stdout || "", V.stderr || ""), W.isError) {
        if (Y += (V.stderr || "").trimEnd() + nv1, V.code !== 0) Y += `Exit code ${V.code}`;
      } else I += (V.stderr || "").trimEnd() + nv1;
      if (Qv1(Q())) Y = Bv1(Y);
      if (W.isError) throw new TN(V.stdout, V.stderr, V.code, V.interrupted);
      X = V.interrupted;
    } finally { if (G) G(null); }

    // File-readback hook (adds recent outputs to readFileState based on patterns)
    RLB(A.command, I, Z).then((j) => {
      for (let f of j) {
        let y = qF8(f) ? f : NF8(s0(), f);
        try {
          if (!x1().existsSync(y) || !x1().statSync(y).isFile()) continue;
          D.set(y, { content: MF(y), timestamp: x1().statSync(y).mtimeMs });
        } catch (c) { O1(c); }
      }
      V1("tengu_bash_tool_haiku_file_paths_read", { filePathsExtracted: j.length, readFileStateSize: D.size, readFileStateValuesCharLength: Ev(D).reduce((f, y) => { let c = D.get(y); return f + (c?.content.length || 0); }, 0) });
    });

    // Emit result (with truncation & image detection handled upstream by gM/DS)
    let H = null, z = H?.shouldSummarize === !0, $ = H?.modelReason, L = A.command.split(" ")[0];
    V1("tengu_bash_tool_command_executed", { command_type: L, stdout_length: I.length, stderr_length: Y.length, exit_code: V.code, interrupted: X, summarization_attempted: H !== null, summarization_succeeded: z, summarization_duration_ms: H?.queryDurationMs, summarization_reason: !z && H ? H.reason : void 0, model_summarization_reason: $ });
    let { truncatedContent: N, isImage: O } = gM(DS(I)), { truncatedContent: R } = gM(DS(Y));
    yield { type: "result", data: { stdout: N, stderr: R, summary: z ? H?.summary : void 0, interrupted: X, isImage: O, returnCodeInterpretation: W?.message, backgroundTaskId: V.backgroundTaskId } };
  },

  renderToolUseErrorMessage(A, { verbose: B }) { return _7.createElement(y6, { result: A, verbose: B }); }
};

// ----- Generator that bridges Bash tool -> shell executor -----
async function* xF8({ input: A, abortController: B, setToolJSX: Q }) {
  let { command: D, timeout: Z, shellExecutable: G, run_in_background: F } = A,
      I = Z || $11(),
      Y = d$2(), // obtain executor (Ep4)
      W = "",
      J = 0,
      X = !1,
      V,
      C = (N, O) => { W = N, J = O },
      K = await Y(D, B.signal, I, A.sandbox || !1, G, C),
      H;

  if (Q && process.env.ENABLE_BACKGROUND_TASKS)
    H = () => { if (V = Kq0(D, K), X = !0, Q) Q(null); let N = vOB(D); V1("tengu_bash_command_backgrounded", { command_type: N }); };

  let z = K.result;
  if (F === !0 && _F8(D) && process.env.ENABLE_BACKGROUND_TASKS) {
    V = Kq0(D, K); let N = vOB(D);
    V1("tengu_bash_command_auto_backgrounded", { command_type: N });
    return { stdout: "", stderr: "", code: 0, interrupted: !1, backgroundTaskId: V };
  }

  let $ = Date.now(), L = $ + xOB;
  while (!0) {
    let N = Date.now(), O = Math.max(0, L - N), R = await Promise.race([z, new Promise((f) => setTimeout(() => f(null), O))]);
    if (R !== null) return R;
    if (X && V) return { stdout: "", stderr: "", code: 0, interrupted: !1, backgroundTaskId: V };
    let T = Date.now() - $, j = Math.floor(T / 1000);
    if (H && !X && j >= xOB / 1000 && Q) Q({ jsx: _7.createElement(TF8, { onBackground: H }), shouldHidePromptInput: !1, shouldContinueAnimation: !0 });
    yield { type: "progress", output: W, elapsedTimeSeconds: j, totalLines: J };
    L = Date.now() + LF8;
  }
}
