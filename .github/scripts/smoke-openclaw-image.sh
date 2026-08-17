#!/bin/sh
set -eu

/usr/bin/env bash -c "true"
pre-commit --version
for command in bazelisk bb bbapi bbr buildifier ducktape-precommit kubeconform prettier ruff shfmt; do
  command -v "$command"
done
bbr --help >/dev/null

config="${TMPDIR:-/tmp}/openclaw-plugin-smoke.json"
plugins="${TMPDIR:-/tmp}/openclaw-plugins.json"
cat >"$config" <<'JSON'
{
  "plugins": {
    "entries": {
      "matrix": {
        "enabled": true
      }
    }
  }
}
JSON

OPENCLAW_CONFIG_PATH="$config" openclaw plugins list --json >"$plugins"
jq '{matrix: [.plugins[] | select(.id == "matrix")], diagnostics}' "$plugins"
jq -e '.plugins[] | select(.id == "matrix" and .origin == "bundled" and .status == "loaded")' "$plugins"

source=$(jq -er '.plugins[] | select(.id == "matrix") | .source' "$plugins")
case "$source" in
  */dist/extensions/matrix/dist/index.js)
    gateway_root=${source%/dist/extensions/matrix/dist/index.js}
    ;;
  */dist-runtime/extensions/matrix/dist/index.js)
    gateway_root=${source%/dist-runtime/extensions/matrix/dist/index.js}
    ;;
  *)
    echo "unexpected Matrix plugin source: $source" >&2
    exit 1
    ;;
esac
matrix_root=${source%/dist/index.js}

test -f "$matrix_root/openclaw.plugin.json"
test -d "$matrix_root/node_modules/matrix-js-sdk"
test "$(readlink -f "$matrix_root/node_modules/openclaw")" = "$gateway_root"
test -f "$gateway_root/dist/extensions/matrix/openclaw.plugin.json"
test -f "$gateway_root/dist-runtime/extensions/matrix/openclaw.plugin.json"
test "$(readlink -f "$gateway_root/dist-runtime/extensions/matrix/node_modules/openclaw")" = "$gateway_root"
jq -e '[.diagnostics[] | select(.message | contains("blocked plugin candidate"))] | length == 0' "$plugins"
test ! -e /opt/openclaw/plugins/matrix
