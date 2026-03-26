# 91c789ff RE Plan

## Binary Info

| Property         | Value                                          |
| ---------------- | ---------------------------------------------- |
| **Build ID**     | `91c789ff2a9e647bf7b1914e351f67b89713c4ef`     |
| **Release**      | `process_api_2026-03-23-22-49`                 |
| **Size**         | ~3.2 MB                                        |
| **Linking**      | Static-pie                                     |
| **Source files** | 10 modules                                     |
| **Rust**         | stable `1aa9bab4ecbce4859eaad53000f78158ebe2be2c` |

## Features

### 1. Firecracker VM Init (`--firecracker-init`)

The largest module. When enabled, process_api acts as a full VM init
system (PID 1) inside a Firecracker microVM:

- Mount essential filesystems (/proc, /sys, /dev, /dev/pts, /dev/shm, cgroup2)
- Set up networking (IP=192.0.2.2/24, GW=192.0.2.1, MTU=1400)
- Write /etc/hostname, /etc/hosts, /etc/resolv.conf (nameserver 8.8.8.8) at init
  (Binary: 91c789ff — DNS/network config is now set up at init time)
- Mount root filesystem from /dev/vda or /dev/vdb (ext4 or squashfs)
- pivot_root or MS_MOVE+chroot fallback
- Mount model tools from /dev/vdb (squashfs)
- Create /dev/fuse, spawn rclone for FUSE mounts (log prefix: `fuse_spawn`)
- Mount rclone_tools from block device
- Mount readonly block devices
- Write config files (etc_hosts, resolv_conf, ca_cert_pem)
- Load environment variables from /container.env (JSON)
- Scrub auth tokens from saved configs
- Set system clock via clock_settime
- Drop CAP_SYS_RESOURCE
- Write /proc/sys/vm/drop_caches

**Snapstart**: `/mount_config.json` / snapstart template mode removed in 91c789ff.
The `POST /mount_root` endpoint still exists for dynamic mount config delivery.

### 2. CLI Flags

| Flag                   | Env Var              | Description                            |
| ---------------------- | -------------------- | -------------------------------------- |
| `--firecracker-init`   | `FIRECRACKER_INIT`   | Run as Firecracker VM init             |
| `--listen-uds`         | `LISTEN_UDS`         | Unix domain socket WebSocket listener  |
| `--listen-vsock-port`  | `LISTEN_VSOCK_PORT`  | Vsock WebSocket listener (Firecracker) |
| `--control-vsock-port` | `CONTROL_VSOCK_PORT` | Vsock control server (Firecracker)     |

Note: `--addr` is Optional since vsock/UDS are alternatives.

### 3. Control Server Endpoints

| Method | Path                            | Description                                               |
| ------ | ------------------------------- | --------------------------------------------------------- |
| `POST` | `/mount_root`                   | Apply mount root config (enabled with --firecracker-init) |
| `POST` | `/fs_free`                      | Flush buffers, drop caches, FIFREEZE (Binary: 91c789ff)   |
| `POST` | `/fs_thaw`                      | FITHAW — thaw frozen filesystem (Binary: 91c789ff)        |
| `POST` | `/auth_public_key/write_etc_files` | Set Ed25519 auth key + write /etc files (Binary: 91c789ff) |

### 4. Vsock Support

Both the WebSocket listener and control server can operate over vsock
(Firecracker's virtio socket interface) instead of TCP. Uses `tokio-vsock 0.7.2`.
Connections validated against CID == 2 (host).

### 5. UDS Support

WebSocket listener can operate over a Unix domain socket via `--listen-uds`.

### 6. JWT Auth Removed

JWT authentication (`jsonwebtoken` crate, `TokenClaims` struct, `Invalid JWT
signature`, `JWT token has expired`) is completely absent from 91c789ff.
Auth is now handled by the `POST /auth_public_key/write_etc_files` endpoint
without JWT.

### 7. Container Info Persistence Removed

`/container_info.json` reading/writing and `detect_container_name()` are
removed in 91c789ff. The container name is no longer persisted to disk.

## Key Dependencies

| Crate         | Version | Purpose                       |
| ------------- | ------- | ----------------------------- |
| `tokio-vsock` | —       | Async vsock streams/listeners |
| `libc`        | —       | Raw syscalls for init path    |

Note: `jsonwebtoken` dependency removed in 91c789ff.
Rust toolchain changed from `nightly-2025-12-06` to stable `1aa9bab4...`.

## Completed (91c789ff update)

- [x] Copied from e409c31a as baseline
- [x] Updated io.rs: new ServerMessage variants (KeepAlive, Closed, AlreadyClosed,
      IoWriteBufferFull, AttackAttemptUrl, HttpFormatIpSocket), container_shutdown event,
      timeout_secs/limit_bytes fields already present in e409c31a source
- [x] Updated control_server.rs: /fs_sync → /fs_free + /fs_thaw, updated
      /auth_public_key → /auth_public_key/write_etc_files with new fields,
      removed JWT auth, removed container_info.json persistence
- [x] Updated main.rs: removed detect_container_name(), added DNS/network setup
      (/etc/hostname, /etc/hosts, resolv.conf), updated fuse_spawn message strings,
      updated release version string
- [x] Updated firecracker_init.rs: removed TokenClaims/JWT struct, removed
      snapstart template mode, added /etc/hostname + /etc/resolv.conf init,
      updated fuse_spawn strings
- [x] Updated BUILD.bazel: removed jsonwebtoken comment, updated note
- [x] Updated README.md and PLAN.md to reflect 91c789ff

## Previously Completed (carried from e409c31a)

- [x] Phase 1: String census and diff analysis
- [x] Phase 1: Section comparison (static-pie vs dynamic)
- [x] Phase 1: INIT string extraction and cataloging
- [x] Phase 1: New CLI flag identification
- [x] Phase 1: Source file path extraction (src/firecracker_init.rs)
- [x] Phase 2: objdump cross-reference analysis for init code (0xfb394..0x103000)
- [x] Phase 3: firecracker_init.rs reconstruction (MountRootConfig, FuseMountConfig, full init sequence)
- [x] Phase 3: main.rs updated (new CLI flags, firecracker-init code path, UDS/vsock listeners)
- [x] Phase 3: control_server.rs updated (mount_root, fs_sync, vsock, persist)
- [x] Phase 4: BUILD.bazel updated (new source file, new deps, static-pie note)
- [x] Phase 4: FIFREEZE/FITHAW ioctl values verified
- [x] Phase 4: `create_device_nodes()` implemented
- [x] Phase 4: `scrub_auth_tokens()` verified complete
- [x] Phase 4: Binary string comparison
- [x] Phase 5: Documentation updated

## String Analysis Findings (91c789ff)

### FIFREEZE/FITHAW Verification

Confirmed correct against Linux kernel headers:

- `FIFREEZE = _IOWR('X', 119, int) = 0xC0045877`
- `FITHAW = _IOWR('X', 120, int) = 0xC0045878`

### fs_free / fs_thaw Endpoints (91c789ff)

The old `/fs_sync` endpoint is replaced by two separate endpoints:

- `POST /fs_free` (H3 = 3-char suffix in HTTP/2 pseudo-header): freeze
- `POST /fs_thaw` (H9 = 9-char suffix): thaw

String evidence: `/fs_freeH3` and `/fs_thawH9` in new binary (replacing `/fs_syncH9`).
Log string `[CONTROL] / thawed` confirms thaw is a separate operation.

### auth_public_key Endpoint (91c789ff)

Expanded to `POST /auth_public_key/write_etc_files`. New request body fields:
- `process_id_reuse` — allow reuse of process IDs
- `allow_process_id` — specific process ID to allow
- `memory_limit_bytes` — per-connection memory limit

JWT auth strings (`Invalid JWT signature`, `JWT token has expired`,
`struct TokenClaims`) are completely absent — JWT validation removed.

### Device Nodes

Binary string evidence shows only 4 device paths as standalone literals:
`/dev/null`, `/dev/random`, `/dev/urandom`, `/dev/tty`. `create_device_nodes()`
matches. `/dev/zero`, `/dev/console`, `/dev/ptmx` not present.

### DNS / Network Config at Init (91c789ff)

New strings in init path: `/etc/hostname`, `/etc/hosts`, `nameserver 8.8.8.8`
in `/etc/resolv.conf`. These are now written during `run_firecracker_init()`
before the main service loop.

### fuse_spawn Log Prefix (91c789ff)

Old binary: `fuse_mounts FAILED`. New binary: `fuse_spawn FAILED` / `fuse_spawn ok`.
Log prefix changed from `fuse_mounts` to `fuse_spawn`.

### New WebSocket Message Variants (91c789ff)

`KeepAlive`, `Closed`, `AlreadyClosed`, `IoWriteBufferFull`,
`AttackAttemptUrl`, `HttpFormatIpSocket` added to `ServerMessage` enum.
New event type: `container_shutdown`.

### Control Server Vsock CID Validation

Binary string found: `"[CONTROL] [SECURITY] Rejected connection from non-host CID "`.
Vsock control server is still a stub in RE source. Requires tokio-vsock.

### tokio-vsock Crate Status

`tokio-vsock` is not in the root `Cargo.toml` and remains commented out in
`BUILD.bazel`. Adding it requires:

1. Add crate entry to root `Cargo.toml`
2. Run `CARGO_BAZEL_REPIN=1 bazel build @crates//:all`
3. Uncomment dep in `BUILD.bazel`

## Open Items

- [ ] Full vsock listener implementation (requires tokio-vsock in `Cargo.toml` + Bazel repin)
- [ ] `POST /auth_public_key/write_etc_files` full request body deserialization
- [ ] DNS/network setup exact implementation in `run_firecracker_init()`
- [ ] Network ioctl implementation detail (SIOCSIFADDR etc.)
- [ ] Behavioral test harness
