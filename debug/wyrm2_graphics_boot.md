# Wyrm2: GDM fails to start + SPICE resize (2026-03-10)

## Problem: GDM crash on boot

GDM 49.2 crashes with `SIGTRAP` in `get_fallback_session_name()`:

```
GdmSession: no session desktop files installed, aborting...
```

Chain:

1. NixOS sees `videoDrivers = [ "nvidia" ]` → writes `WaylandEnable=false` in GDM config
2. GDM only looks for X11 sessions in `xsessions/`
3. **GNOME 49 removed X11 sessions** — `gnome-xorg.desktop` no longer ships
4. `xsessions/` empty, `wayland-sessions/` has `gnome.desktop` → zero usable sessions → crash

## Display hardware

The display is **QXL-driven**, not NVIDIA:

| DRM card | Device          | Status                    |
| -------- | --------------- | ------------------------- |
| card0    | NVIDIA RTX 5090 | disconnected              |
| card1    | **QXL**         | **connected** (Virtual-1) |
| card2    | NVIDIA RTX 5090 | disconnected              |

NVIDIA GPUs are headless compute (VFIO passthrough, no monitors). The NixOS
auto-disable of Wayland for NVIDIA is wrong for this setup — the NVIDIA GPUs
aren't driving any display.

## Fix applied

```nix
# nix/nixos/hosts/wyrm2/default.nix
services.displayManager.gdm.wayland = true;
```

Overrides NixOS's NVIDIA auto-disable. GNOME 49 is Wayland-only, no alternative.

## SPICE resize: should work on Wayland

**Previous assumption was wrong.** spice-vdagent 0.23.0 labels itself "X11" but has
both codepaths compiled in (`vdagent_mutter_create`, `vdagent_mutter_get_resolutions`,
`org.gnome.Mutter.DisplayConfig` D-Bus strings all present in binary).

Modern SPICE resize flow ([Red Hat bug 1290586](https://bugzilla.redhat.com/show_bug.cgi?id=1290586)):

1. SPICE client tells QEMU desired resolution
2. QEMU updates QXL's available DRM modes
3. spice-vdagent notifies the desktop environment (doesn't call xrandr directly anymore)
4. **Mutter handles it** via QXL DRM hotplug — works on both X11 and Wayland

This is GNOME-specific — XFCE/KDE never implemented their side. The bug was closed
as CANTFIX (requires upstream DE work).

If resize still doesn't work after re-enabling Wayland, check:

- `spice-vdagentd.service` running (confirmed active)
- `spice-vdagent` user session agent starting after login
- Using `virt-viewer` / `remote-viewer` SPICE client (not noVNC)
- Fractional scaling off (known to cause incorrect resolution)

## SSH access

```bash
ssh -J root@10.0.182.102 root@10.0.106.97
```

## Sources

- [GNOME X11 Session Removal FAQ](https://blogs.gnome.org/alatiera/2025/06/23/x11-session-removal-faq/)
- [Red Hat bug 1290586: QXL resize works on GNOME, not XFCE/KDE](https://bugzilla.redhat.com/show_bug.cgi?id=1290586)
- [spice-vdagent mutter D-Bus commit](https://cgit.freedesktop.org/spice/linux/vd_agent/commit/?id=73bf8367268e7ef5a00fd23674b0a8700d0e4a85)
