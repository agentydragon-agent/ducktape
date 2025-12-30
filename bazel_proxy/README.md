# Bazel Proxy

A local proxy that adds authentication headers for upstream TLS-inspecting proxies, enabling Bazel to access the Bazel Central Registry (BCR).

## Why This Exists

[Claude Code on the web](https://docs.anthropic.com/en/docs/claude-code/claude-code-on-the-web) runs in ephemeral containers with a TLS-inspecting proxy for network egress. This breaks Bazel's access to BCR due to multiple Java/JVM limitations:

### The Problem

1. **TLS Inspection**: The proxy does TLS inspection with a custom Anthropic CA certificate
2. **JWT Authentication**: Proxy credentials include a JWT token for authentication (see [network docs](https://docs.anthropic.com/en/docs/claude-code/security#network-access))
3. **Java doesn't read env vars**: Standard Java networking uses system properties (`https.proxyHost`), not `HTTPS_PROXY` environment variables
4. **HTTP 401 vs 407**: Java's `Authenticator` class only triggers on HTTP 407 (Proxy Authentication Required), but Claude Code's proxy returns 401 (Unauthorized)
5. **Basic auth disabled by default**: Since [Java 8u111](https://confluence.atlassian.com/kb/basic-authentication-fails-for-outgoing-proxy-in-java-8u111-909643110.html), Basic authentication for HTTPS tunneling is disabled via `jdk.http.auth.tunneling.disabledSchemes=Basic`

### The Solution

This local proxy acts as an authentication intermediary:
- Accepts unauthenticated CONNECT requests from Bazel on `localhost:18081`
- Forwards them to the upstream proxy with proper `Proxy-Authorization: Basic` headers
- Handles credential refresh when JWTs are rotated (reads from file on each connection)
- Allows Bazel to access BCR without any Java authentication workarounds

## References

- [Claude Code on the Web](https://docs.anthropic.com/en/docs/claude-code/claude-code-on-the-web) - Container environment overview
- [Network Configuration](https://docs.anthropic.com/en/docs/claude-code/security#network-access) - Proxy and network egress details
- [Enterprise Configuration](https://docs.anthropic.com/en/docs/claude-code/enterprise) - TLS certificate configuration

## Important Constraint

**This package must not have any non-stdlib dependencies.**

It's used by session-start hooks which run before package installation. The hook needs to start the proxy before Bazel can fetch its dependencies.

## Usage

### As a daemon (typical usage)

```bash
# Start proxy in background (kills any existing proxy first)
python -m bazel_proxy.proxy -d

# Kill existing proxy
python -m bazel_proxy.proxy -k
```

### CLI options

```
--listen-host    Host to listen on (default: 127.0.0.1)
--listen-port    Port to listen on (default: 18081)
--state-dir      Directory for pidfile and log (default: ~/.cache/bazel-proxy/)
-d, --daemonize  Fork to background
-k, --kill       Kill existing proxy and exit
```

### From session-start hook

The hook (`bazel_proxy_setup.py`) handles the full setup:

1. Extracts the TLS inspection CA from the proxy via openssl
2. Creates a Java truststore with the CA
3. Starts this proxy at `127.0.0.1:18081`
4. Writes `~/.bazelrc` with JVM properties for proxy and truststore

## How It Works

1. Proxy reads `https_proxy` / `HTTPS_PROXY` from environment at startup
2. Extracts hostname, port, and credentials from the proxy URL
3. Listens for CONNECT requests on the local port
4. Forwards CONNECT requests to upstream with `Proxy-Authorization: Basic ...` header
5. Pipes data between client and upstream after tunnel is established

## Lifecycle Management

The proxy manages its own lifecycle:

- **Pidfile**: Written to `~/.cache/bazel-proxy/proxy.pid`
- **Logging**: When daemonized, logs to `~/.cache/bazel-proxy/proxy.log`
- **Restart**: Starting the proxy automatically kills any existing instance
- **Cleanup**: Pidfile is cleaned up on exit via atexit

## Verification

After session start:

```bash
# Proxy should be running
curl -s --max-time 5 -x http://127.0.0.1:18081 https://bcr.bazel.build/ | head -1

# Bazel should be able to access BCR
bazel info

# Check proxy log
cat ~/.cache/bazel-proxy/proxy.log
```

## Files

Runtime files (in `~/.cache/bazel-proxy/`):
- `proxy.pid` - Process ID file
- `proxy.log` - Proxy output log (when daemonized)

Setup files (created by `bazel_proxy_setup.py`):
- `anthropic_ca.pem` - Extracted TLS inspection CA
- `cacerts.jks` - Java truststore with CA
- `bazelrc` - Proxy startup options

## Development

```bash
# Run tests
pytest bazel_proxy/tests/

# With Bazel (if Bazel can access BCR)
bazel test //bazel_proxy:test_bazel_proxy
```
