# bridge — Haku's harness-opaque process bridge

The runner is deliberately thin. It launches the immutable harness selected by `--harness`, copies
native newline-delimited JSON between the harness stdio and the Console WebSocket, and retains an
ordered replay window. Claude is the only production harness in this change; Codex is a later
change.

| file            | role                                     |
| --------------- | ---------------------------------------- |
| `protocol.py`   | incompatible v3 envelope and negotiation |
| `transport.py`  | Console-side WebSocket transport         |
| `cli_client.py` | Claude's native protocol client          |
| `backend.py`    | process-launch seam                      |
| `options.py`    | Claude launch material and executable    |
| `runner.py`     | sandbox process bridge                   |

## v3 framing

Every bridge frame is discriminated by the outer `kind`. Native harness JSON is opaque:

- `hello` — runner → Console negotiation
- `start` — Console → runner launch material and resume cursor
- `harness_frame` — a complete inner harness frame in `frame`, either direction
- `end_input` — Console → runner stdin close
- `setup_output` — runner bootstrap/stderr bytes

The inner frame's `kind`, payload `type`, JSON-RPC method, and other native fields are never copied
into the outer kind or `session_frames.kind`. For Claude, the wire shape is
`{"kind":"harness_frame","seq":...,"frame":{"kind":"claude","payload":{...}}}`.
The database stores the complete inner frame in `session_frames.payload` for inspection/export.

Protocol v3 is intentionally incompatible. A runner that only advertises v2 has no common version,
so the Console refuses it and the runner exits/cleans up rather than guessing a framing contract.

## Position-based replay

The runner assigns dense outer `seq` values to every frame it puts on the wire, including native deltas
and notifications. `start.resume_from` is the highest sequence recorded for the session. The runner
retains and replays every frame above that cursor; no backend-specific `replayable()` classifier is
involved. The Console deduplicates by `(session_id, runner_seq)` and stores the original inner frame,
direction, and timestamps.

`--harness claude` is required by the deployed Claude SandboxTemplate. The selected harness is
resolved once at runner startup and cannot change for the lifetime of the process. The bridge token
is removed from the child harness environment.
