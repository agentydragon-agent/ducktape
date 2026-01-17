@README.md

## Agent Instructions

- **No external dependencies**: This package runs before package installation. Only stdlib.
- **Session start log**: `~/.cache/claude-code-web/session-start.log`
- **Supervisor logs**: `~/.config/supervisor/supervisord.log` (supervisor daemon), `~/.config/supervisor/bazel-proxy.{log,err.log}` (proxy service)
- **gVisor environment**: Claude Code web runs on gVisor, not real Linux. Some syscalls behave differently.
- **Design rationale**: See <proxy-alternatives.md> for why we use a local proxy instead of native Bazel/Java auth.

## Debugging Commands

When the user encounters proxy or Bazel issues:

```bash
# Check supervisor status
supervisorctl -c ~/.config/supervisor/supervisord.conf status

# View proxy logs
tail -50 ~/.config/supervisor/bazel-proxy.log
tail -50 ~/.config/supervisor/bazel-proxy.err.log

# Restart proxy (e.g., if credentials expired)
supervisorctl -c ~/.config/supervisor/supervisord.conf restart bazel-proxy

# Check session start log
tail -100 ~/.cache/claude-code-web/session-start.log

# Verify proxy connectivity
curl -s --max-time 5 -x http://127.0.0.1:18081 https://bcr.bazel.build/ | head -1

# Check Bazel configuration
cat ~/.cache/bazel-proxy/bazelrc
```
