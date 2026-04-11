<%import os%>\
## Secrets
% if secrets and secrets.buildbuddy_api_key:
BuildBuddy API key loaded. `GITHUB_TOKEN` and `KUBECONFIG` come from personal config (home-manager).
% if secrets.github_token:
`gh` CLI and authenticated git operations available via personal PAT.
% endif
% else:
BuildBuddy API key not loaded — Bazel RBE unavailable. Check `devinfra/secrets/cli_env.sh`.
% endif
% if profile.bazel_remote_proxy and bazel_remote_proxy_sock:
Bazel remote proxy (UDS): `${bazel_remote_proxy_sock}` → `${profile.bazel_remote_proxy.target}`.
% endif
