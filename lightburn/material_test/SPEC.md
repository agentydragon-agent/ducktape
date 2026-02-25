# Material Test Grid Generator — Feature Specification

Generates parametric material test grids as LightBurn `.lbrn2` files. Each run produces a
grid of laser-cut squares where rows and columns correspond to two varying laser parameters,
making it easy to visually evaluate results across the parameter space in a single job.

## Concept

A rectangular grid of laser-cut squares where:

- Each **column** corresponds to one value of an X-axis parameter
- Each **row** corresponds to one value of a Y-axis parameter
- Each **cell** is cut with that cell's specific (x-param, y-param) combination
- All other parameters are held constant across the entire grid

Example: X axis = power (12%, 13.5%, 15%, 16.5%, 18%), Y axis = ΔZ/pass (−0.5 to −0.8 mm)
→ 20 cells, each cut at a unique (power, z-per-pass) pair.

## Supported Cut Parameters

Parameters that can be varied on X or Y axes, or held constant:

| Parameter name | Description                      | Typical unit |
| -------------- | -------------------------------- | ------------ |
| `power`        | Min and max power (set together) | %            |
| `power_min`    | Minimum power only               | %            |
| `power_max`    | Maximum power only               | %            |
| `speed`        | Cut speed                        | mm/s         |
| `kerf`         | Kerf compensation offset         | mm           |
| `z_offset`     | Z offset at start of layer       | mm           |
| `z_per_pass`   | Z step per pass (typically ≤ 0)  | mm           |
| `num_passes`   | Number of passes                 | integer      |

## Grid Geometry

- `cell_size` — Side length of each square cell, default 15 mm
- `gap` — Gap between adjacent cells (both X and Y), default 8 mm
- Cell stride = `cell_size + gap`
- Grid is tight: no outer padding beyond the cell edges (margin is separate)

## Annotations

### X-axis annotation (above the grid)

When enabled, per-column parameter values appear above each column, centered.
Below the values, the X-axis label appears (centered over all columns).

Example (X = power):

```
12    13.5   15    16.5   18
         Power [%]
```

### Y-axis annotation (left of the grid)

When enabled, per-row parameter values appear to the left of each row, right-aligned
and vertically centered on the row.

To the left of the values, the Y-axis label appears rotated 90° CCW (reading bottom-to-top),
centered vertically over the grid height.

Example (Y = ΔZ/pass):

```
─0.5
─0.6
─0.7   (with "ΔZ/pass [mm]" rotated 90° to the far left)
─0.8
```

### In-cell text (optional)

When enabled, the X and Y parameter values for each cell are printed as two text lines
inside the cell (centered). Font size is configurable and defaults to something small enough
to fit within the cell.

Example for a 15 mm cell with power=15, z_per_pass=−0.6:

```
  15
 -0.6
```

### Title and subtitle (optional)

A title line appears above the grid, and a subtitle appears below the title. The subtitle
can be auto-generated from the constant parameter values.

Example:

```
6.08mm ply, Lauan
Z=−0.1, 15 mm/s, kerf 0.1 mm
```

The auto-generated subtitle includes only parameters that are not being varied on either axis.
An optional extra title text can be prepended to the subtitle (user-supplied).

### Border (optional)

A border rectangle can be drawn around the entire grid, using a separate configurable
cut setting. The border is padded a configurable amount outside the grid cells.

## LightBurn Layer Structure

| Layer index      | Content                                        |
| ---------------- | ---------------------------------------------- |
| 0                | All text (title, labels, values, in-cell text) |
| 1 … N×M          | One cut layer per grid cell (N cols × M rows)  |
| N×M+1 (optional) | Border rectangle layer                         |

Each grid cell gets its own `CutSetting` because the combination of X and Y parameter
values is unique per cell. Layer 0 uses a distinct, low-power cut setting for marking.

## Usage

```
bazel run //lightburn/material_test -- config.toml [-o output.lbrn2]
```

All parameters are supplied via a TOML configuration file. The output path defaults to the
config filename with `.lbrn2` extension. See `example_config.toml` for a fully annotated
example.

### TOML config reference

**Top-level:**

| Key             | Default | Description                                         |
| --------------- | ------- | --------------------------------------------------- |
| `title`         | `""`    | Main title printed above the grid                   |
| `subtitle`      | `""`    | Extra text prepended to the auto-generated subtitle |
| `auto_subtitle` | `true`  | Append constant-parameter summary to subtitle       |

**`[x]` and `[y]` — axis configuration:**

| Key                | Default | Description                                                        |
| ------------------ | ------- | ------------------------------------------------------------------ |
| `param`            | —       | Parameter to scan (`power`, `power_max`, `speed`, `z_per_pass`, …) |
| `values`           | —       | List of values to sweep, e.g. `[10, 20, 30]`                       |
| `label`            | auto    | Axis label; omit to auto-generate from param name and unit         |
| `show_annotations` | `true`  | Show per-tick value labels and the axis label                      |

**`[cut]` — constant cut parameters:**

| Key          | Default | Description                            |
| ------------ | ------- | -------------------------------------- |
| `power`      | —       | Shorthand: sets both `power_min`/`max` |
| `power_min`  | 80      | Minimum power (%)                      |
| `power_max`  | 80      | Maximum power (%)                      |
| `speed`      | 100     | Cut speed (mm/s)                       |
| `kerf`       | 0       | Kerf compensation (mm)                 |
| `z_offset`   | 0       | Initial Z offset (mm)                  |
| `z_per_pass` | 0       | Z step per pass (mm, typically ≤ 0)    |
| `num_passes` | 1       | Number of passes                       |

**`[geometry]`:**

| Key         | Default | Description                     |
| ----------- | ------- | ------------------------------- |
| `cell_size` | 15      | Square cell side length (mm)    |
| `gap`       | 8       | Gap between adjacent cells (mm) |

**`[annotations]`:**

| Key              | Default | Description                           |
| ---------------- | ------- | ------------------------------------- |
| `show_cell_text` | `false` | Print X and Y values inside each cell |

**`[border]`:**

| Key       | Default | Description                             |
| --------- | ------- | --------------------------------------- |
| `enabled` | `false` | Draw a border rectangle around the grid |
| `padding` | 3       | Padding outside the grid cells (mm)     |
| `power`   | 10      | Border layer power (%)                  |
| `speed`   | 200     | Border layer speed (mm/s)               |

**`[text_layer]`:**

| Key     | Default | Description                        |
| ------- | ------- | ---------------------------------- |
| `power` | 15      | Text/annotation layer power (%)    |
| `speed` | 200     | Text/annotation layer speed (mm/s) |

**`[font]`:**

| Key          | Default | Description                        |
| ------------ | ------- | ---------------------------------- |
| `name`       | `Arial` | Font family for all text           |
| `h_title`    | 10      | Title text height (mm)             |
| `h_subtitle` | 7       | Subtitle text height (mm)          |
| `h_label`    | 6       | Axis label text height (mm)        |
| `h_value`    | 5       | Axis value annotation height (mm)  |
| `h_cell`     | 4       | In-cell parameter text height (mm) |

## Layout Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│  Title: "6.08mm ply, Lauan"                                          │
│  Subtitle: "Z=−0.1, 15 mm/s, kerf 0.1 mm"                           │
│                                                                       │
│             12      13.5      15      16.5      18                   │
│                         Power [%]                                    │
│                                                                       │
│        ─0.5  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐     │
│              │ 12   │  │13.5  │  │  15  │  │16.5  │  │  18  │     │
│              │─0.5  │  │─0.5  │  │─0.5  │  │─0.5  │  │─0.5  │     │
│              └──────┘  └──────┘  └──────┘  └──────┘  └──────┘     │
│                                                                       │
│ Δ      ─0.6  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐     │
│ Z            │ ...  │  │ ...  │  │ ...  │  │ ...  │  │ ...  │     │
│ /            └──────┘  └──────┘  └──────┘  └──────┘  └──────┘     │
│ p                                                                     │
│ a      ─0.7  ┌──────┐  ...                                          │
│ s                                                                     │
│ s      ─0.8  ┌──────┐  ...                                          │
│                                                                       │
│  [optional border around grid]                                       │
└──────────────────────────────────────────────────────────────────────┘
```

## 3D / 4D Parameter Sweep (Grid of Grids)

For sweeping 3 or 4 parameters simultaneously, add optional `[cols]` and/or `[rows]` sections.
These define outer axes that produce a grid of sub-grids, where each sub-grid is a complete
2D grid (with its own inner axis annotations) at a specific combination of outer parameter values.

- **3-parameter sweep**: add `[cols]` alone (row of sub-grids) or `[rows]` alone (column of sub-grids)
- **4-parameter sweep**: add both `[cols]` and `[rows]` (grid of sub-grids)
- All axis params (`x`, `y`, `cols`, `rows`) must be distinct

### TOML config additions

**`[cols]` and `[rows]`** — outer axis configuration (same format as `[x]`/`[y]`):

| Key                | Default | Description                                                      |
| ------------------ | ------- | ---------------------------------------------------------------- |
| `param`            | —       | Parameter to scan across outer columns/rows                      |
| `values`           | —       | List of values for the outer sweep                               |
| `label`            | auto    | Outer axis label; omit to auto-generate from param name and unit |
| `show_annotations` | `true`  | Show outer axis value labels and the axis label                  |

**`[geometry]` addition:**

| Key              | Default | Description                         |
| ---------------- | ------- | ----------------------------------- |
| `subgrid_gap_mm` | 20      | Gap between sub-grids in mm (3D/4D) |

### Layout

```
              Title
              Subtitle

              col_val=1        col_val=2        col_val=3
                         Passes [count]

              ┌─subgrid─┐     ┌─subgrid─┐     ┌─subgrid─┐
row_val=-0.3  │ inner    │     │ inner    │     │ inner    │
              │ 2D grid  │     │ 2D grid  │     │ 2D grid  │
              │ w/ annot │     │ w/ annot │     │ w/ annot │
              └──────────┘     └──────────┘     └──────────┘

              ┌─subgrid─┐     ┌─subgrid─┐     ┌─subgrid─┐
row_val=-0.5  │  ...     │     │  ...     │     │  ...     │
              └──────────┘     └──────────┘     └──────────┘

ΔZ/pass [mm]   (rotated 90° CCW)
```

- Single shared title/subtitle at top
- Each sub-grid has its own inner axis annotations (values + label)
- Outer column values appear above the sub-grid columns, with axis label below them
- Outer row values appear to the left (rotated 90° CCW), with axis label further left
- Auto-subtitle excludes all varied parameters (inner + outer)

### Layer structure (3D/4D)

| Layer index    | Content                                             |
| -------------- | --------------------------------------------------- |
| 0              | All text (title, labels, values, in-cell text)      |
| 1 … T          | One cut layer per cell, sequential across sub-grids |
| T+1 (optional) | Border rectangle layer                              |

Cells are numbered sequentially: outer_row × outer_col × inner_row × inner_col.

### Example (3-parameter TOML)

```toml
[x]
param = "power_max_pct"
values = [12, 15, 18]

[y]
param = "z_per_pass_mm"
values = [-0.5, -0.6, -0.7]

[cols]
param = "num_passes"
values = [1, 2, 3]

[geometry]
subgrid_gap_mm = 20
```

See `example_config_3d.toml` for a complete annotated example.

## Future Work

- **Engrave mode** (Fill/Scan): expose `interval` (line interval mm) and `crosshatch` (bool).
  Show only engrave-relevant params in auto-subtitle.
