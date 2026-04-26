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

This narrows the likely fault to one of:

1. Mutter is not actually receiving / processing `orientation-changed` despite the live sensor value changing.
2. Mutter receives the event, but `meta_monitor_config_manager_create_for_orientation()` returns `NULL` before any config is applied, which is a silent path.

Current working theory:

1. The hardware path is healthy.
2. The tablet-mode switch is healthy.
3. Sensor orientation derivation is healthy.
4. GNOME/Mutter is failing somewhere between accelerometer orientation updates and monitor-config application for the internal panel in the current session/build.

## Regression Window

The user reports this worked in the past.

Observed recent local generations:

- `2026-04-18`: NixOS `25.11.20260410.54170c5`, kernel `6.19.11`
- `2026-04-19` to `2026-04-21`: NixOS `25.11.20260417.c7f4703`, kernel `6.19.12`
- `2026-04-22` current family: NixOS `25.11.20260421.10e7ad5`, kernel `6.19.13`

Likely regression window: between the older `2026-04-18` generation and the newer `2026-04-22` generation family, pending confirmation by boot test.

## Next Steps

- Inspect the exact Mutter source path around:
  - `meta_monitor_manager_get_panel_orientation_managed`
  - orientation manager sensor claim / tracking logic
- Distinguish whether manual `ApplyMonitorsConfig` rotation works:
  - if yes, sensor subscription path is broken
  - if no, monitor-config generation/apply path is broken
- Compare current session behavior against an older known-good NixOS generation.
- If older generations work, bisect whether the regression came from:
  - kernel / HID / DRM stack
  - Mutter
  - GNOME Shell / settings-daemon integration
