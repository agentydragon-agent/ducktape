# public_git MCP server (Gitea + per-session container exec)

This FastMCP server exposes two tools over a single, per-session Docker container:

- `obtain_code(url, ref?, branch?)` — ensures a Gitea pull-mirror exists and is synced, then clones into the session container under `/workspace/<host>/<path>` using `--reference` to a read-only mirror
- `exec(cmd, cwd?, env?, user?, tty?, shell?, timeout_secs?)` — executes commands inside the same per-session container (the working copy persists across calls within the session)

Highlights
- Mirrors are Gitea-managed only: expected layout `<store>/<owner>/<repo>.git`
- Session container: no network, RO bind of the mirror store, RW `/workspace`
- Server description: built from Docker image history (CreatedBy lines) — no in-container reads; works with any image

## 1) Start Gitea (docker-compose)

Gitea runs as a sidecar and hosts the pull mirrors. We keep mirrors under `$HOME/.combo_mcp/gitea/git/repositories` to be Colima-friendly.

```bash
# Launch Gitea
docker compose -f /Users/mpokorny/code/ducktape/llm/adgn_llm/src/adgn_llm/mcp/gitea/docker-compose.yml up -d

# Open the UI and complete initial setup
open http://localhost:3000
```

Initial setup steps:
- Create admin user
- Create a personal access token (Settings → Applications)
- Create a pull mirror (Repositories → New Migration → URL http/https; check “This repository will be a mirror”)

Gitea mirrors live at:
```
$HOME/.combo_mcp/gitea/git/repositories/<owner>/<repo>.git
```

## 2) Launch the MCP server (in-process)

This server is designed to be embedded and run in-process via FastMCP. Example:

```python
from pathlib import Path
from adgn_llm.mcp.public_git.server import make_public_git_mcp

# Configure store path (Gitea repositories dir) and container image
store = Path.home() / ".combo_mcp/gitea/git/repositories"
image = "debian:bookworm-slim"  # or your own prebuilt image with git, jq, rg, fd, python3, etc.

server = make_public_git_mcp(
    store_host=store,
    image=image,
    # Optional Gitea RPC for "Synchronize Now"
    gitea_base_url="http://localhost:3000",
    gitea_token="<YOUR_TOKEN>",
)

# Use your FastMCP client/session machinery to run the server in-proc
# Example (pseudocode):
# async with open_inproc_session(server) as sess:
#     await sess.initialize()
#     await sess.call_tool("obtain_code", {"url": "https://github.com/org/repo.git"})
#     await sess.call_tool("exec", {"cmd": ["git", "status"], "cwd": "/workspace/github.com/org/repo"})
```

If you already use a manager for in-proc MCP servers, wire `server` into it and call the tools as usual. The per-session container is created on session initialize and stopped on session close; both tools target the same container and `/workspace`.

## 3) Tool contracts

- `obtain_code`
  - Input: `{ url: string, ref?: string, branch?: string, submodules?: boolean=false }`
  - Behavior:
    - Always attempts a best-effort Gitea mirror sync: `POST /api/v1/repos/{owner}/{repo}/mirror-sync` (if base URL and token are set)
    - Verifies `<store>/<owner>/<repo>.git` exists; if missing, instructs to create a Gitea pull mirror
    - Clones inside the container using the mirror as both file:// source and `--reference`
    - Optionally checks out `ref` (detached) or `branch`
  - Output: `{ path, head_sha, storage_key, pretty_path, sync_attempted, sync_ok, sync_error }`

- `exec`
  - Input: `{ cmd: string[], cwd?: string, env?: map<string,string>, user?: string, tty?: boolean, shell?: boolean, timeout_secs?: number }`
  - Output: `{ exit_code, timed_out, stdout, stderr }`

Notes:
- The session container has no network; only RO mounts and RW `/workspace`
- Paths follow `/workspace/<host>/<owner>/<repo>` (e.g., `/workspace/github.com/org/repo`)

## 4) Images and description

On session start, the server produces a description using Docker image history:
- Includes image id/tags, RO mount mapping, workspace path
- Lists up to 100 `CreatedBy` steps with `/bin/sh -c` and `#(nop)` stripped for readability
- Does not duplicate tool lists — discover tools via MCP schemas

You can use any image, but for a smooth experience pick one with:
- `git`, `jq`, `ripgrep` (`rg`), `fd`, `python3`, `pip`, `bash` preinstalled (see `src/adgn_llm/mcp/public_git/Dockerfile` for a reference)

## 5) Troubleshooting

- Colima binds: host paths must be under `$HOME` to mount into containers
- Mirror missing: if `obtain_code` reports no mirror, create a Gitea pull mirror for that URL
- Sync errors: `sync_attempted=false` when no Gitea base URL/token; `sync_ok=false` with `sync_error` details if RPC failed — clone proceeds with the last mirrored content
- RO mount: writing under `/mnt/git-bare` will fail (expected)
- No network: commands like `curl https://example.com` will fail inside the container (expected)

## 6) Related servers (optional composition)

- Generic container exec (shared core): `src/adgn_llm/mcp/docker_exec/server.py` provides a reusable FastMCP with only the `exec` tool. It shares the same per-session container logic and description pattern and can be combined with a separate git-mirror server if you prefer composing behavior in the client.
