@README.md

## Agent Instructions

- **No external dependencies**: This package runs before package installation. Only stdlib.
- **Session start log**: `~/.cache/claude-code-web/session-start.log`
- **Proxy log**: `~/.cache/bazel-proxy/proxy.log` (when daemonized)
- **gVisor environment**: Claude Code web runs on gVisor, not real Linux. Some syscalls behave differently.
- **Design rationale**: See <proxy-alternatives.md> for why we use a local proxy instead of native Bazel/Java auth.
