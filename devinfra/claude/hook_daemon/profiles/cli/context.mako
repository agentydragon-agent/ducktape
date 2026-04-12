<%import os%>\
## Secrets
% if secrets and secrets.buildbuddy_api_key:
`BUILDBUDDY_API_KEY` loaded (from `devinfra/secrets/cli_env.sh`).
% else:
`BUILDBUDDY_API_KEY` not loaded — Bazel RBE unavailable. Check `devinfra/secrets/cli_env.sh`.
% endif
% if secrets and secrets.github_token:
`GITHUB_TOKEN` available (personal PAT from home-manager). `gh` CLI and authenticated git operations work.
% endif
`KUBECONFIG` comes from personal config (home-manager `~/.kube/config`), not from the hook daemon. It may or may not be present depending on the user's setup.
