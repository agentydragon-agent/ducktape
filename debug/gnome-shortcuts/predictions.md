# Predictions: Disable V-Shell + Remove KB Overrides

Date: 2026-03-23
Branch: `gnome-shortcuts`

## Changes Made

1. **Removed `vertical-workspaces` (V-Shell)** from `programs.gnome-shell.extensions` in `home.nix`
2. **Stripped `gnome-workspace-shortcuts.nix`** to only Pop Shell tiling prefs (`gap-inner=1`, `gap-outer=1`, `tile-by-default=true`). Removed all dconf overrides:
   - WM keybinding overrides (workspace up/down/left/right, move-to-workspace)
   - Pop Shell shortcut clears (`pop-workspace-*`, `pop-monitor-*`)
   - Dash-to-dock hotkey clears

## Key Uncertainty: dconf Reset Behavior

Home-manager may or may not reset dconf keys that were previously set but are now removed from config. Two scenarios:

### Scenario A: Home-manager resets removed keys (expected for recent versions)

All overrides revert to schema defaults. Predicted state:

**Workspace layout**: Horizontal (GNOME 40+ default without V-Shell).

**GNOME WM keybindings** (schema defaults for GNOME 49):

| Shortcut                | Action                 | Notes                                           |
| ----------------------- | ---------------------- | ----------------------------------------------- |
| `Ctrl+Alt+Left`         | Switch workspace left  | Schema default (was previously overridden)      |
| `Ctrl+Alt+Right`        | Switch workspace right | Schema default (was previously cleared to `[]`) |
| `Super+Up`              | Maximize               | Schema default                                  |
| `Super+Down` / `Alt+F5` | Unmaximize             | Schema default                                  |
| `Super+h`               | Minimize               | Schema default                                  |
| `Alt+F4`                | Close                  | Schema default                                  |
| `Super+Tab` / `Alt+Tab` | Switch applications    | Schema default                                  |

**Pop Shell keybindings** (all restored to schema defaults):

| Shortcut                | Action             | Previously              |
| ----------------------- | ------------------ | ----------------------- |
| `Super+Left/h`          | Focus left         | Was active (default)    |
| `Super+Right/l`         | Focus right        | Was active (default)    |
| `Super+Up/k`            | Focus up           | Was active (default)    |
| `Super+Down/j`          | Focus down         | Was active (default)    |
| `Super+Return`          | Enter tiling mode  | Was active (default)    |
| `Super+y`               | Toggle auto-tiling | Was active (default)    |
| `Super+g`               | Toggle floating    | Was active (default)    |
| `Super+o`               | Toggle orientation | Was active (default)    |
| `Super+/`               | Launcher           | Was active (default)    |
| `Super+s`               | Toggle stacking    | Was active (default)    |
| `Super+Shift+Up`        | Pop workspace up   | **Was cleared to `[]`** |
| `Super+Shift+Down`      | Pop workspace down | **Was cleared to `[]`** |
| `Super+Shift+Left`      | Pop monitor left   | **Was cleared to `[]`** |
| `Super+Shift+Right`     | Pop monitor right  | **Was cleared to `[]`** |
| `Super+Shift+Ctrl+Up`   | Pop monitor up     | **Was cleared to `[]`** |
| `Super+Shift+Ctrl+Down` | Pop monitor down   | **Was cleared to `[]`** |

**Known conflicts** (all at schema defaults, no resolution applied):

| Shortcut      | Pop Shell        | GNOME                          | Expected winner                 |
| ------------- | ---------------- | ------------------------------ | ------------------------------- |
| `Super+h`     | Focus left       | Minimize                       | GNOME (intercepts first)        |
| `Super+l`     | Focus right      | Lock screen (media-keys)       | GNOME (intercepts first)        |
| `Super+s`     | Toggle stacking  | Quick settings (Shell)         | Needs testing                   |
| `Super+o`     | Tile orientation | Rotate video lock (media-keys) | Needs testing                   |
| `Super+Up`    | Focus up         | Maximize (WM)                  | Pop Shell (observed previously) |
| `Super+Down`  | Focus down       | Unmaximize (WM)                | Pop Shell (observed previously) |
| `Super+Left`  | Focus left       | Toggle tiled left (Mutter)     | Pop Shell (observed previously) |
| `Super+Right` | Focus right      | Toggle tiled right (Mutter)    | Pop Shell (observed previously) |

### Scenario B: Home-manager does NOT reset removed keys (stale dconf persists)

Old dconf overrides remain. Predicted state:

**Broken workspace navigation**:

- `switch-to-workspace-left` = `[]` (stale clear)
- `switch-to-workspace-right` = `[]` (stale clear)
- `switch-to-workspace-up` = `['<Primary><Alt>Up']` (stale override, won't work without V-Shell)
- `switch-to-workspace-down` = `['<Primary><Alt>Down']` (stale override, won't work without V-Shell)
- Pop Shell `pop-workspace-*` still cleared to `[]`
- **Result: no workspace switching works at all**

**How to detect**: After `home-manager switch`, before logout:

```bash
dconf read /org/gnome/desktop/wm/keybindings/switch-to-workspace-left
```

If it shows `@as []`, we're in Scenario B.

**Fix for Scenario B**:

```bash
dconf reset -f /org/gnome/desktop/wm/keybindings/
dconf reset -f /org/gnome/shell/extensions/pop-shell/
dconf reset -f /org/gnome/shell/extensions/dash-to-dock/
```

## Verification Plan

After switch + re-login:

1. Check workspace layout is horizontal (overview should show workspaces side-by-side)
2. Test `Ctrl+Alt+Left/Right` for workspace switching
3. Test `Super+Left/Right/Up/Down` for Pop Shell focus
4. Test `Super+Return` for tiling mode entry
5. Test `Super+h` — expect minimize (GNOME wins), not focus-left
6. Test `Super+l` — expect lock screen (GNOME wins), not focus-right
7. Check Pop Shell `Super+Shift+Up/Down` workspace shortcuts are active again
