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
