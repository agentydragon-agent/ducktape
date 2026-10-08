#!/usr/bin/env bash
# Runs on the CI host after nix build; the container remains its non-root image user.
set -euo pipefail
variant="$1"
loaded="$(docker load -i "$(readlink -f result)")"
printf '%s\n' "$loaded"
image="$(printf '%s\n' "$loaded" | sed -n -e 's/^Loaded image: //p' -e 's/^Loaded image ID: //p' | tail -n 1)"
test -n "$image"
docker run --rm "$image" --help
docker run --rm --entrypoint /bin/claude "$image" --version
docker run --rm --entrypoint /bin/codex "$image" --version
if [[ "$variant" == runner-ducktape ]]; then
  docker run --rm --network none -v "$PWD:/checkout:ro" --entrypoint /bin/bash "$image" -euo pipefail -c '
    test "$(id -u)" = 1000
    for tool in bb bbr bazelisk pre-commit ruff prettier nixfmt buildifier gazelle; do
      command -v "$tool"
    done
    bbr --help
    pre-commit --version
    work=$(mktemp -d)
    cd "$work"
    git init -q
    cp /checkout/.pre-commit-config.yaml /checkout/ruff.toml .
    printf "answer = 42\n" > probe.py
    printf "# Probe\n" > probe.md
    printf "{ }: { answer = 42; }\n" > probe.nix
    printf "exports_files([\"probe.py\"])\n" > BUILD.bazel
    git add .
    # Start formatted; pre-commit must then pass using the actual repository hook definitions.
    ruff format --config ruff.toml probe.py
    prettier --write probe.md
    nixfmt probe.nix
    buildifier BUILD.bazel
    pre-commit run ruff-format --files probe.py
    pre-commit run prettier --files probe.md
    pre-commit run nixfmt --files probe.nix
    pre-commit run buildifier --files BUILD.bazel
  '
fi
