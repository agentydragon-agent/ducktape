- Anki mini-format-pack: disabled - seems I deleted my fork (`addon_id: 295889520`, `https://github.com/agentydragon/mini-format-pack`)
- Chrome remote desktop
- disable screensaver and desktop effects on VMs
- GitLab runner
- Buildifier

## Legacy Claude MCP Servers

MCP servers previously managed by the `legacy_claude_mcp` Ansible role (removed 2026-03).

| Server    | Command | Package                                                          |
| --------- | ------- | ---------------------------------------------------------------- |
| memory    | `npx`   | `@modelcontextprotocol/server-memory`                            |
| firecrawl | `npx`   | `firecrawl-mcp` (env: `FIRECRAWL_API_URL=http://localhost:3002`) |
| arxiv     | `uvx`   | `git+https://github.com/blazickjp/arxiv-mcp-server.git`          |
| probe     | `npx`   | `@buger/probe-mcp`                                               |

## Legacy Google Drive Client

Ansible role `google_drive_client` (removed 2026-03) set up Google Drive File Stream
as a systemd user service:

- Ran `/opt/google/drive-file-stream/drive ~/.google-drive` via a user systemd service
- Symlinked `~/drive` → `~/.google-drive/My Drive`
- Symlinked `~/.config/worthy/config.yaml` → `~/drive/finance/worthy-config.yaml`
- Required manual first-run authentication via the command line
