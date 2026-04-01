# Plan: Migrate Rai's HA Config to YAML/Git

Target: `homeassistant/packages/rai/` in this repo, synced to the HA box via `homeassistant/deploy.sh` (rsync diff + prompt + `reload_all`). No automated git pull — manual deploy for now.

Config lives in `/config/` on the HA box.

---

## Step 1: Enable packages in `configuration.yaml`

SSH in and edit `/config/configuration.yaml`. Add under the `homeassistant:` block:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Create the directories:

```bash
ssh homeassistant 'mkdir -p /config/packages/rai'
```

Then restart or reload HA to pick up the new `packages:` key. This is a structural config change — it requires a full HA restart (not just reload).

---

## Step 2: Create package files in this repo

All files go under `homeassistant/packages/rai/`.

### `automations.yaml`

Extract these 5 automations from `/config/automations.yaml` (match by `id:`):

- `1728265492434` — `Rai room switch toggles lights`
- `1728693363194` — `Rai remote "off" -> turn off lights`
- `1728693417656` — `Rai remote "on" -> lights on`
- `1730106847448` — `Rai room: sleep lights @ 0:00 AM`
- `1730106913259` — `Rai room - sleep lights off @ 6 AM`

Also pull in the full content of `/config/automation/rai_webhook_inbox.yml`:

- `Rai webhook inbox - state change`
- `Rai webhook inbox - air quality per 15 min`

In a package file, automations use the `automation:` key with a list. Format:

```yaml
automation:
  - id: "1728265492434"
    alias: Rai room switch toggles lights
    # ... rest of automation ...

  - id: "1728693363194"
    # ...

  # ... (all 7 automations) ...
```

### `scenes.yaml`

Extract these 3 scenes from `/config/scenes.yaml` (match by `id:`):

- `1726220894378` — `Rai's room work lights`
- `1726221468922` — `Rai's room lights off`
- `1738486322099` — `Rai's room sleep mode plus nook light`

Package format uses the `scene:` key (not a bare list):

```yaml
scene:
  - id: "1726220894378"
    name: Rai's room work lights
    # ...
  - id: "1726221468922"
    name: Rai's room lights off
    # ...
  - id: "1738486322099"
    name: Rai's room sleep mode plus nook light
    # ...
```

### `sensors.yaml`

Move from `/config/configuration.yaml`:

- The `indoor_aqi` sensor under `sensor:` (Rai's room AQI)
- The `rest_command.rai_webhook_inbox` entry under `rest_command:`
- The `_tmpl:` YAML anchors block (used by the template block below)
- The entire `template:` block for Pixel 6 Bluetooth sensors (Shokz + Bose QC45)

Example structure:

```yaml
sensor:
  - platform: ...
    # indoor_aqi config

rest_command:
  rai_webhook_inbox:
    # ...

# YAML anchors (must appear before the template block that references them)
_tmpl:
  # ...

template:
  - sensor:
      # Pixel 6 Bluetooth sensors
```

Note: YAML anchors (`&anchor` / `*anchor`) work within a single file but not across files. Keep the `_tmpl:` block and the `template:` block that uses it in the same file.

### `adaptive_lighting.yaml`

The adaptive lighting integration for Rai's room is currently managed via the UI (config entry `01J9R78HZ7DS3890BR6RWHH8G2` in `.storage/core.config_entries`).

**Migration steps (requires HA restart):**

1. In HA UI: Settings → Devices & Services → Adaptive Lighting → find the "Rai room lights" entry → delete it.
2. Push `adaptive_lighting.yaml` to the HA box (see Step 3).
3. Do a full HA restart (`ha core restart`).

File content — YAML config uses a list under `adaptive_lighting:`. Omit all `null`/`None` values (they are defaults). Only non-default values need to be specified:

```yaml
adaptive_lighting:
  - name: Rai room lights
    lights:
      - light.rai_s_room_ceiling_lights
    adapt_delay: 0.0
    adapt_only_on_bare_turn_on: false
    autoreset_control_seconds: 0
    brightness_mode: default
    brightness_mode_time_dark: 900
    brightness_mode_time_light: 3600
    detect_non_ha_changes: false
    include_config_in_attributes: true
    initial_transition: 1.0
    intercept: true
    interval: 90
    max_brightness: 100
    max_color_temp: 6500
    min_brightness: 1
    min_color_temp: 2700
    multi_light_intercept: true
    only_once: false
    prefer_rgb_color: false
    send_split_delay: 0
    separate_turn_on_commands: false
    skip_redundant_commands: false
    sleep_brightness: 1
    sleep_color_temp: 1000
    sleep_rgb_color: [255, 56, 0]
    sleep_rgb_or_color_temp: rgb_color
    sleep_transition: 1.0
    take_over_control: true
    transition: 45.0
    transition_until_sleep: false
```

### `helpers.yaml`

`input_button.trigger_low_battery_check` is currently managed via UI (in `.storage/input_button`).

**Migration steps:**

1. In HA UI: Settings → Helpers → find `trigger_low_battery_check` → delete it.
2. Push `helpers.yaml` to the HA box.
3. Run `ha core service homeassistant/reload_all` (or reload via UI).

File content:

```yaml
input_button:
  trigger_low_battery_check:
    name: Trigger low battery check
    icon: mdi:battery-charging-wireless-outline
```

### `dashboard.yaml` (reference/backup only — not auto-loaded)

The Rai dashboard (`lovelace.dashboard_rai`, url path `dashboard-rai`) is currently in `mode: storage` (`.storage/lovelace.dashboard_rai`). It has 5 views:

- `rai-s-room`: main room overview (light controls, temp/CO2, occupancy history, battery levels, desk plug)
- `lights`: per-LED-row controls, adaptive lighting toggles, scene buttons
- `atmosphere`: CO2/VOC/temp/humidity history graphs
- `charges` (sections layout): Pixel 6 battery, ThinkPad/headphone batteries via halinuxcompanion
- `thinkpad`: CPU/GPU temps, load, fan speeds

For now: copy the raw JSON from `.storage/lovelace.dashboard_rai` on the HA box, convert to YAML, and store as `homeassistant/packages/rai/dashboard.yaml`. This is a **reference/backup only** — Lovelace dashboards are not loaded via the packages mechanism.

**Actual YAML-mode migration (separate, later — see Step 5).**

---

## Step 3: Deploy script

Create `homeassistant/deploy.sh` — checks for diffs between local package files and
what's on the HA box, then offers to deploy:

```bash
#!/usr/bin/env bash
set -euo pipefail

HA_HOST=homeassistant
HA_PACKAGES_DIR=/config/packages/rai
LOCAL_DIR="$(cd "$(dirname "$0")/packages/rai" && pwd)"

echo "=== Diff: local vs HA ==="
if rsync -avn --out-format="%n" "$LOCAL_DIR/" "$HA_HOST:$HA_PACKAGES_DIR/" | grep -q .; then
    rsync -avn --out-format="%i %n" "$LOCAL_DIR/" "$HA_HOST:$HA_PACKAGES_DIR/"
    echo
    read -rp "Deploy? [y/N] " answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
        rsync -av "$LOCAL_DIR/" "$HA_HOST:$HA_PACKAGES_DIR/"
        echo "=== Reloading HA ==="
        ssh "$HA_HOST" 'ha core service homeassistant/reload_all'
        echo "Done."
    else
        echo "Aborted."
    fi
else
    echo "No differences — HA is up to date."
fi
```

Usage: `./homeassistant/deploy.sh` from anywhere in the repo.

For changes that need a full restart (adaptive_lighting YAML migration, adding the
`packages:` key for the first time):

```bash
ssh homeassistant 'ha core restart'
```

---

## Step 4: Remove migrated items from global config files

**Do this only after verifying the package versions load correctly** (check HA logs, confirm entities/automations/scenes are present and functional).

### `/config/automations.yaml`

Remove the 5 Rai automation blocks (identified by `id:` values listed in Step 2). Leave all non-Rai automations in place.

### `/config/automation/rai_webhook_inbox.yml`

Delete this file entirely:

```bash
ssh homeassistant 'rm /config/automation/rai_webhook_inbox.yml'
```

### `/config/scenes.yaml`

Remove the 3 Rai scene blocks (by `id:`). Leave all non-Rai scenes.

### `/config/configuration.yaml`

Remove:

- The `indoor_aqi` sensor entry
- The `rest_command.rai_webhook_inbox` entry
- The `_tmpl:` anchors block
- The `template:` block containing Pixel 6 Bluetooth sensors

After all removals, run `ha core check_config` before restarting:

```bash
ssh homeassistant 'ha core check_config'
```

Then reload:

```bash
ssh homeassistant 'ha core service homeassistant/reload_all'
```

---

## Step 5: Lovelace dashboard YAML migration (separate, later)

Currently `dashboard-rai` is `mode: storage` — UI drag-and-drop works, but config is not in git.

To switch to `mode: yaml`:

1. Choose a filename, e.g. `packages/rai/dashboard_rai_lovelace.yaml`.
2. Place the YAML file at `/config/packages/rai/dashboard_rai_lovelace.yaml` on the HA box.
3. Change the dashboard registration. Options:
   - **HA UI**: Settings → Dashboards → click the Rai dashboard → Edit → there may be a "Take control" or YAML mode toggle (availability depends on HA version).
   - **REST API**:
     ```bash
     # Get the dashboard slug first, then PATCH:
     curl -X PATCH http://10.0.0.3:8123/api/lovelace/dashboards/dashboard-rai \
       -H "Authorization: Bearer <token>" \
       -H "Content-Type: application/json" \
       -d '{"mode": "yaml", "filename": "packages/rai/dashboard_rai_lovelace.yaml"}'
     ```
   - **Direct `.storage` edit** (last resort): edit `.storage/lovelace_dashboards` to change `mode` and add `filename`, then restart HA.
4. Restart HA after the registration change.

**Tradeoff**: Once in YAML mode, the UI drag-and-drop editor is disabled for this dashboard. Card edits require editing the YAML file and syncing.

---

## Reload vs Restart Reference

| Change                                                                     | Required action                         |
| -------------------------------------------------------------------------- | --------------------------------------- |
| Automations, scenes, scripts, input_button, template sensors, rest_command | `homeassistant/reload_all`              |
| Adding `packages:` key to `configuration.yaml`                             | Full restart                            |
| Deleting UI adaptive_lighting entry + adding YAML                          | Full restart                            |
| Deleting UI input_button + adding YAML                                     | `reload_all` (or just "Helpers" reload) |
| Lovelace dashboard mode change                                             | Full restart                            |

---

## Risk Notes

- **Never remove from global files until the package version is confirmed working.** HA will error if the same entity/automation `id` appears in both the package and the global file — so verify the package loads cleanly first, then delete from global.
- **YAML anchors are file-scoped.** The `_tmpl:` anchors and the `template:` block that uses them must be in the same file.
- **Adaptive lighting deletion is irreversible via UI** — make sure the YAML config is correct before deleting the UI entry, because the entity history will show a gap if you have to re-add it.
- Always run `ha core check_config` after editing `configuration.yaml` before applying changes.
