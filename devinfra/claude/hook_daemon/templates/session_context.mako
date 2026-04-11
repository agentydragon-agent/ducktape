<%
    status = "ERRORS" if collector.has_errors else "OK with warnings" if collector.has_warnings else "OK"
%>\
# Claude Code session start hook — ${status}

% if proxy:
**Environment:** gVisor sandbox, TLS-inspecting proxy, no overlay fs (vfs), 9p fs
**Bazel:** wrapper adds auth proxy (${proxy.ca_status})
% else:
**Environment:** CLI (local)
% endif
% if container:

## Docker
${container.status}, `DOCKER_HOST=${container.socket_url}`
- `docker run` works. `docker build --network=host` works (BuildKit handles large output gracefully).
  Details: <devinfra/claude/docs/docker_evaluation_results.md>
  Use `--network=host` for builds; Alpine apk may need `--no-check-certificate` for TLS proxy.
- Storage: \
% if container.storage_driver == "overlay":
overlay on tmpfs (layer caching works for <~35 layers). Use `--layers=false` for larger Dockerfiles.
% else:
VFS on 9p (no layer caching, slower builds).
% endif
% endif
% if mkcert:

## Localhost TLS
`$MKCERT_CERT` / `$MKCERT_KEY` (auto-trusted). Use for HTTPS dev servers.
% endif
% if background_commands:

${"##"} Background tasks
% for cmd in background_commands:
- ${cmd.name}${ " (after env)" if cmd.after_env else "" }
% endfor
% endif
% if buildbuddy_configured:

${"##"} BuildBuddy
Bazel builds and tests by default execute remotely via BuildBuddy.
Use BuildBuddy API (key in `~/.config/bazel/buildbuddy.bazelrc`) to download undeclared test outputs, profiles, search invocations.
% endif

% if platform.nixpkgs_available:

## Nix
Nix is available with nixpkgs. When a tool you need isn't installed, use `nix-shell -p <pkg> --run <cmd>` (one-shot) or `nix shell nixpkgs#<pkg>` (Nix flakes) rather than installing permanently.
% elif platform.nix_installed:

## Nix
Nix is installed but nixpkgs channels are not configured. You can set up nixpkgs with `nix-channel --add https://nixos.org/channels/nixpkgs-unstable nixpkgs && nix-channel --update` to enable `nix-shell -p <pkg>`.
% endif
% if collector.has_warnings:

## Warnings
% for record in collector.buffer:
% if record.levelno >= logging.WARNING:
<%
    msg = record.getMessage()
    display_msg = msg[:200] + " [truncated — see log]" if len(msg) > 200 else msg
%>\
- ${record.levelname}: ${display_msg}
% endif
% endfor
% endif

Session start log: `${log_file}`
% if extra_context:
${extra_context}
% endif
