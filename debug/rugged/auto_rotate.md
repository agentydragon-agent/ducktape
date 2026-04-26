# Rugged Auto-Rotate Investigation

Date: 2026-04-25
Host: `rugged`
Hardware: Dell Pro Rugged 12 Tablet RA02260

## Symptom

GNOME auto-rotate is not rotating the built-in display, even though this machine is a tablet and auto-rotate reportedly worked at some point in the past.

## Findings So Far

### Host configuration is correct

- The `rugged` NixOS host configuration enables IIO sensor proxy:
  - `nix/nixos/hosts/rugged/default.nix`
  - `hardware.sensor.iio.enable = true;`
- GNOME rotation lock is currently off:
  - `org.gnome.settings-daemon.peripherals.touchscreen orientation-lock false`

### Kernel/IIO sensor path works

- `/sys/bus/iio/devices` contains the expected HID sensor devices:
  - `als`
  - `magn_3d`
  - `accel_3d`
  - `gyro_3d`
  - `incli_3d`
  - `dev_rotation`
  - `relative_orientation`
- `accel_3d` produces live raw values.
- `iio-sensor-proxy.service` is active and running.
- `busctl` reports:
  - `HasAccelerometer = true`
  - `HasAmbientLight = true`

### Tablet-mode switch works

- The kernel input device `Intel HID switches` is present.
- Current `/proc/bus/input/devices` block:

```text
I: Bus=0019 Vendor=0000 Product=0000 Version=0000
N: Name="Intel HID switches"
S: Sysfs=/devices/platform/INTC107B:00/input/input13
H: Handlers=event9
B: EV=21
B: SW=2
```

- `SW=2` means the device exposes only `SW_TABLET_MODE`.
- Live switch-state read from `/dev/input/event9` returned:

```text
/dev/input/event9 0x2 [1]
```

- Interpretation:
  - `SW_TABLET_MODE` is active right now.
  - GNOME/Mutter is being told the machine is in tablet mode.

### Sensor orientation events work when explicitly claimed

- `monitor-sensor` initially appeared with orientation unset:

```text
=== Has accelerometer (orientation: undefined, tilt: undefined)
```

- After moving the device, `monitor-sensor` reported valid orientation transitions, including:
  - `Accelerometer orientation changed: normal`
  - `Accelerometer orientation changed: left-up`
  - `Accelerometer orientation changed: right-up`

- This proves:
  - The accelerometer is not missing.
  - The sensor proxy can derive orientation correctly.
  - Physical rotation is reaching userspace correctly.

## Suspicious Runtime Signals

- In the user journal, GNOME logged:

```text
gsd-power: Release of light sensors failed: GDBus.Error:org.freedesktop.DBus.Error.AccessDenied: Not Authorized: Sensor claim not allowed
```

- A direct manual D-Bus claim against `net.hadess.SensorProxy` succeeded, so the sensor service is not globally broken.
- This suggests a GNOME-side integration or policy/regression issue rather than missing hardware support.
- The `gsd-power` light-sensor warning is likely not the root cause by itself; similar
  warnings appear on otherwise-working GNOME systems and do not explain the missing
  builtin-panel rotation.

## Mutter / GNOME Boundary

- `org.gnome.Mutter.DisplayConfig.GetCurrentState` shows the built-in display as `eDP-1`.
- Direct D-Bus query now shows:
  - `org.gnome.Mutter.DisplayConfig.PanelOrientationManaged = true`
  - `HasExternalMonitor = true`
- Live `GetCurrentState` continues to show the built-in logical monitor transform as `0` (normal), even after physical rotation events.
- Mutter source references indicate orientation changes are applied through the monitor manager on `orientation-changed`.

### Relevant Mutter source path

From `/tmp/mutter-src` (commit `e14c662`):

- `src/backends/meta-monitor-manager.c`
  - `update_panel_orientation_managed()` sets panel orientation managed only when all are true:
    - `clutter_seat_get_touch_mode(seat)`
    - `meta_orientation_manager_has_accelerometer(...)`
    - built-in monitor exists
  - `orientation_changed()` returns early if `panel_orientation_managed` is false.
  - `handle_orientation_change()` computes the requested transform from accelerometer orientation and applies a temporary monitor config.
- `src/backends/meta-orientation-manager.c`
  - Mutter only receives live `AccelerometerOrientation` property updates from `iio-sensor-proxy` when it has successfully claimed the accelerometer.
- `src/tests/monitor-orientation-tests.c`
  - Mutter’s own tests explicitly expect the built-in panel to continue rotating correctly even with an external monitor connected, as long as the lid is open.

### Additional live checks

- DRM/KMS connector `eDP-1` reports:

```text
panel orientation:
  enums: Normal=0 Upside Down=1 Left Side Up=2 Right Side Up=3
  value: 0
```

- This rules out a hidden panel-orientation correction causing the physical rotation to appear as a no-op.

- While watching `org.gnome.Mutter.DisplayConfig` during tablet rotation:
  - no `MonitorsChanged` signal was observed
  - the built-in display transform remained unchanged in `GetCurrentState`

### Manual Mutter rotate works

- A direct D-Bus `ApplyMonitorsConfig` verify call succeeded for a temporary `90°`
  transform on `eDP-1`.
- A direct D-Bus `ApplyMonitorsConfig` temporary apply also succeeded.
- `GetCurrentState` immediately reflected the built-in logical monitor transform
  changing from `0` to `1` (`90°`), and a second temporary apply cleanly restored
  it to `0`.

This rules out:

1. Broken monitor-config generation for rotated builtin layouts.
2. Broken monitor-config apply for the current two-monitor session.
3. External-monitor presence as a hard blocker for built-in panel rotation.

This narrows the remaining fault to:

1. Mutter is not actually receiving / processing the live `orientation-changed`
   path despite sensor orientation changes existing in `iio-sensor-proxy`.
2. Mutter is failing to claim or stay subscribed to the accelerometer, so it never
   receives the live `AccelerometerOrientation` property updates needed to trigger
   rotation.

### Negative tests after narrowing

- Disconnecting the external `DP-1` monitor did **not** restore auto-rotate.
- Restarting `iio-sensor-proxy.service` did **not** restore auto-rotate.
- Temporarily disabling the `display-scale-switcher` GNOME Shell extension did
  **not** restore auto-rotate.
- Temporarily disabling **all** user GNOME Shell extensions did **not** restore
  auto-rotate.
- Monitoring the system D-Bus traffic for `net.hadess.SensorProxy` while:
  - toggling `orientation-lock` `true` -> `false`
  - and physically rotating the tablet
    showed **no** `ClaimAccelerometer` or `ReleaseAccelerometer` calls from the
    live session.
- A `strace` attached to the running `gnome-shell` process during the same test
  also showed:
  - `orientation-lock` dconf change notifications arriving on the session bus
  - ordinary session D-Bus traffic continuing normally
  - **no** traffic containing `net.hadess.SensorProxy`,
    `ClaimAccelerometer`, `ReleaseAccelerometer`, or
    `AccelerometerOrientation`

These additional tests rule out:

1. External-monitor presence as the practical blocker in the current setup.
2. A stale `iio-sensor-proxy` process or a one-shot missed service startup.
3. User-installed GNOME Shell extensions as the immediate cause.
4. Live auto-rotate being merely "slow" or delayed behind the observed rotation.
5. The possibility that Mutter is attempting sensor D-Bus calls that were simply
   missed by higher-level monitoring.

### Session / startup observations

- The active graphical session is `loginctl` session `2` on `seat0`, `Type=wayland`,
  `Active=yes`, `Service=gdm-password`.
- GNOME Shell registered a polkit agent under one session identifier, then later
  re-registered under `unix-session:2` after a compositor restart during login.
- GNOME logs also included:

```text
Missing required core component Settings, expect trouble…
```

- `gnome-settings-daemon` components are running in the final session, so this
  message does not mean the settings stack is absent, but it does suggest a noisy
  or unstable startup sequence.

Current working theory:

1. The hardware path is healthy.
2. The tablet-mode switch is healthy.
3. Sensor orientation derivation is healthy.
4. Manual display rotation inside Mutter works, so monitor-config generation/apply
   is healthy.
5. GNOME/Mutter is failing somewhere in the live sensor subscription or
   `orientation-changed` path inside the compositor/session build.

### Stronger Mutter-specific hypothesis

The absence of any `ClaimAccelerometer` / `ReleaseAccelerometer` traffic during the
live test suggests Mutter is not actively claiming the sensor anymore in the current
session.

Reading the source makes a startup race plausible:

- `MetaOrientationManager` only receives live orientation property updates after a
  successful `ClaimAccelerometer`.
- `MetaMonitorManager::orientation_changed()` unconditionally calls
  `meta_orientation_manager_inhibit_tracking()` on the first signal
  (`initial_orient_change_done` path).
- If startup ordering leaves the monitor manager in a state where that first signal
  lands after panel orientation has already become managed, the inhibit count may
  remain elevated in a way that suppresses future sensor claims for the rest of the
  session.

This matches the observed behavior well:

1. Manual monitor rotation still works.
2. Sensor-derived orientation exists when another client claims the sensor.
3. The live GNOME session shows no sensor claim/release activity of its own.
4. Service restart and settings toggles do not recover the session.

### Core-dump proof from the live broken session

A `gcore` dump of the running `gnome-shell` / Mutter process was inspected with
the matching `gnome-shell` and `mutter` debug outputs.

Recovered live Mutter state from the dump:

- `MetaContextPrivate.backend` points to a valid backend object.
- `MetaBackendPrivate.orientation_manager` points to a valid
  `MetaOrientationManager`.
- `MetaBackendPrivate.monitor_manager` points to a valid
  `MetaMonitorManager`.

The critical `MetaOrientationManager` fields in the broken session were:

- `has_accel = 1`
- `orientation_locked = 0`
- `should_claim = 0`
- `is_claimed = 0`
- `orientation = META_ORIENTATION_UNDEFINED`
- `inhibited_count = -1`

The paired `MetaMonitorManagerPrivate` fields were:

- `initial_orient_change_done = 0`
- `power_save_mode = META_POWER_SAVE_ON`
- `power_save_inhibit_orientation_tracking = 0`

Interpretation:

1. Mutter sees the accelerometer (`has_accel = 1`).
2. Rotation lock is not blocking it (`orientation_locked = 0`).
3. Power-save inhibition is not blocking it.
4. Mutter has never processed its first orientation event in this session
   (`initial_orient_change_done = 0`).
5. Yet the orientation manager's internal inhibit counter is already negative
   (`inhibited_count = -1`).

That is a concrete broken internal state. It directly explains why Mutter never
claims the accelerometer in this session:

- `sync_accelerometer_claimed()` only sets `should_claim = true` when
  `self->inhibited_count == 0`.
- A value of `-1` therefore suppresses `ClaimAccelerometer` permanently.

Relevant source lines:

- `src/backends/meta-orientation-manager.c`
  - `sync_accelerometer_claimed()` computes
    `should_claim = self->iio_proxy && self->inhibited_count == 0`
    (lines `287`-`326` in the inspected source tree).
  - `meta_orientation_manager_uninhibit_tracking()` blindly decrements
    `self->inhibited_count--` with no lower-bound guard
    (lines `527`-`532`).
- `src/backends/meta-monitor-manager.c`
  - `update_panel_orientation_managed()` calls
    `meta_orientation_manager_uninhibit_tracking()` immediately when panel
    orientation becomes managed
    (lines `1096`-`1131`).
  - In the captured broken session, `panel_orientation_managed = true` while
    `initial_orient_change_done = 0`, which means the negative counter was
    reached before Mutter ever handled its first orientation event.

This is substantially stronger than the earlier "maybe a startup race" theory:
the live broken session contains the exact wedged state preventing sensor claims.

### Refined startup-race interpretation

The core data and source together point to a specific ordering bug rather than a
generic random wedge.

Relevant ordering:

1. `MetaOrientationManager` starts with `inhibited_count = 0`.
2. If `iio_proxy_ready()` runs while the count is still `0`, it calls
   `sync_accelerometer_claimed()` and Mutter can claim the accelerometer.
3. The monitor manager treats the first `sensor-active` / `orientation-changed`
   signal specially and calls `meta_orientation_manager_inhibit_tracking()`,
   incrementing the counter.
4. Separately, when `update_panel_orientation_managed()` decides that tablet
   auto-rotation should be active, it calls
   `meta_orientation_manager_uninhibit_tracking()`, decrementing the counter.

This only works if those steps happen in the "lucky" order:

- first orientation signal increments to `1`
- then panel-orientation management decrements back to `0`

In the broken session, the opposite ordering happened:

- panel-orientation management decremented from `0` to `-1`
- no first orientation signal ever arrived afterward
- `should_claim` stayed false forever because the counter never returned to `0`

That ordering exactly matches the core:

- `panel_orientation_managed = true`
- `initial_orient_change_done = 0`
- `inhibited_count = -1`
- `iio_proxy != NULL`
- `has_accel = 1`
- `should_claim = 0`
- `is_claimed = 0`

So the most precise current diagnosis is:

- Mutter's auto-rotate claim path is startup-order-dependent.
- On this broken session, `update_panel_orientation_managed()` won the race
  before the first sensor-active/orientation event.
- That drove the inhibit counter negative and permanently suppressed
  `ClaimAccelerometer` for the rest of the session.

Most likely concrete callback chain:

1. `MetaOrientationManager::iio_proxy_ready()` runs.
2. It calls `update_has_accel()`.
3. `update_has_accel()` sets `has_accel = true` and emits
   `notify::has-accelerometer`.
4. `MetaMonitorManager` is connected to that notify signal, so
   `update_panel_orientation_managed()` runs immediately.
5. Because touch mode, builtin panel, and accelerometer are all now true,
   `update_panel_orientation_managed()` flips panel orientation to managed and
   calls `meta_orientation_manager_uninhibit_tracking()`.
6. At this point no prior matching inhibit has happened yet, so the counter goes
   from `0` to `-1`.
7. Control returns to `iio_proxy_ready()`, which only _then_ calls
   `sync_accelerometer_claimed()`.
8. `sync_accelerometer_claimed()` sees `inhibited_count == -1`, computes
   `should_claim = false`, and never sends `ClaimAccelerometer`.

That exact chain is not yet live-traced from a fresh login, but it is the best
fit to both:

- the source ordering in `iio_proxy_ready()`
- and the captured broken-session core state

## Package / Regression Notes

The user reports this worked in the past, including within roughly the last
three months.

Older retained local generations (`system-78`, `system-95`) and the current one
(`system-96`) all point at the same `mutter-49.2` store path:

- `/nix/store/n6qcqizvig95j7839fh1s3qm71wgvjsx-mutter-49.2`

They also point at the same `gnome-settings-daemon-49.1` build.

This means the earlier "likely regression between `2026-04-18` and
`2026-04-22`" theory is no longer supported by package evidence alone.

Updated interpretation:

1. The root cause is very likely a race/order bug already present in the
   installed `mutter-49.2` build.
2. If the user truly saw auto-rotate work on one of these retained generations,
   that would fit an intermittent startup-order race rather than a clean package
   upgrade regression.
3. A boot test into an older generation is still useful as a behavioral check,
   but not because those retained generations use a different Mutter build.

## Upstream provenance

The ordering-dependent logic was introduced upstream in Mutter commit:

- `9bed859ad` - `backend: Inhibit orientation sensor when panel orientation is not managed`
  - author date: `2024-11-11`
  - merged upstream: `2025-08-28`
  - merge request referenced by the commit message: `GNOME/mutter!4119`

That commit changed `MetaMonitorManager` to:

1. call `meta_orientation_manager_inhibit_tracking()` on the first
   `orientation-changed` path
2. call `meta_orientation_manager_uninhibit_tracking()` when panel orientation
   becomes managed
3. call `meta_orientation_manager_inhibit_tracking()` when panel orientation
   becomes unmanaged

The underlying inhibit API came from earlier commit:

- `dc7eca63c` - `orientation-manager: Add API for inhibiting orientation change listening`

As of the fetched current upstream `main`, the same `inhibited_count` logic and
the same unguarded decrement are still present. No follow-up fix for the
negative-counter startup race was found in the inspected history.

## Next Steps

The immediate next step is to activate the host-local Mutter patch on `rugged`
and test the first fresh GNOME session after the switch.

### Post-switch validation checklist

1. Run:

```bash
sudo nixos-rebuild switch --flake .#rugged
```

2. Start a fresh graphical session:
   - log out and back in, or reboot
   - a fresh session is important because the running `gnome-shell` process must
     load the patched Mutter libraries
3. Before running `monitor-sensor`, `busctl monitor`, manual D-Bus claims, or any
   other sensor-debug tooling, test auto-rotate normally:
   - ideally with no external monitor attached for the first check
   - enter tablet mode
   - rotate the device and hold each orientation for `2-3s`
4. Expected success criteria:
   - the built-in display rotates on its own
   - GNOME no longer needs another client to claim the accelerometer first

### If the patch works

1. Confirm it is stable across:
   - one logout/login cycle
   - one reboot
2. Re-test with the external monitor attached if that setup matters.
3. Use the result to prepare:
   - an upstream bug report with the captured RCA
   - and, if appropriate, an upstream patch based on the local fix

### If the patch does not work

1. Verify the patched system is actually active:
   - confirm the switch completed successfully
   - confirm the test was done in a fresh GNOME session after the switch
2. Capture one fresh failure from the patched session before using sensor tools:
   - check whether auto-rotate is still dead immediately after login
3. If still broken, return to deep instrumentation on the fresh patched session:
   - inspect `gnome-shell` state again with `gdb` / core dump
   - specifically check whether `inhibited_count` is still negative
   - and whether `panel_orientation_inhibit_tracking` reflects the intended new
     ownership logic
4. If the patched session still reaches a bad state, the next branch is either:
   - another startup-order path not covered by the current fix
   - or a separate issue downstream of sensor claiming

At this point, a pure host-config fix is no longer the interesting question. The
main question is whether the host-local Mutter patch eliminates the negative
`inhibited_count` startup wedge in a fresh session.

## Local Mitigation

A `rugged`-only Nix overlay patch was added to locally patch Mutter on this host:

- host config: `nix/nixos/hosts/rugged/default.nix`
- patch file: `nix/nixos/hosts/rugged/mutter-auto-rotate-startup-race.patch`

Patch intent:

1. Track whether `MetaMonitorManager` itself currently owns a
   panel-orientation inhibit.
2. Do not `uninhibit` when panel orientation becomes managed unless that exact
   inhibit was previously taken.
3. Do not take the one-shot "first orientation measurement" inhibit if panel
   orientation is already managed by the time the first sensor event arrives.
4. Add a defensive guard in `MetaOrientationManager` so unmatched
   `uninhibit_tracking()` calls cannot drive `inhibited_count` negative.

Validation:

- `nix build .#nixosConfigurations.rugged.config.system.build.toplevel --no-link`
  completed successfully with the host-local patch in place.
- The patched `mutter-49.2` and rebuilt `gnome-shell-49.2` both built
  successfully as part of that closure.
