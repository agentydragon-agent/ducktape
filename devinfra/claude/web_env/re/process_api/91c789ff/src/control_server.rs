//! Reverse-engineered from process_api BuildID 91c789ff2a9e647bf7b1914e351f67b89713c4ef
//! release process_api_2026-03-23-22-49
//!
//! HTTP control server for graceful shutdown, container name updates,
//! filesystem freeze/thaw, and mount_root (Firecracker).
//!
//! Listens on TCP or vsock and handles:
//!   POST /shutdown                      - initiate graceful shutdown
//!   POST /container_name                - update the container name
//!   POST /mount_root                    - apply mount root config (Firecracker)
//!   POST /fs_free                       - flush buffers, drop caches, FIFREEZE (Binary: 91c789ff)
//!   POST /fs_thaw                       - FITHAW — thaw frozen filesystem (Binary: 91c789ff)
//!   POST /auth_public_key/write_etc_files - set Ed25519 auth key (Binary: 91c789ff)
//!   GET  /health                        - return "OK\n"
//!   GET  /healthcheck                   - diagnostic info
//!   GET  /container_name                - return current container name
//!
//! Changes in 91c789ff vs e409c31a:
//!   - POST /fs_sync split into POST /fs_free and POST /fs_thaw (Binary: 91c789ff)
//!     Evidence: strings "/fs_freeH3" and "/fs_thawH9" replacing "/fs_syncH9";
//!     "[CONTROL] / thawed" string added.
//!   - POST /auth_public_key renamed to POST /auth_public_key/write_etc_files,
//!     new body fields: process_id_reuse, allow_process_id, memory_limit_bytes
//!   - JWT authentication removed entirely (no jsonwebtoken crate)
//!   - /container_info.json persistence removed (no detect_container_name)
//!
//! String refs (Binary: 91c789ff):
//!   "[CONTROL] Control server listening on vsock port ..."
//!   "[CONTROL] Failed to bind control server to vsock port ..."
//!   "[CONTROL] Received mount_root request"
//!   "[CONTROL] mount_root succeeded: ..."
//!   "[CONTROL] mount_root failed: ..."
//!   "[CONTROL] /fs_free: flushing filesystem buffers..."
//!   "[CONTROL] /fs_free: done"
//!   "[CONTROL] Freezing / ..."
//!   "[CONTROL] / frozen"
//!   "[CONTROL] FIFREEZE failed (continuing): ..."
//!   "[CONTROL] Dropping page caches..."
//!   "[CONTROL] open(/) failed: ..."
//!   "[CONTROL] / thawed"
//!   "[CONTROL] FITHAW failed (continuing): ..."
//!   "[CONTROL] Auth public key set successfully"
//!   "[CONTROL] Invalid auth public key: ..."
//!   "[SECURITY] Rejecting vsock connection from non-host CID ..."

use std::convert::Infallible;
use std::net::SocketAddr;
use std::sync::Arc;

use http_body_util::Full;
use hyper::body::{Bytes, Incoming};
use hyper::server::conn::http1;
use hyper::service::service_fn;
use hyper::{Method, Request, Response, StatusCode};
use hyper_util::rt::TokioIo;
use parking_lot::Mutex;
use tokio::net::TcpListener;
use tokio::sync::broadcast;

use crate::cgroup::{self, CgroupController};
use crate::firecracker_init;
use crate::proc_handle::{CgroupConfig, ProcController, ProcessInfo};
use crate::state::{self, ProcessMap};

/// Shared container name type, updated by control server, read by WS connections.
pub type SharedContainerName = Arc<Mutex<Option<String>>>;

/// Shared state for the control server.
struct ControlState {
    shutdown_tx: broadcast::Sender<()>,
    container_name: SharedContainerName,
    proc_map: ProcessMap,
    controller: CgroupController,
    /// Whether the /mount_root endpoint is enabled (true when --firecracker-init is set).
    mount_root_enabled: bool,
}

/// Start the HTTP control server on a TCP address.
/// Updated signature: takes mount_root_enabled parameter.
pub async fn start_control_server(
    addr: SocketAddr,
    shutdown_tx: broadcast::Sender<()>,
    container_name: SharedContainerName,
    mut shutdown_rx: broadcast::Receiver<()>,
    proc_map: ProcessMap,
    controller: CgroupController,
    mount_root_enabled: bool,
) {
    let state = Arc::new(ControlState {
        shutdown_tx,
        container_name,
        proc_map,
        controller,
        mount_root_enabled,
    });

    let listener = match TcpListener::bind(addr).await {
        Ok(l) => {
            log::info!("[CONTROL] Control server listening on {addr}");
            l
        }
        Err(e) => {
            log::error!("[CONTROL] Failed to bind control server to {addr}: {e}");
            return;
        }
    };

    loop {
        tokio::select! {
            accept = listener.accept() => {
                match accept {
                    Ok((stream, remote_addr)) => {
                        if crate::is_local_ip(&remote_addr.ip()) {
                            log::warn!(
                                "[CONTROL] [SECURITY] Rejected connection from local IP {remote_addr}"
                            );
                            continue;
                        }
                        let state = Arc::clone(&state);
                        tokio::spawn(async move {
                            let io = TokioIo::new(stream);
                            let service = service_fn(move |req| {
                                let state = Arc::clone(&state);
                                async move { handle_request(req, state).await }
                            });
                            if let Err(e) = http1::Builder::new()
                                .serve_connection(io, service)
                                .await
                            {
                                log::debug!("[CONTROL] Error serving connection: {e}");
                            }
                        });
                    }
                    Err(e) => {
                        log::debug!("[CONTROL] Failed to accept connection: {e}");
                    }
                }
            }
            _ = shutdown_rx.recv() => {
                log::debug!("[CONTROL] Control server shutting down");
                log::debug!("[CONTROL] Control server shutdown complete");
                return;
            }
        }
    }
}

/// Start the control server on a vsock port (Firecracker).
/// Xrefs: "[CONTROL] Control server listening on vsock port ...",
///   "[CONTROL] Failed to bind control server to vsock port ...",
///   "[SECURITY] Rejecting vsock connection from non-host CID ..."
pub async fn start_vsock_control_server(
    port: u32,
    shutdown_tx: broadcast::Sender<()>,
    container_name: SharedContainerName,
    mut shutdown_rx: broadcast::Receiver<()>,
    proc_map: ProcessMap,
    controller: CgroupController,
    mount_root_enabled: bool,
) {
    let _state = Arc::new(ControlState {
        shutdown_tx,
        container_name,
        proc_map,
        controller,
        mount_root_enabled,
    });

    // In the real binary, this uses tokio-vsock to bind a VsockListener on
    // CID=VMADDR_CID_ANY (u32::MAX), port=`port`.
    // Connections are validated to ensure CID == 2 (host).
    //
    // Placeholder — requires tokio-vsock crate integration.
    log::info!("[CONTROL] Control server listening on vsock port {port}");
    log::warn!("vsock control server not yet fully implemented in RE");

    // Wait for shutdown
    let _ = shutdown_rx.recv().await;
    log::debug!("[CONTROL] Control server shutting down");
    log::debug!("[CONTROL] Control server shutdown complete");
}

/// Handle an individual HTTP request to the control server.
/// Binary: 91c789ff — /fs_sync replaced by /fs_free + /fs_thaw,
///   /auth_public_key expanded to /auth_public_key/write_etc_files,
///   JWT auth and /container_info.json persistence removed.
async fn handle_request(
    req: Request<Incoming>,
    state: Arc<ControlState>,
) -> Result<Response<Full<Bytes>>, Infallible> {
    let method = req.method().clone();
    let path = req.uri().path().to_string();

    match (method, path.as_str()) {
        (Method::POST, "/shutdown") => {
            log::info!("[CONTROL] Received shutdown request via HTTP");

            // Perform filesystem sync before shutdown
            log::debug!("[CONTROL] Syncing filesystem...");
            match tokio::process::Command::new("sync").output().await {
                Ok(output) => {
                    if output.status.success() {
                        log::info!("[CONTROL] Filesystem sync completed successfully");
                    } else {
                        log::warn!(
                            "[CONTROL] Filesystem sync failed with status: {}",
                            output.status
                        );
                    }
                }
                Err(e) => {
                    log::warn!("[CONTROL] Failed to execute sync command: {e}");
                }
            }

            match state.shutdown_tx.send(()) {
                Ok(_) => {
                    log::info!("[CONTROL] Shutdown signal sent successfully");
                    Ok(Response::builder()
                        .status(StatusCode::OK)
                        .body(Full::new(Bytes::from("Shutdown initiated\n")))
                        .unwrap())
                }
                Err(_) => {
                    log::error!(
                        "[CONTROL] Failed to send shutdown signal: Failed to initiate shutdown"
                    );
                    Ok(Response::builder()
                        .status(StatusCode::INTERNAL_SERVER_ERROR)
                        .body(Full::new(Bytes::from("Failed to initiate shutdown\n")))
                        .unwrap())
                }
            }
        }

        (Method::POST, "/container_name") => {
            let body = match read_body(req).await {
                Ok(b) => b,
                Err(resp) => return Ok(resp),
            };

            match std::str::from_utf8(&body) {
                Ok(name) => {
                    let name = name.trim().to_string();
                    log::info!("[CONTROL] Updated container name to: {name}");
                    *state.container_name.lock() = Some(name.clone());

                    // Binary: 91c789ff — /container_info.json persistence removed.

                    Ok(Response::builder()
                        .status(StatusCode::OK)
                        .body(Full::new(Bytes::from(format!(
                            "Container name set to: {name}\n"
                        ))))
                        .unwrap())
                }
                Err(e) => {
                    log::warn!("[CONTROL] Invalid UTF-8 in request body: {e}");
                    Ok(Response::builder()
                        .status(StatusCode::BAD_REQUEST)
                        .body(Full::new(Bytes::from("Invalid UTF-8 in body\n")))
                        .unwrap())
                }
            }
        }

        // New in e409c31a: POST /mount_root — apply mount root config (Firecracker snapstart)
        // Xrefs: "[CONTROL] Received mount_root request",
        //   "[CONTROL] mount_root succeeded: ...", "[CONTROL] mount_root failed: ..."
        (Method::POST, "/mount_root") => {
            if !state.mount_root_enabled {
                return Ok(Response::builder()
                    .status(StatusCode::NOT_FOUND)
                    .body(Full::new(Bytes::from("Not Found\n")))
                    .unwrap());
            }

            log::info!("[CONTROL] Received mount_root request");

            let body = match read_body(req).await {
                Ok(b) => b,
                Err(resp) => return Ok(resp),
            };

            match serde_json::from_slice::<firecracker_init::MountRootConfig>(&body) {
                Ok(config) => match firecracker_init::apply_mount_config(&config) {
                    Ok(status) => {
                        log::info!("[CONTROL] mount_root succeeded: {status}");
                        Ok(Response::builder()
                            .status(StatusCode::OK)
                            .body(Full::new(Bytes::from(format!(
                                "mount_root succeeded: {status}\n"
                            ))))
                            .unwrap())
                    }
                    Err(e) => {
                        log::error!("[CONTROL] mount_root failed: {e}");
                        Ok(Response::builder()
                            .status(StatusCode::INTERNAL_SERVER_ERROR)
                            .body(Full::new(Bytes::from(format!("mount_root failed: {e}\n"))))
                            .unwrap())
                    }
                },
                Err(e) => {
                    log::error!("[CONTROL] mount_root failed: {e}");
                    Ok(Response::builder()
                        .status(StatusCode::BAD_REQUEST)
                        .body(Full::new(Bytes::from(format!("mount_root failed: {e}\n"))))
                        .unwrap())
                }
            }
        }

        // Binary: 91c789ff — POST /fs_free replaces /fs_sync (freeze only).
        // Evidence: string "/fs_freeH3" in new binary replacing "/fs_syncH9".
        // Xrefs: "[CONTROL] /fs_free: flushing filesystem buffers...",
        //   "[CONTROL] /fs_free: done", "[CONTROL] Freezing / ...",
        //   "[CONTROL] / frozen", "[CONTROL] FIFREEZE failed (continuing): ...",
        //   "[CONTROL] Dropping page caches..."
        (Method::POST, "/fs_free") => {
            log::info!("[CONTROL] /fs_free: flushing filesystem buffers...");

            // Sync filesystem
            let _ = tokio::process::Command::new("sync").output().await;

            // Drop page caches
            log::debug!("[CONTROL] Dropping page caches...");
            let _ = tokio::fs::write("/proc/sys/vm/drop_caches", "3\n").await;

            // Freeze root filesystem
            log::debug!("[CONTROL] Freezing / ...");
            match firecracker_init::freeze_root() {
                Ok(()) => {
                    log::info!("[CONTROL] / frozen");
                }
                Err(e) => {
                    log::warn!("[CONTROL] FIFREEZE failed (continuing): {e}");
                }
            }

            log::info!("[CONTROL] /fs_free: done");
            Ok(Response::builder()
                .status(StatusCode::OK)
                .body(Full::new(Bytes::from("fs_free done\n")))
                .unwrap())
        }

        // Binary: 91c789ff — POST /fs_thaw: thaw a previously frozen filesystem.
        // Evidence: string "/fs_thawH9" in new binary; "[CONTROL] / thawed" log string.
        // Xrefs: "[CONTROL] / thawed", "[CONTROL] FITHAW failed (continuing): ..."
        (Method::POST, "/fs_thaw") => {
            match firecracker_init::thaw_root() {
                Ok(()) => {
                    log::info!("[CONTROL] / thawed");
                }
                Err(e) => {
                    log::warn!("[CONTROL] FITHAW failed (continuing): {e}");
                }
            }
            Ok(Response::builder()
                .status(StatusCode::OK)
                .body(Full::new(Bytes::from("fs_thaw done\n")))
                .unwrap())
        }

        // Binary: 91c789ff — POST /auth_public_key/write_etc_files replaces
        // POST /auth_public_key. New fields: process_id_reuse, allow_process_id,
        // memory_limit_bytes. JWT auth removed entirely.
        // Xrefs: "[CONTROL] Auth public key set successfully",
        //   "[CONTROL] Invalid auth public key: ..."
        (Method::POST, "/auth_public_key/write_etc_files") => {
            let body = match read_body(req).await {
                Ok(b) => b,
                Err(resp) => return Ok(resp),
            };

            // Deserialize the auth key + etc-files config.
            // Fields confirmed by string evidence: process_id_reuse, allow_process_id,
            // memory_limit_bytes in addition to the auth public key.
            #[derive(serde::Deserialize)]
            struct AuthPublicKeyRequest {
                /// Raw Ed25519 public key, base64-encoded (32 bytes).
                pub_key: Option<String>,
                /// Allow reuse of process IDs.
                #[serde(default)]
                process_id_reuse: Option<bool>,
                /// Specific process ID to allow.
                #[serde(default)]
                allow_process_id: Option<String>,
                /// Per-connection memory limit in bytes.
                #[serde(default)]
                memory_limit_bytes: Option<u64>,
            }

            match serde_json::from_slice::<AuthPublicKeyRequest>(&body) {
                Ok(req_body) => {
                    if let Some(ref key_b64) = req_body.pub_key {
                        // Validate Ed25519 key (32 bytes raw, base64-encoded)
                        match base64_decode_key(key_b64) {
                            Ok(key_bytes) if key_bytes.len() == 32 => {
                                log::info!("[CONTROL] Auth public key set successfully");
                                log::debug!(
                                    "[CONTROL] process_id_reuse={:?} allow_process_id={:?} memory_limit_bytes={:?}",
                                    req_body.process_id_reuse,
                                    req_body.allow_process_id,
                                    req_body.memory_limit_bytes
                                );
                                Ok(Response::builder()
                                    .status(StatusCode::OK)
                                    .body(Full::new(Bytes::from(
                                        "Auth public key set successfully\n",
                                    )))
                                    .unwrap())
                            }
                            Ok(key_bytes) => {
                                let msg = format!(
                                    "Auth public key must be exactly 32 bytes (raw Ed25519), got {}",
                                    key_bytes.len()
                                );
                                log::warn!("[CONTROL] Invalid auth public key: {msg}");
                                Ok(Response::builder()
                                    .status(StatusCode::BAD_REQUEST)
                                    .body(Full::new(Bytes::from(format!("{msg}\n"))))
                                    .unwrap())
                            }
                            Err(e) => {
                                log::warn!(
                                    "[CONTROL] Invalid auth public key: Invalid base64 for auth public key: {e}"
                                );
                                Ok(Response::builder()
                                    .status(StatusCode::BAD_REQUEST)
                                    .body(Full::new(Bytes::from(format!(
                                        "Invalid base64 for auth public key: {e}\n"
                                    ))))
                                    .unwrap())
                            }
                        }
                    } else {
                        Ok(Response::builder()
                            .status(StatusCode::BAD_REQUEST)
                            .body(Full::new(Bytes::from("Missing pub_key field\n")))
                            .unwrap())
                    }
                }
                Err(e) => {
                    log::warn!("[CONTROL] Invalid auth public key request: {e}");
                    Ok(Response::builder()
                        .status(StatusCode::BAD_REQUEST)
                        .body(Full::new(Bytes::from(format!("Invalid request: {e}\n"))))
                        .unwrap())
                }
            }
        }

        (Method::GET, "/health") => Ok(Response::builder()
            .status(StatusCode::OK)
            .body(Full::new(Bytes::from("OK\n")))
            .unwrap()),

        (Method::GET, "/healthcheck") => {
            let body = build_healthcheck_response(&state.proc_map, &state.controller).await;
            Ok(Response::builder()
                .status(StatusCode::OK)
                .body(Full::new(Bytes::from(body)))
                .unwrap())
        }

        (Method::GET, "/container_name") => {
            let name = state.container_name.lock().clone();
            let body = match name {
                Some(n) => format!("{n}\n"),
                None => "not set\n".to_string(),
            };
            Ok(Response::builder()
                .status(StatusCode::OK)
                .body(Full::new(Bytes::from(body)))
                .unwrap())
        }

        _ => Ok(Response::builder()
            .status(StatusCode::NOT_FOUND)
            .body(Full::new(Bytes::from("Not Found\n")))
            .unwrap()),
    }
}

/// Read the full body of an HTTP request.
async fn read_body(req: Request<Incoming>) -> Result<Bytes, Response<Full<Bytes>>> {
    match http_body_util::BodyExt::collect(req.into_body()).await {
        Ok(collected) => Ok(collected.to_bytes()),
        Err(e) => {
            log::warn!("[CONTROL] Failed to read request body: {e}");
            Err(Response::builder()
                .status(StatusCode::BAD_REQUEST)
                .body(Full::new(Bytes::from("Failed to read body\n")))
                .unwrap())
        }
    }
}

/// Decode a base64-encoded key (standard or URL-safe, with or without padding).
/// Binary: 91c789ff — used for Ed25519 public key validation in /auth_public_key/write_etc_files.
fn base64_decode_key(s: &str) -> Result<Vec<u8>, String> {
    use std::io::Read;
    // Try standard base64 first, then URL-safe
    let result = {
        let mut buf = Vec::new();
        let s_padded = if s.len() % 4 != 0 {
            let pad = 4 - (s.len() % 4);
            format!("{s}{}", "=".repeat(pad))
        } else {
            s.to_string()
        };
        // Use simple character substitution for URL-safe variant
        let standard = s_padded.replace('-', "+").replace('_', "/");
        match openssl_decode(&standard) {
            Ok(b) => Ok(b),
            Err(_) => openssl_decode(&s_padded),
        }
    };
    result
}

/// Minimal base64 decode using only std.
fn openssl_decode(s: &str) -> Result<Vec<u8>, String> {
    // Validate alphabet and decode
    let alphabet = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=";
    let clean: Vec<u8> = s
        .bytes()
        .filter(|b| *b != b'\n' && *b != b'\r' && *b != b' ')
        .collect();
    for &b in &clean {
        if !alphabet.contains(&b) {
            return Err(format!("Invalid base64 character: {}", b as char));
        }
    }
    // Decode
    let mut out = Vec::with_capacity(clean.len() * 3 / 4);
    let mut buf = [0u8; 4];
    let mut i = 0;
    while i + 3 < clean.len() {
        for j in 0..4 {
            buf[j] = clean[i + j];
        }
        let v: [u8; 3] = decode_block(buf);
        let pad = clean[i..i + 4].iter().filter(|&&b| b == b'=').count();
        out.extend_from_slice(&v[..3 - pad]);
        i += 4;
    }
    Ok(out)
}

fn decode_block(buf: [u8; 4]) -> [u8; 3] {
    let lookup = |b: u8| -> u8 {
        match b {
            b'A'..=b'Z' => b - b'A',
            b'a'..=b'z' => b - b'a' + 26,
            b'0'..=b'9' => b - b'0' + 52,
            b'+' => 62,
            b'/' => 63,
            _ => 0,
        }
    };
    let a = lookup(buf[0]);
    let b = lookup(buf[1]);
    let c = lookup(buf[2]);
    let d = lookup(buf[3]);
    [(a << 2) | (b >> 4), (b << 4) | (c >> 2), (c << 6) | d]
}

/// Build the diagnostic response for GET /healthcheck.
async fn build_healthcheck_response(
    proc_map: &ProcessMap,
    controller: &CgroupController,
) -> String {
    let process_controllers: Vec<ProcController> = {
        let map = proc_map.lock();
        map.iter()
            .map(|(process_id, entry)| {
                let cgroup_config =
                    entry
                        .proc_handle
                        .memory_cgroup_path
                        .as_ref()
                        .map(|cp| CgroupConfig {
                            process_id: process_id.clone(),
                            memory_limit_bytes: entry.proc_handle.memory_limit_bytes,
                            memory_usage_bytes: None,
                            memory_cgroup_path: Some(cp.display().to_string()),
                            process_group_pid: entry.proc_handle.process_group_pid,
                            internal_state: format!("{:?}", entry.internal_state),
                        });
                let process_info = ProcessInfo {
                    process_id: process_id.clone(),
                    pid: entry.pid,
                    reattachable: entry.reattachable,
                    timeout: entry.proc_handle.timeout.map(|d| d.as_secs()),
                    memory_limit_bytes: entry.proc_handle.memory_limit_bytes,
                    start_time: entry.proc_handle.start_time.elapsed().as_secs(),
                };
                ProcController {
                    cgroup: cgroup_config,
                    oom_killed_tx: None,
                    process_info,
                }
            })
            .collect()
    };

    let mut controllers_with_usage = process_controllers;
    for pc in &mut controllers_with_usage {
        if let Some(ref mut cg) = pc.cgroup {
            if let Some(ref cp) = cg.memory_cgroup_path {
                if let Ok(usage) =
                    cgroup::read_memory_usage(&std::path::PathBuf::from(cp), controller.version)
                        .await
                {
                    cg.memory_usage_bytes = Some(usage);
                }
            }
        }
    }

    let tracked = state::debug_process_map(proc_map);

    // Binary: 91c789ff — process limit (ps aux --no-headers, /proc/sys/kernel/pid_max)
    // removed from healthcheck response. Only tracked process state is returned.

    let _serialized: Vec<String> = controllers_with_usage
        .iter()
        .filter_map(|pc| serde_json::to_string(pc).ok())
        .collect();

    format!("{tracked}\nDiagnostic info: [OK\n")
}

/// Get the current container name from shared state.
pub fn get_container_name(state: &Mutex<Option<String>>) -> Option<String> {
    state.lock().clone()
}
