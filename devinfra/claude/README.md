# Claude Code Integration

Session hooks, statusline, and Claude Code API models for Claude Code web environments.

## References

- [Claude Code Hooks API](https://docs.anthropic.com/en/docs/claude-code/hooks)
- [Settings JSON Schema](https://json.schemastore.org/claude-code-settings.json)

## Glossary

| Concept                   | Canonical term        | Rationale                                         |
| ------------------------- | --------------------- | ------------------------------------------------- |
| Anthropic's Envoy gateway | **egress proxy**      | Matches Anthropic's own docs ("egress controls"). |
| Mock TLS MITM for tests   | **mock egress proxy** | Says what it simulates.                           |

## Anthropic's TLS-Inspecting Proxy

Claude Code on the web runs in sandboxed containers with network egress controlled through a TLS-inspecting proxy. Key characteristics:

### Environment Setup (by Anthropic)

Anthropic configures the container environment with:

```bash
HTTPS_PROXY=http://<container_id>:<jwt_token>@<proxy_host>:<port>
HTTP_PROXY=...  # same
```

- **JWT authentication**: Credentials are embedded in the proxy URL as username:password
- **Token refresh**: Anthropic may refresh JWT tokens during long sessions
- **TLS inspection**: Proxy terminates TLS to inspect traffic, re-encrypts with Anthropic CA

### Our Design Principle

**We do NOT overwrite `HTTPS_PROXY` / `HTTP_PROXY` environment variables.**

Most tools (curl, pip, npm, git, etc.) work correctly with Anthropic's proxy. Only Bazel needs special handling due to Java's proxy authentication limitations.

By preserving the original proxy env vars:

- Tools continue to use Anthropic's proxy directly
- JWT token refreshes are automatically picked up
- The bazel wrapper reads fresh credentials on each invocation

## Components

- **Session Start Hook**: Sets up the development environment for Claude Code web sessions

## Session Start Hook

The hook runs at the start of each Claude Code web session and:

### Proxy/TLS Setup (via `auth_proxy/setup.py`)

1. Starts supervisord for process management (needed for container runtime)
2. Loads the TLS inspection CA from the pre-installed filesystem path (`/usr/local/share/ca-certificates/swp-ca-production.crt`)
3. Creates a Java truststore with the CA using keytool
4. Creates combined CA bundle (system CAs + proxy CA)
5. Writes bazelrc to `<session_dir>/bazelrc`

### Bazel Setup (via `bazelisk_setup.py`)

7. Downloads and installs Bazelisk
8. Creates wrapper script at `<session_dir>/bin/bazel`

### Git Hooks

9. Installs git pre-commit hooks via pre-commit framework

### Development Tools

10. Installs nix via `nix_setup.py` (for nix eval, flake operations)

Note: flux, kustomize, kubeseal, helm are now Bazel-managed via `@multitool//tools/*`.
Nix formatting uses a static nixfmt binary downloaded by `devinfra/precommit/run_nixfmt.sh`.

### Environment Configuration

12. Configures podman for gVisor compatibility
13. Sets up environment variables in `CLAUDE_ENV_FILE`

See `.claude/settings.json` for hook configuration.

# Bazel Proxy Authentication

How Bazel accesses the Bazel Central Registry (BCR) through Anthropic's TLS-inspecting egress proxy.

## Background

[Claude Code on the web](https://docs.anthropic.com/en/docs/claude-code/claude-code-on-the-web) runs in ephemeral containers with a TLS-inspecting proxy for network egress. Getting Bazel to authenticate with this proxy required working around Java/JVM limitations:

1. **TLS Inspection**: The proxy does TLS inspection with a custom Anthropic CA certificate
2. **JWT Authentication**: Proxy credentials include a JWT token for authentication (see [network docs](https://docs.anthropic.com/en/docs/claude-code/security#network-access))
3. **Java doesn't read `HTTPS_PROXY` env vars natively**: Bazel's bzlmod/repository rules use `ProxyHelper`, which only reads `HTTPS_PROXY` from Bazel's `getRepoEnv()` map — not the process environment. Requires `--repo_env=HTTPS_PROXY` to be set.
4. **Basic auth disabled by default**: Since [Java 8u111](https://confluence.atlassian.com/kb/basic-authentication-fails-for-outgoing-proxy-in-java-8u111-909643110.html), Basic authentication for HTTPS tunneling is disabled via `jdk.http.auth.tunneling.disabledSchemes=Basic`

## The Solution

Bazel authenticates **directly** with Anthropic's egress proxy using Java's native `Authenticator` mechanism. The session bazelrc configures three things:

1. **Re-enable Basic auth**: `startup --host_jvm_args=-Djdk.http.auth.tunneling.disabledSchemes=` and `-Djdk.http.auth.proxying.disabledSchemes=`
2. **Expose credentials to ProxyHelper**: `common --repo_env=HTTPS_PROXY` (inherits current env value at bazel invocation time)
3. **Trust the inspection CA**: `startup --host_jvm_args=-Djavax.net.ssl.trustStore=<custom-truststore>`

With these flags, Bazel's `ProxyHelper` parses the `HTTPS_PROXY` URL (including JWT credentials), installs a `java.net.Authenticator`, and authenticates the CONNECT tunnel on 407 challenge/response. No local proxy daemon needed.

See <docs/proxy-alternatives.md> for earlier analysis and why native JVM settings were initially considered unworkable (the egress proxy now returns RFC-compliant 407 responses, and `--repo_env` solves the env-var problem).

## References

See <proxy-alternatives.md> for analysis of why alternatives don't work.

- [Claude Code on the Web](https://www.anthropic.com/news/claude-code-on-the-web) - Product announcement
- [Claude Code Sandboxing](https://www.anthropic.com/engineering/claude-code-sandboxing) - Network isolation architecture
- [Enterprise Network Configuration](https://docs.anthropic.com/en/docs/claude-code/corporate-proxy) - Proxy and CA configuration
- [Network Security](https://docs.anthropic.com/en/docs/claude-code/security#network-access) - Egress controls

## Configuration

All settings use [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) with the `DUCKTAPE_CLAUDE_HOOKS_` prefix:

| Environment Variable                      | Default                    | Description                                       |
| ----------------------------------------- | -------------------------- | ------------------------------------------------- |
| `DUCKTAPE_CLAUDE_HOOKS_SUPERVISOR_DIR`    | `<session_dir>/supervisor` | Supervisor config directory                       |
| `DUCKTAPE_CLAUDE_HOOKS_SUPERVISOR_PORT`   | `19001`                    | Supervisor TCP port                               |
| `DUCKTAPE_CLAUDE_HOOKS_AUTH_PROXY_DIR`    | `<session_dir>/auth-proxy` | TLS CA cache directory                            |
| `DUCKTAPE_CLAUDE_HOOKS_INSTALL_BAZELISK`  | `true`                     | Install bazelisk                                  |
| `DUCKTAPE_CLAUDE_HOOKS_INSTALL_NIX`       | `false`                    | Install nix package manager                       |
| `DUCKTAPE_CLAUDE_HOOKS_CONTAINER_RUNTIME` | `docker`                   | Container runtime (`podman`, `docker`, or `none`) |

`<session_dir>` = `~/.claude/session-env/<session_id>/` — a per-session directory managed by Claude Code.

See `settings.py` for the full configuration schema.

## Dependencies

See BUILD.bazel for the full dependency list. Key runtime requirements:

- **keytool** (from JDK) for Java truststore creation

## Usage

Bazel proxy authentication is fully automatic — no daemon to manage. The session start hook writes the bazelrc; the bazel wrapper picks it up on each invocation.

## How It Works

### Architecture

```
All tools (curl, pip, npm, Bazel, etc.)
    │
    └──► HTTPS_PROXY (Anthropic's egress proxy, fresh JWT) ──► Internet
         (unchanged — we never overwrite HTTPS_PROXY)

Bazel specifically:
    └──► bazel wrapper
           └── Execs bazelisk with --bazelrc=<session-bazelrc>
                   │
                   └──► Bazel JVM
                          │  startup: -Djdk.http.auth.tunneling.disabledSchemes=
                          │  startup: -Djdk.http.auth.proxying.disabledSchemes=
                          │  startup: -Djavax.net.ssl.trustStore=<custom>
                          │  common:  --repo_env=HTTPS_PROXY (inherits JWT from env)
                          │
                          └──► ProxyHelper parses HTTPS_PROXY → installs Authenticator
                                 └──► CONNECT bcr.bazel.build:443 → 407 → auth → 200
                                        └──► BCR / Internet
```

### Flow

1. **Session hook** extracts the Anthropic CA, creates a Java truststore, creates a combined CA bundle, and writes a per-session bazelrc with the JVM flags above.
2. **Bazel wrapper** (invoked as `bazel`) just execs bazelisk with `--bazelrc=<session-bazelrc>`. No proxy manipulation.
3. **Bazel JVM** (at build time): `--repo_env=HTTPS_PROXY` passes the current egress proxy URL (with fresh JWT) to `ProxyHelper`, which installs a `java.net.Authenticator`. When the proxy returns 407, the Authenticator provides credentials and the CONNECT succeeds.

### Why This Works Now

The egress proxy now returns RFC-compliant `HTTP/1.1 407 Proxy Authentication Required` with `Proxy-Authenticate: Basic` (verified 2026-03-16). Combined with the three JVM flags, Java's native proxy auth handles the 407 challenge correctly.

See <docs/proxy-alternatives.md> for historical analysis and earlier investigation.

## Verification

After session start:

```bash
# Verify Bazel can reach BCR
bazel info

# Verify egress proxy is reachable (direct — no local proxy shim)
curl -s --max-time 5 -x "$HTTPS_PROXY" https://bcr.bazel.build/ | head -1

# Check session bazelrc (should contain jdk.http.auth.tunneling.disabledSchemes)
cat "$DUCKTAPE_CLAUDE_HOOKS_SESSION_DIR/bazelrc"
```

## Files

All session-scoped files live under `<session_dir>` = `~/.claude/session-env/<session_id>/`.

Supervisor files (in `<session_dir>/supervisor/`):

- `supervisord.conf` - Supervisor main configuration
- `supervisord.{log,pid}` - Supervisor daemon state

Note: Supervisor listens on TCP `127.0.0.1:19001` (no Unix socket file). Supervisor runs only to manage container runtime (podman/docker), not an auth proxy daemon.

TLS CA files (in `<session_dir>/auth-proxy/`, created by `auth_proxy/setup.py`):

- `anthropic_ca.pem` - Loaded TLS inspection CA
- `combined_ca.pem` - System CAs + Anthropic CA bundle (used by SSL_CERT_FILE)
- `cacerts.jks` - Java truststore with CA (used by Bazel JVM via --host_jvm_args)

Global (non-session-scoped) files in `~/.cache/claude-hooks/`:

- `bazelisk` - Bazelisk binary
- `mkcert` - mkcert binary

## Known Limitations

### rules_python lock() doesn't inherit --action_env

The `lock()` rule from `@rules_python//python/uv:lock.bzl` has a bug/limitation: it doesn't inherit `--action_env` values because it sets an explicit `env` attribute on `ctx.actions.run_shell()`.

**Impact**: The `uv pip compile` sandbox action doesn't receive proxy environment variables set via `--action_env=HTTPS_PROXY=...`.

**Workaround**: Pass proxy env vars directly to the `lock()` rule's `env` attribute:

```starlark
lock(
    name = "requirements",
    srcs = [...],
    out = "requirements_bazel.txt",
    env = {
        "HTTPS_PROXY": "http://container:jwt_token@proxy_host:port",
        "SSL_CERT_FILE": "/path/to/combined_ca.pem",  # For TLS inspection
    },
)
```

**Root cause**: In `python/uv/private/lock.bzl`:

```starlark
ctx.actions.run_shell(
    ...
    env = ctx.attr.env,  # <-- Explicit env overrides --action_env inheritance
)
```

This should arguably use `dicts.add(ctx.configuration.default_shell_env, ctx.attr.env)` to merge `--action_env` with rule-specific env.

### 9p filesystem doesn't support Unix socket hard links

**Affects**: Claude Code web gVisor sandbox (root `/` is 9p)

**Root cause**: Supervisord uses hard links for atomic Unix socket creation (`link()` syscall). The 9p filesystem doesn't support hard linking Unix domain sockets, returning `EOPNOTSUPP` (errno 95). When the hard link fails, supervisord misinterprets this as a stale socket and enters an infinite retry loop.

**Solution**: Use TCP socket (`inet_http_server`) instead of Unix socket. The supervisor_setup module now configures supervisor to listen on `127.0.0.1:19001` by default. This avoids the 9p filesystem limitation entirely.

Configuration via environment variable:

- `DUCKTAPE_CLAUDE_HOOKS_SUPERVISOR_PORT`: Override TCP port (default: 19001)

## Test Environments

### How Tests Work in Each Environment

**GitHub Actions CI** (no egress proxy):

- `HTTPS_PROXY` is not set
- `MockEgressProxy` connects directly to the internet
- DNS resolution works directly

**Claude Code Web** (gVisor sandbox with egress proxy):

- `HTTPS_PROXY` is set to `http://CONTAINER:JWT@host:port` by Anthropic
- The bazel wrapper does NOT rewrite `HTTPS_PROXY` — Bazel reads it via `--repo_env=HTTPS_PROXY`
- `env_inherit` in BUILD.bazel passes the original `HTTPS_PROXY` to test processes
- `MockEgressProxy` chains through the egress proxy directly
- DNS does NOT work directly (all traffic must go through egress proxy)

**Developer laptop** (no proxy):

- Same as CI — `MockEgressProxy` connects directly

### Proxy Chain in Tests (Claude Code Web)

```
test client (e.g. bazel, podman)
    │
    └──► mock egress proxy (random port, TLS MITM)
           │ simulates Anthropic's TLS inspection
           │ chains through HTTPS_PROXY if set
           └──► egress proxy (21.x.x.x:15004)
                  │ TLS inspection, JWT validation
                  └──► internet
```

## Encrypted Secrets

Secrets are stored as per-component age-encrypted JSON files in `.claude_hooks/secrets/` at the repo root — NOT inside the wheel. Each `.age` file decrypts to a JSON dict mapping env var names to values (e.g. `{"OLLAMA_API_KEY": "..."}"`).

When `DUCKTAPE_CLAUDE_HOOKS_SECRETS_AGE_KEY` is set (in Claude Code web environment), the session start hook decrypts all `.age` files and exports the merged env vars to `CLAUDE_ENV_FILE`.

Uses asymmetric X25519 encryption via [age](https://age-encryption.org/):

- **Public key**: `.claude_hooks/secrets/recipients.txt` (anyone can encrypt)
- **Private key**: `DUCKTAPE_CLAUDE_HOOKS_SECRETS_AGE_KEY` env var (only the decryptor needs this)
- **Repo-specific context**: `.claude_hooks/templates/context.mako` is rendered and appended to the session context

### Decrypting a component

```bash
age -d -i <key_file> .claude_hooks/secrets/ollama.age
```

### Editing a component

```bash
# Decrypt to a temp file
age -d -i <key_file> .claude_hooks/secrets/ollama.age > /tmp/component.json

# Edit the JSON dict
$EDITOR /tmp/component.json

# Re-encrypt
age -e -R .claude_hooks/secrets/recipients.txt /tmp/component.json > .claude_hooks/secrets/ollama.age

# Clean up
rm /tmp/component.json
```

### Adding a new recipient

Add their age public key (one per line) to `.claude_hooks/secrets/recipients.txt`, then re-encrypt all component files.

## OTEL Tracing

Hooks emit OpenTelemetry traces to Grafana Alloy via Authentik proxy at
`alloy-otlp.allegedly.works`. Fully declarative — token flows through
Terraform → Vault → ESO → k8s secrets → `otel.py`.

Configured in `.claude_hooks/config.yaml` (`otel.endpoint`). Bearer token
loaded from k8s secret (`k8s_secrets.otel_bearer_token`).

Key files: TF module in `cluster/terraform/gitops/alloy-otlp-bearer-token/`,
Authentik blueprint in `cluster/k8s/authentik/blueprints/alloy-otlp-sso.yaml`.
Rotation: bump `rotation_version` in the TF module.

## Development

```bash
# Run tests
bazel test //devinfra/claude:test_proxy
```
