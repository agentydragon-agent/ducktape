# Gitea mirror + Docker exec integration

This document explains how to run a local Gitea instance, prepare pull mirrors,
and expose them to the Docker exec MCP server as a read-only volume. Clients can
then compose the `gitea_mirror` and `docker_exec` MCP servers to keep mirrors up
to date and clone them inside sandboxed containers.

## Overview

```
┌─────────────────┐      ensure_mirror_and_sync       ┌────────────────────┐
│ gitea_mirror MCP │ ───────────────────────────────▶ │ Gitea (pull mirrors)│
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
3. Agents first call `mcp_gitea_mirror_ensure_mirror_and_sync` with an HTTPS
repository URL. The tool creates a pull mirror (POST `/repos/migrate`) and
triggers a sync (POST `/repos/{owner}/{repo}/mirror-sync`).
4. Once the mirror is populated, agents call `mcp_docker_clone_from_mirror`
with `mirror_path` set to `owner/repo.git`. The container clones from the
read-only bind mount using `git clone --reference` for fast object reuse.

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

The server exposes a single tool `ensure_mirror_and_sync` which returns the
`mirror_path` ready for cloning.

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

1. Call `ensure_mirror_and_sync` with the upstream URL. The response includes a
   `mirror_path` such as `agentydragon/demo.git`.
2. Use the `exec` tool on the docker exec server to run a shell command that
   clones from the mount. For example:

```json
{
  "cmd": [
    "sh",
    "-lc",
    "mkdir -p /workspace/repos && git clone --reference /mnt/git-bare/agentydragon/demo.git file:///mnt/git-bare/agentydragon/demo.git /workspace/repos/demo"
  ]
}
```

3. Subsequent `exec` calls can operate inside the checkout (e.g. run tests or
   edit files under `/workspace/repos/demo`).

## Troubleshooting

- **Mirror not found**: ensure the mirror path returned by `ensure_mirror_and_sync`
  matches the host mount (owner/repo.git). Allow time for Gitea to complete the
  initial sync.
- **Permission errors on clone**: verify the `--volumes` entry uses `:ro`. For
  Colima, the host path must be under `$HOME`.
- **API failures**: `ensure_mirror_and_sync` surfaces HTTP status and response
  text. Confirm the token has `write:repository` scope and Gitea settings allow
  pull mirroring.
