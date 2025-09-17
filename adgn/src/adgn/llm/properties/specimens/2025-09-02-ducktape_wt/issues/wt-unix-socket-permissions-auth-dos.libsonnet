local I = import '../../specimens/lib.libsonnet';

I.issueOneOccurrence(
  rationale= |||
    Unix domain socket path/permissions are not enforced, enabling local DoS and unauthenticated access.

    Observed:
    - Client connects using `asyncio.open_unix_connection(self.config.daemon_socket_file)` (wt/wt/client/wt_client.py),
      but there is no corresponding code in this specimen that guarantees the server creates/binds the socket in a
      private directory (0700) or sets restrictive socket file perms (0600). No unlink-before-bind logic was found either.
    - Startup/Config surfaces `socket_path` in messages, but there is no visible chmod/umask or auth check on accept.

    Risks:
    - Pre-creation/TOCTOU DoS: another local user can create the socket path ahead of the daemon to block startup or
      force the daemon to write in an attacker-controlled directory.
    - Unauthenticated local connections: without permission gating (directory 0700 + socket 0600) or peer credential
      checks, any local user may connect to the daemon and issue requests.

    Acceptance criteria (agnostic to exact layout, but enforce strong invariants):
    - Socket directory must be user-private (0700), e.g. under $XDG_RUNTIME_DIR/$USER/wt/ or ~/.cache/wt/run.
    - On daemon start: create the parent dir with 0700 (exist_ok but ensure mode), unlink any stale socket, bind,
      and set socket file mode to 0600 (either via umask(0o177) around bind or explicit chmod after bind).
    - On accept: optionally verify peer credentials (SO_PEERCRED / getpeereid) and reject non-owner users.
    - Client: ensure `daemon_socket_file` resolves inside the expected private dir; do not allow arbitrary paths; fail if
      path or its parent dir is not owned by the current user or has group/world write perms.

    Notes:
    - If a separate daemon module exists outside this specimen, implement the permission and auth checks there; the
      client contract should still assert a user-private socket path.
  |||,
  filesToRanges={
    'wt/wt/client/wt_client.py': [[300, 336]],
    'wt/wt/shared/protocol.py': [[320, 336]],
  },
)
