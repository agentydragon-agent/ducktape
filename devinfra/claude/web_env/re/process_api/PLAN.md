# process_api RE Plan

## Current Binary

| Property        | Value                                              |
| --------------- | -------------------------------------------------- |
| **Build ID**    | `810fd3a49330ce58ff678d539a91723adfda88a8`         |
| **Release**     | `process_api_2026-03-25-20-38`                     |
| **Size**        | 3,326,984 bytes                                    |
| **Linking**     | Static-pie                                         |
| **Rust**        | `rustc 1.94.0-nightly (1aa9bab4e 2025-12-05)`      |
| **Source path** | `/root/src/tree/marcus-process-api/sandboxing/...` |

## RE Status by Module

All modules have 810fd3a4 headers. String references verified against
810fd3a4 via `strings -t x`. Code offsets are stale — function addresses
shifted significantly between builds (typically +0x3K-0x19K for 91c789ff
modules, incomparable for b0e4b2f4 modules).

| Module                 | Status            | Offset Status   | Notes                                        |
| ---------------------- | ----------------- | --------------- | -------------------------------------------- |
| `main.rs`              | 810fd3a4 verified | N/A             | vsock, dial-uds, CLI flags                   |
| `control_server.rs`    | 810fd3a4 verified | Exact match     | Strings at same offsets as 91c789ff          |
| `platform/unix/mod.rs` | 810fd3a4 verified | N/A             | New module                                   |
| `io.rs`                | 810fd3a4 updated  | Shifted +0x3A76 | process_id validation, bad control msg added |
| `proc_handle.rs`       | 810fd3a4 updated  | Incomparable    | 7 new ProcessInfo fields, Cgroup rename      |
| `firecracker_init.rs`  | 810fd3a4 updated  | Not verified    | Source path updated                          |
| `cgroup.rs`            | strings verified  | Shifted +0x45A0 | Logic unchanged                              |
| `oom_killer.rs`        | strings verified  | Shifted +0x3901 | Logic unchanged                              |
| `adopter.rs`           | strings verified  | Incomparable    | Logic unchanged                              |
| `state.rs`             | strings verified  | Incomparable    | Logic unchanged                              |
| `pid_tree.rs`          | strings verified  | N/A             | Logic unchanged, no offsets in original      |

## Completed

- [x] Vsock WS listener — real `tokio-vsock 0.7.2` (was UDS stub)
- [x] Vsock control server — real `tokio-vsock 0.7.2` (was no-op stub)
- [x] `--dial-uds` / `DIAL_UDS` CLI flag and dial-out implementation
- [x] `POST /sync_clock` — `clock_settime` implementation (was stub error)
- [x] `platform/unix/mod.rs` — new module matching binary layout
- [x] `ProcessInfo` struct — added 7 missing serde fields (start_wallclock_micros,
      cmd_summary, stdin_bytes, stdout_bytes, stderr_bytes, trace_emitted, trace_outcome)
- [x] `CgroupConfig` → `Cgroup` struct rename (matches binary evidence)
- [x] process_id validation — empty, too long, control chars, trace marker
- [x] `[DEBUG] bad control msg from ws:` error path in WS message loop
- [x] All module headers updated to 810fd3a4
- [x] Directory flattened — removed BuildID subdirectory

## Open Items

- [ ] Re-verify binary offsets against 810fd3a4 (all modules carry stale offsets
      from b0e4b2f4 or 91c789ff)
- [ ] Behavioral test harness
