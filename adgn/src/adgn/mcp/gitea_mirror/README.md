# Gitea mirror + Docker exec integration

This document explains how to run a local Gitea instance, prepare pull mirrors,
and expose them to the Docker exec MCP server as a read-only volume. Clients can
then compose the `gitea_mirror` and `docker_exec` MCP servers to keep mirrors up
to date and clone them inside sandboxed containers.

## Overview

```
┌─────────────────┐  1. trigger_mirror_sync          ┌────────────────────┐
│ gitea_mirror MCP │ ───────────────────────────────▶ │ Gitea (pull mirrors)│
│                 │  2. get_mirror_status (poll)     │                    │
│                 │ ◀───────────────────────────────  │                    │
└─────────────────┘                                   └────────────────────┘
          ▲                                                     │
          │ mirror_path                                         │ host bind mount
          │                                                     ▼
┌─────────────────┐  git clone via exec tool        ┌────────────────────┐
│ docker_exec MCP  │ ─────────────────────────────▶ │ /mnt/git-bare/<repo>│
└─────────────────┘                                 └────────────────────┘
```

1. `gitea_mirror` MCP is run on the host with access to the Gitea API.
2. `docker_exec` MCP runs sandboxed containers with a read-only bind mount of
the mirror store (e.g. `/Users/<user>/.combo_mcp/gitea/git/repositories`).
3. Agents call `trigger_mirror_sync` with an HTTPS repository URL. The tool creates
a pull mirror (POST `/repos/migrate`), triggers an async sync (POST
`/repos/{owner}/{repo}/mirror-sync`), and returns immediately with the current
`mirror_updated` timestamp.
4. Agents poll `get_mirror_status` until the `mirror_updated` timestamp changes,
indicating the sync is complete.
5. Once synced, agents call `mcp_docker_clone_from_mirror` with `mirror_path` set
to `owner/repo.git`. The container clones from the read-only bind mount using
`git clone --reference` for fast object reuse.

## Running Gitea locally

A minimal docker-compose file is available at
`src/adgn_llm/mcp/gitea/docker-compose.yml`:

```bash
docker compose -f src/adgn_llm/mcp/gitea/docker-compose.yml up -d
open http://localhost:3000
```

Complete the initial setup, create an admin token, and record:

- Base URL, e.g. `http://localhost:3000`
- Access token with `write:repository` scope (required for migrate + sync API)
- Mirror storage path inside the volume (`/data/git/repositories` inside the
  container, bind-mounted on the host).

To discover the host path of the mirror store when using Docker Desktop or
Colima:

```bash
docker inspect adgn-gitea --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}'
```

Mount this path read-only into the Docker exec MCP containers.

## Launching the MCP servers

### Gitea mirror MCP

```bash
export GITEA_BASE_URL="http://localhost:3000"
export GITEA_TOKEN="<token>"
adgn-mcp-gitea-mirror
```

The server exposes two tools:
- `trigger_mirror_sync`: Ensures mirror exists, triggers async sync, returns immediately
- `get_mirror_status`: Returns current mirror status including `mirror_updated` timestamp

### Docker exec MCP

```bash
MIRROR_ROOT="$(docker inspect adgn-gitea \
  --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}')/git/repositories"

adgn-mcp-docker-exec \
  --image ghcr.io/agentydragon/public-git-runner:latest \
  --working-dir /workspace \
  --network-mode none \
  --volumes "$MIRROR_ROOT:/mnt/git-bare:ro"
```

Flags of note:

- `--image` must include `git` and other tools needed inside the container.
- `--network-mode none` keeps containers offline; change if API access is
  required.
- `--volumes` accepts comma-separated bind specs (`host:container[:mode]`). Use
  `:ro` to keep the mirror read-only inside the container.

## Client workflow

1. **Trigger the sync**: Call `trigger_mirror_sync` with the upstream URL:
   ```json
   {
     "url": "https://github.com/username/repo"
   }
   ```

   The response includes:
   ```json
   {
     "owner": "agentydragon",
     "repo": "github-com-username-repo",
     "mirror_path": "agentydragon/github-com-username-repo.git",
     "mirror_updated": "2024-01-15T10:30:00Z",
     "sync_triggered": true
   }
   ```

   Save the `mirror_updated` timestamp and `mirror_path`.

2. **Poll for completion**: Repeatedly call `get_mirror_status` until `mirror_updated` changes:
   ```json
   {
     "owner": "agentydragon",
     "repo": "github-com-username-repo"
   }
   ```

   When `mirror_updated` differs from the initial timestamp, the sync is complete.

3. **Clone from mirror**: Use the `exec` tool on the docker exec server to clone:
   ```json
   {
     "cmd": [
       "sh",
       "-lc",
       "mkdir -p /workspace/repos && git clone --reference /mnt/git-bare/agentydragon/github-com-username-repo.git file:///mnt/git-bare/agentydragon/github-com-username-repo.git /workspace/repos/repo"
     ]
   }
   ```

4. **Work with the repo**: Subsequent `exec` calls can operate inside the checkout
   (e.g. run tests or edit files under `/workspace/repos/repo`).
