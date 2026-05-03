# gnome-extensions

Custom GNOME Shell extensions for ducktape hosts. Extensions are packaged via
`nix/packages/gnome-shell-<name>.nix` and wired into per-host home-manager config.

## Bazel-built distribution zip

Each extension exposes a `pkg_zip` target producing the standard
GNOME-extension distribution zip (extension files at the archive root, no
UUID-prefixed subdir). Same artifact the test container, the local
devkit launcher, and (eventually) the Nix release pipeline all consume:

```bash
bazelisk build //gnome-extensions/claude-quota:claude-quota_zip
# bazel-bin/gnome-extensions/claude-quota/claude-quota.zip
```

## Local iteration: nested devkit shell

`bazelisk run //gnome-extensions/claude-quota:devkit` builds the zip,
unpacks it into `~/.local/share/gnome-shell/extensions/<uuid>/`,
pre-enables the extension in dconf, and launches `gnome-shell --devkit
--wayland`. Requires `gnome-shell` on the host PATH.

To preview a specific render state (same fixture format as the golden
tests) without real auth/HTTP:

```bash
CLAUDE_QUOTA_FIXTURE=$PWD/gnome-extensions/claude-quota/test_fixtures/panel_both_warn.json \
  bazelisk run //gnome-extensions/claude-quota:devkit
```

## Watch for errors

```bash
journalctl --user -f | grep -i "claude\|error\|extension"
```

## Enable in the running session

```bash
busctl --user call org.gnome.Shell /org/gnome/Shell \
    org.gnome.Shell.Extensions EnableExtension s "claude-quota@allegedly.works"
```

## Golden render tests

`//gnome-extensions/claude-quota:test_render` boots a real `gnome-shell`
inside a Bazel-built test container
(`//gnome-extensions/test_image:gnome_shell_test_image`; gnome-shell +
Xvfb + dbus + scrot pulled hermetically via `rules_distroless` apt),
unzips the distribution zip into the extension dir, loads the indicator
under fixture state injected via the `CLAUDE_QUOTA_FIXTURE` env var, and
screenshots the panel. The right-edge crop (where the indicator lives)
is diff'd against a checked-in golden PNG via `util.testing.png_diff`.

The fixture matrix exercises each branch of the renderer:

| Fixture           | What it covers                                                                                              |
| ----------------- | ----------------------------------------------------------------------------------------------------------- |
| `panel_both_ok`   | both providers in the ok band (deviation 0)                                                                 |
| `panel_both_cool` | both providers under-running (deviation -15, cool/blue)                                                     |
| `panel_both_warn` | both providers mildly over (deviation +10, warn/yellow)                                                     |
| `panel_both_hot`  | both providers severely over (deviation +20, hot/red)                                                       |
| `panel_short_hot` | short-window absolute-hot override (≥ 85% usage) wins binding tint while long-window pace label stays "+0%" |
| `panel_mixed`     | per-provider tints don't bleed (Claude warn, Codex cool)                                                    |
| `panel_error`     | error short-circuit (red icon + `!` label) on one provider                                                  |
| `panel_no_data`   | initial state (both windows null → unknown tint, empty label)                                               |

**Fixture state injection.** When `CLAUDE_QUOTA_FIXTURE` is set,
`extension.js` skips its HTTP/credential fetch path and loads
`{claude, codex}` provider state from the JSON file. Provide
`resetSeconds` directly (not `resetAtMs`) so rendering is independent of
`Date.now()`. Format:

```json
{
  "claude": {
    "short": { "usedPercent": 50, "resetSeconds": 9000, "windowSeconds": 18000 },
    "long": { "usedPercent": 40, "resetSeconds": 362880, "windowSeconds": 604800 },
    "lastFetch": null,
    "error": null
  },
  "codex": { ... }
}
```

**Updating goldens** when a rendering change is intentional:

```bash
# 1. Re-render every fixture with UPDATE_GOLDEN=1; PNGs land in undeclared outputs.
bbr test //gnome-extensions/claude-quota:test_render \
  --test_env=UPDATE_GOLDEN=1 \
  --remote_download_outputs=toplevel --nocache_test_results

# 2. Pull each PNG from BuildBuddy into the source tree.
INV=$(cat ~/.cache/bbr/last_invocation_id)
for f in panel_both_ok panel_both_cool panel_both_warn panel_both_hot \
         panel_short_hot panel_mixed panel_error panel_no_data; do
  bbapi artifact "$INV" "$f.png" \
    > gnome-extensions/claude-quota/__snapshots__/$f.png
done

# 3. Eyeball, commit, then re-run without UPDATE_GOLDEN to confirm green.
bbr test //gnome-extensions/claude-quota:test_render
```

On comparison failure the test writes `<fixture>.{actual,expected,diff}.png`
and the gnome-shell log to undeclared outputs for inspection.
