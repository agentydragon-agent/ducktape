# Exec-server resets during VM OOM testing

The focused k3s Codex OOM test intermittently lost its execution transport in
[RBE invocation `26f1f4ef-4ad8-43af-b40a-928a85d234a1`](https://app.buildbuddy.io/invocation/26f1f4ef-4ad8-43af-b40a-928a85d234a1).
`write_stdin` reported a WebSocket reset and then `unknown session id` when resuming. Guest console
collection happened after VM deletion, so that particular run cannot distinguish a kernel victim,
supervisor fencing, or an exec-server defect.

Shared console and native-frame capture reproduced the same transport errors in
[full CI invocation `a3253f3b-1c60-5d2d-8af6-139ef98af9b0`](https://app.buildbuddy.io/invocation/a3253f3b-1c60-5d2d-8af6-139ef98af9b0).
Its console establishes the sequence on 2026-10-26 (UTC):

- `08:45:16Z`: the kernel kills only the allocating `awk` (`oom_score_adj=1000`) in the executor
  cgroup. The leaf reports `oom_kill=1`, `oom_group_kill=0`, and a 256 MiB peak.
- In the same second, Runner reports a health-probe read deadline and fences the executor.
- `08:45:19Z`: a successor executor is ready. Codex cannot resume its execution session in that
  new server and returns the transport error instead of the command's exit status.

The kernel contained the allocation, but Runner's single failed three-second probe discarded the
surviving server's tool result. [PR #12143](https://github.com/agentydragon/ducktape/pull/12143)
requires three consecutive failed probes, resetting after a success, while retaining the five-second
probe interval, per-probe deadline, process-exit cleanup and no-replay rule.

Both focused repetitions in
[RBE invocation `0b3c2df1-04ad-4fb8-95bf-18105d011216`](https://app.buildbuddy.io/invocation/0b3c2df1-04ad-4fb8-95bf-18105d011216)
passed before the Runner change: the kernel killed the allocator, Codex reported exit `137`, Runner
and the app-server kept their identities, and a follow-up succeeded in the same executor leaf.
Run 1 also records a probe-driven restart before its baseline command: the retired cgroup had no
OOM events and an 83 MiB peak. These passes show why repeated runs and console evidence matter;
they do not establish recovery from a missed probe during an active command.

The combined artifact and Runner changes passed all three full VM-suite repetitions (nine tests) in
[RBE invocation `3b3f988c-5c9b-4c66-9bbf-bcb4e7a061c6`](https://app.buildbuddy.io/invocation/3b3f988c-5c9b-4c66-9bbf-bcb4e7a061c6).
Each OOM command returned exit `137`, with unchanged Runner/app-server identities and a successful
same-leaf follow-up. All nine VM consoles and native-frame exports survived teardown. Run 3 records
a failed read probe at `09:01:17Z` while the allocator runs. The kernel kills `awk`, Codex receives
exit `137` at `09:01:19Z`, and the follow-up completes at `09:01:23Z` without an executor restart.
An earlier isolated handshake timeout also recovers, demonstrating that a successful probe resets
the failure count.

Undeclared outputs retain guest consoles and native frames in both directions under `vm-artifacts/`,
including failed turns and deleted launchers. Keep the strict exit-status, process-identity and
same-leaf follow-up assertions. The older run lacks enough console evidence to attribute its exact
failure retrospectively.

Reproduce on RBE:

```bash
bbr test //agentplane/system_tests:test_vm_sandbox_vm --test_arg=-k=tool_oom --runs_per_test=3 --test_output=errors
```
