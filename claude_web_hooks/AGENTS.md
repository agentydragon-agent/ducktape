@README.md

## Agent Instructions

- **No external dependencies**: This package runs before package installation. Only stdlib.
- **Logs to `/tmp/session-start-direnv.log`**: Check here for hook debugging.
- **gVisor environment**: Claude Code web runs on gVisor, not real Linux. Some syscalls behave differently.
