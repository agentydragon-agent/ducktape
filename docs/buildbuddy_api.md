# BuildBuddy API Reference

The BuildBuddy backend is open-source: <https://github.com/buildbuddy-io/buildbuddy>.
Proto definitions live in `proto/` (service: `proto/buildbuddy_service.proto`,
public API: `proto/api/v1/service.proto`).

[Official docs](https://www.buildbuddy.io/docs/enterprise-api/) cover 9 public
endpoints. The backend also exposes ~70 internal RPCs via
`/rpc/BuildBuddyService/` that work with a standard API key.

## Authentication

API key is in `~/.config/bazel/buildbuddy.bazelrc`. All endpoints accept
`x-buildbuddy-api-key: $KEY` as an HTTP header.

## Key Capabilities

- **Search invocations** by repo, branch, commit, user, command
- **Get invocation details** (status, duration, targets, actions)
- **Read build logs** (chunked)
- **Get cache scorecard** (per-action hit/miss, durations, sizes)
- **Get execution details** (remote actions, exit codes, stderr)
- **Download artifacts** (BES event stream, build logs, profiles)

## Common Recipes

```bash
KEY="$(grep -oP 'x-buildbuddy-api-key=\K.*' ~/.config/bazel/buildbuddy.bazelrc)"
BB="https://app.buildbuddy.io"

# List recent invocations for this repo
curl -s -X POST -H "Content-Type: application/json" \
  -H "x-buildbuddy-api-key: $KEY" \
  -d '{"query":{"repo_url":"https://github.com/agentydragon/ducktape"},"count":10}' \
  "$BB/rpc/BuildBuddyService/SearchInvocation"

# Get invocation by ID (public API)
curl -s -X POST -H "Content-Type: application/json" \
  -H "x-buildbuddy-api-key: $KEY" \
  -d '{"selector":{"invocation_id":"<UUID>"}}' \
  "$BB/api/v1/GetInvocation"

# Get build log
curl -s -X POST -H "Content-Type: application/json" \
  -H "x-buildbuddy-api-key: $KEY" \
  -d '{"invocation_id":"<UUID>","min_lines":500}' \
  "$BB/rpc/BuildBuddyService/GetEventLogChunk"

# Get remote executions for an invocation
curl -s -X POST -H "Content-Type: application/json" \
  -H "x-buildbuddy-api-key: $KEY" \
  -d '{"execution_lookup":{"invocation_id":"<UUID>"},"inline_execute_response":true}' \
  "$BB/rpc/BuildBuddyService/GetExecution"

# Get cache scorecard
curl -s -X POST -H "Content-Type: application/json" \
  -H "x-buildbuddy-api-key: $KEY" \
  -d '{"invocation_id":"<UUID>"}' \
  "$BB/rpc/BuildBuddyService/GetCacheScoreCard"

# Download BES event stream (JSON)
curl -s -H "x-buildbuddy-api-key: $KEY" \
  "$BB/file/download?invocation_id=<UUID>&artifact=raw_json"

# Download build profile (for chrome://tracing or ui.perfetto.dev)
curl -s -H "x-buildbuddy-api-key: $KEY" \
  "$BB/file/download?invocation_id=<UUID>&artifact=execution_profile&execution_id=<EXEC_ID>"
```

## Downloading Undeclared Test Outputs from RBE

Tests running on RBE write undeclared outputs (`TEST_UNDECLARED_OUTPUTS_DIR`) to
the remote worker. These are uploaded to BuildBuddy as BES artifacts and can be
downloaded via the `/file/download` endpoint.

```python
# Download a test output from a BuildBuddy RBE invocation.
# Set INVOCATION and NAME_FILTER, then run the whole snippet.
import json, re, urllib.request, urllib.parse

INVOCATION = "<UUID>"       # from "Streaming build results to: .../invocation/<UUID>"
NAME_FILTER = "proxy.log"   # substring match; leave empty to list all outputs

BB = "https://app.buildbuddy.io"
KEY = re.search(r"x-buildbuddy-api-key=(\S+)",
    open("/root/.config/bazel/buildbuddy.bazelrc").read()).group(1)

def fetch(url):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"x-buildbuddy-api-key": KEY})).read()

# Parse BES event stream for test output bytestream URIs
bes = json.loads(fetch(f"{BB}/file/download?invocation_id={INVOCATION}&artifact=raw_json"))
outputs = {f["name"]: f["uri"]
           for event in bes
           for f in event.get("testResult", {}).get("testActionOutput", [])}

matches = {n: u for n, u in outputs.items() if NAME_FILTER in n} if NAME_FILTER else outputs
for name in sorted(matches):
    print(name)

# Download the first match to stdout (pipe to a file if needed)
if len(matches) == 1:
    uri = next(iter(matches.values()))
    import sys
    sys.stdout.buffer.write(fetch(
        f"{BB}/file/download?bytestream_url={urllib.parse.quote(uri, safe='')}"))
```

| Path                                       | Method | Notes                                                |
| ------------------------------------------ | ------ | ---------------------------------------------------- |
| `/api/v1/GetInvocation`                    | POST   | By invocation ID or commit SHA                       |
| `/api/v1/GetTarget`                        | POST   | Targets with label, status, rule type                |
| `/api/v1/GetLog`                           | POST   | Build stderr                                         |
| `/api/v1/GetFile`                          | POST   | Download blob by bytestream URI                      |
| `/rpc/BuildBuddyService/SearchInvocation`  | POST   | List/filter invocations (not in public API)          |
| `/rpc/BuildBuddyService/GetExecution`      | POST   | Remote execution details                             |
| `/rpc/BuildBuddyService/GetCacheScoreCard` | POST   | Per-action cache hit/miss                            |
| `/rpc/BuildBuddyService/GetEventLogChunk`  | POST   | Build log chunks                                     |
| `/file/download`                           | GET    | Artifact download (`artifact=` or `bytestream_url=`) |

For the full list of ~70 internal RPCs, see `proto/buildbuddy_service.proto` in
the [BuildBuddy repo](https://github.com/buildbuddy-io/buildbuddy).
