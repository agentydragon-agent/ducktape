# Bazel Proxy

A local proxy that adds authentication headers for upstream TLS-inspecting proxies, enabling Bazel to access the Bazel Central Registry (BCR).

## Why This Exists

Claude Code web uses a TLS-inspecting proxy that breaks Bazel's access to BCR:

1. The proxy does TLS inspection with a custom CA
2. Proxy uses JWT-based authentication in proxy credentials
3. Bazel's Java-based BCR client uses JVM properties, not env vars
4. Java's Authenticator only responds to HTTP 407, but the proxy returns 401

This package provides a workaround by running a local proxy that:
- Accepts unauthenticated CONNECT requests from Bazel
- Forwards them to the upstream proxy with proper authentication headers
- Allows Bazel to access BCR through the TLS-inspecting proxy

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
