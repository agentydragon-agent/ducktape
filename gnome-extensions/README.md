# gnome-extensions

Custom GNOME Shell extensions for ducktape hosts. Extensions are packaged via
`nix/packages/gnome-shell-<name>.nix` and wired into per-host home-manager config.

## Testing

### Nested shell (GNOME 49+)

`--nested` was removed in GNOME 45. The replacement is `--devkit`:

```bash
dbus-run-session -- gnome-shell --devkit --wayland --wayland-display $WAYLAND_DISPLAY
```

### Symlink source tree for live editing

Point the local extensions dir at the source tree so edits take effect without
rebuilding the Nix package:

```bash
ln -sfn ~/code/ducktape/gnome-extensions/claude-quota \
        ~/.local/share/gnome-shell/extensions/claude-quota@allegedly.works
```

### Watch for errors

```bash
journalctl --user -f | grep -i "claude\|error\|extension"
```

### Enable in the running session

```bash
busctl --user call org.gnome.Shell /org/gnome/Shell \
    org.gnome.Shell.Extensions EnableExtension s "claude-quota@allegedly.works"
```

## Golden render tests

`//gnome-extensions/claude-quota:test_render` boots a real `gnome-shell`
inside a Bazel-built test container (`//gnome-extensions/test_image:gnome_shell_test_image`,
gnome-shell + Xvfb + dbus pulled hermetically via `rules_distroless` apt),
loads the extension under a fixture state injected via the
`CLAUDE_QUOTA_FIXTURE` env var, and screenshots the panel via `scrot`. The
right-edge crop (where our indicator lives) is diff'd against a golden PNG
checked in under `claude-quota/__snapshots__/`.

**Fixture state injection.** When `CLAUDE_QUOTA_FIXTURE` is set,
`extension.js` skips its HTTP/credential fetch path and loads
`{claude, codex}` provider state from the JSON file. Format:

```json
{
  "claude": {
    "short": {"usedPercent": 50, "resetSeconds": 9000, "windowSeconds": 18000},
    "long":  {"usedPercent": 40, "resetSeconds": 362880, "windowSeconds": 604800},
    "lastFetch": null,
    "error": null
  },
  "codex": { ... }
}
```

Provide `resetSeconds` directly (not `resetAtMs`) so rendering is
independent of `Date.now()`.

**Updating a golden** when a rendering change is intentional:

```bash
# 1. Re-render with UPDATE_GOLDEN=1; PNG lands in undeclared outputs.
bbr test //gnome-extensions/claude-quota:test_render \
  --test_env=UPDATE_GOLDEN=1 \
  --remote_download_outputs=toplevel --nocache_test_results

# 2. Pull from BuildBuddy and overwrite the source-tree golden.
bbapi artifact $(cat ~/.cache/bbr/last_invocation_id) panel_both_ok.png \
  > gnome-extensions/claude-quota/__snapshots__/panel_both_ok.png

# 3. Eyeball, commit, then re-run without UPDATE_GOLDEN to confirm green.
bbr test //gnome-extensions/claude-quota:test_render
```

On comparison failure the test writes `panel_both_ok.{actual,expected,diff}.png`
and the gnome-shell log to undeclared outputs for inspection.
