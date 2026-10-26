# Exec-server resets during VM OOM testing

The focused k3s Codex OOM test intermittently lost its execution transport in
[RBE invocation `26f1f4ef-4ad8-43af-b40a-928a85d234a1`](https://app.buildbuddy.io/invocation/26f1f4ef-4ad8-43af-b40a-928a85d234a1).
`write_stdin` reported a WebSocket reset and then `unknown session id` when resuming. Guest console
collection happened after VM deletion, so that run cannot distinguish a kernel victim, supervisor
fencing, or an exec-server defect. Its cause remains unresolved.

With continuous console capture, both repetitions in
[RBE invocation `0b3c2df1-04ad-4fb8-95bf-18105d011216`](https://app.buildbuddy.io/invocation/0b3c2df1-04ad-4fb8-95bf-18105d011216)
passed: the kernel killed the allocating `awk`, Codex reported exit `137`, Runner and the app-server
kept their identities, and a follow-up succeeded in the same executor leaf. Undeclared outputs
contain each console and the native frames in both directions under `vm-artifacts/`.

Run 1 also records a separate supervisor restart **before** the baseline command:

- `08:32:41Z`: executor ready.
- `08:32:54Z`: its retired cgroup reports `memory_peak_bytes=87130112`, `oom=0`, `oom_kill=0`;
  Runner reports a WebSocket handshake deadline and restarts without replay.
- `08:32:56Z`: successor ready. The first command starts after this restart.
- `08:33:16Z`: kernel kills `awk` in the successor's executor cgroup; the executor survives.

These timestamps are UTC on 2026-10-26. Run 2 has no supervisor restart. This demonstrates a
probe-driven restart without a cgroup OOM; it does not establish the cause of the older failure.
`runner/executor.go::monitorExecutor` probes every five seconds and fences on one failed
three-second probe. Follow up by capturing a failing command with the shared diagnostics, checking
whether fencing overlaps it, and evaluating consecutive-failure tolerance under TCG CPU contention.
Keep the OOM test's exit-status and survival assertions while investigating.

Reproduce on RBE:

```bash
bbr test //agentplane/system_tests:test_vm_sandbox_vm --test_arg=-k=tool_oom --runs_per_test=2 --test_output=errors
```
