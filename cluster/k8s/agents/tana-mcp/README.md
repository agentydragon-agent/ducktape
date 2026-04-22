# Tana MCP Server

Runs the [Tana](https://tana.inc) desktop app in a Kubernetes container with an
nginx proxy that rewrites `Host`/`Origin` headers to `localhost` so Tana's MCP
server accepts requests from cluster clients.

## Architecture

- **tana-desktop container**: Ubuntu + Xvfb + noVNC + Tana Desktop. Tana's MCP
  server listens on `localhost:8262` inside the pod.
- **proxy sidecar**: `nginx:alpine` rewrites `Host`/`Origin` to localhost before
  proxying to port 8262. Exposed on port 8263 (cluster-internal only).
- **token-broker sidecar**: Performs OAuth 2.1 + PKCE flow against Tana's MCP
  server, obtains access/refresh tokens, and writes them to the
  `tana-mcp-oauth-tokens` K8s secret. Refreshes automatically before expiry.
- **PVC**: Persists `~/.config/Tana` (login session, MCP client approvals).

## Initial Setup (Graphical Login)

The Tana desktop app requires a one-time graphical login to your Tana account.
After login, the session persists in the PVC across pod restarts.

### Expected pre-login state

Before the one-time login is completed, the deployment intentionally looks
"half up":

- `kubectl -n tana-mcp get deploy,pods` shows the deployment at `0/1` and the
  pod at `2/3`
- `kubectl -n tana-mcp logs deploy/tana-mcp -c token-broker` repeats
  `Tana not ready, retry attempt ...`
- `kubectl -n tana-mcp get secret tana-mcp-oauth-tokens` returns `NotFound`

That is the expected state before the GUI login and MCP toggle are done.

### 1. Start from a fresh pod window

The `tana-desktop` container has a `startupProbe` on `/health`. Until login is
finished and the MCP server is enabled, Kubernetes restarts it roughly every 20
minutes. Start with a fresh restart window so you are not racing an old pod:

```bash
kubectl -n tana-mcp rollout restart deploy/tana-mcp
kubectl -n tana-mcp rollout status deploy/tana-mcp --timeout=2m
kubectl -n tana-mcp get pods -w
```

Wait until the new pod is `Running` and shows `2/3` ready.

### 2. Connect via noVNC

```bash
kubectl port-forward -n tana-mcp svc/tana-mcp 6080:6080
```

Open <http://localhost:6080> in your browser. You'll see the Tana desktop app
running in a virtual display.

If the root page does not auto-connect cleanly, open:

- <http://localhost:6080/vnc.html?autoconnect=true&resize=scale>

### 3. Sign into Tana

- The Tana app shows its login screen on startup
- Sign in with your Tana account (email + password, or SSO)
- The login flow opens a separate browser window inside the same virtual
  desktop via `xdg-open`
- If the Tana window says `Logging in using browser...`, stay in noVNC and look
  for the browser window there rather than on your host desktop

### 4. Enable the MCP Server

- Open Tana Settings (gear icon, or Menu > Options)
- Navigate to **Tana Labs**
- Enable **"Local API/MCP server (Alpha)"**
- The MCP server starts on port 8262 inside the container

### 5. Wait for the broker to finish OAuth

Once the MCP server is healthy, the `token-broker` sidecar does the OAuth
registration + PKCE flow automatically and writes the token secret.

Use a second terminal:

```bash
kubectl -n tana-mcp logs deploy/tana-mcp -c token-broker -f
```

Success looks like:

- `Tana MCP server is healthy`
- `Registered OAuth client ...`
- `Created secret tana-mcp/tana-mcp-oauth-tokens` or
  `Updated secret tana-mcp/tana-mcp-oauth-tokens`

You can verify separately:

```bash
kubectl -n tana-mcp get secret tana-mcp-oauth-tokens
kubectl -n tana-mcp get deploy,pods
```

The deployment should move to `1/1` available and the pod to `3/3` ready.

### 6. Disconnect noVNC

Close the browser tab. The Tana app continues running headlessly. You only need
noVNC again if the session expires or for troubleshooting.

## Connecting MCP Clients

The MCP endpoint is cluster-internal only (no public ingress).

- **Endpoint**: `http://tana-mcp.tana-mcp.svc.cluster.local:8263/mcp`
- **Auth**: The token-broker sidecar obtains OAuth tokens automatically. Clients
  can read the `tana-mcp-oauth-tokens` secret for the access token and include
  `Authorization: Bearer <token>` in requests.

### Health Check

```bash
kubectl exec -n tana-mcp deploy/tana-mcp -c proxy -- \
  curl -s http://localhost:8263/health
```

### Port Forward for Local Testing

```bash
kubectl port-forward -n tana-mcp svc/tana-mcp 8263:8263
curl http://localhost:8263/health
```

## Troubleshooting

- **Deployment stays `0/1`, pod stays `2/3`**: This is normal until the Tana
  login is complete and **Tana Labs > Local API/MCP server (Alpha)** is turned
  on.
- **Pod restarts while you are logging in**: The `startupProbe` allows about 20
  minutes for the initial setup. Restart the deployment to get a fresh window,
  then reconnect via noVNC.
- **MCP health check failing**: Tana may not be running or MCP not enabled.
  Connect via noVNC to check.
- **`Logging in using browser...` but no browser appears**: The pod is likely
  running an older `tana-desktop` image without the browser-launching
  dependencies (`xdg-utils` + GUI browser). Rebuild and redeploy the image,
  then retry the login flow.
- **`tana-mcp-oauth-tokens` secret missing**: The broker only creates it after
  Tana is healthy. Check `kubectl -n tana-mcp logs deploy/tana-mcp -c token-broker`
  first.
- **Session expired**: Connect via noVNC and sign in again. The PVC preserves
  state across normal pod restarts but Tana may expire the session after
  prolonged inactivity.
- **Updating Tana version**: Change `TANA_VERSION` in
  `tana/mcp_server/Dockerfile` and push. CI rebuilds the image and Flux
  auto-deploys.

## Secrets

| Secret                  | Key                 | Source                               |
| ----------------------- | ------------------- | ------------------------------------ |
| `harbor-pull-robot`     | `.dockerconfigjson` | harbor-ci TF (Reflector mirror)      |
| `tana-mcp-oauth-tokens` | `access_token`      | Auto-managed by token-broker sidecar |
| `tana-mcp-oauth-tokens` | `refresh_token`     | Auto-managed by token-broker sidecar |
