# Ducktape

My personal infrastructure's duct tape. Projects that didn't yet warrant making
into separate repositories.

Based on my [Python project skeleton](https://gitlab.com/agentydragon/python-skeleton).

Please install and use [pre-commit](https://github.com/pre-commit/pre-commit).

## License
AGPL 3.0

## Updates

To update Python requirements lock:

```bash
bazel run //:requirements.update
```

## Spawning agents
```
# inside the canonical repo
cd ~/code/ducktape

# create Claude sandbox, branch agent/claude-ws1 off main
git worktree add -b agent/claude-ws1 ~/claude-code/ws1 main
```
