# Material Test Grid Generator

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

## Usage

```
bazel run //laser/material_test -- config.toml [-o output.lbrn2]
```

All parameters are supplied via a TOML configuration file. The output path defaults to the
config filename with `.lbrn2` extension. See <example_config.toml> for a fully annotated
example with all available options and their defaults.

## Supported Cut Parameters

Parameters that can be varied on X or Y axes, or held constant:

| Parameter       | Description                      | Unit |
| --------------- | -------------------------------- | ---- |
| `power_pct`     | Min and max power (set together) | %    |
| `power_min_pct` | Minimum power only               | %    |
| `power_max_pct` | Maximum power only               | %    |
| `speed_mm_s`    | Cut speed                        | mm/s |
| `kerf_mm`       | Kerf compensation offset         | mm   |
| `z_offset_mm`   | Z offset at start of layer       | mm   |
| `z_per_pass_mm` | Z step per pass (typically ≤ 0)  | mm   |
| `num_passes`    | Number of passes                 | —    |

## Layout

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

For sweeping 3 or 4 parameters simultaneously, add optional `[cols]` and/or `[rows]` sections
to the config. These define outer axes that produce a grid of sub-grids, where each sub-grid is
a complete 2D grid at a specific combination of outer parameter values.

- **3-parameter sweep**: add `[cols]` alone (row of sub-grids) or `[rows]` alone (column of sub-grids)
- **4-parameter sweep**: add both `[cols]` and `[rows]` (grid of sub-grids)
- All axis params (`x`, `y`, `cols`, `rows`) must be distinct

```
              Title
              Subtitle

              col_val=1        col_val=2        col_val=3
                         Passes [count]

              ┌─subgrid─┐     ┌─subgrid─┐     ┌─subgrid─┐
row_val=-0.3  │ inner    │     │ inner    │     │ inner    │
              │ 2D grid  │     │ 2D grid  │     │ 2D grid  │
              │ w/ labels│     │ w/ labels│     │ w/ labels│
              └──────────┘     └──────────┘     └──────────┘

              ┌─subgrid─┐     ┌─subgrid─┐     ┌─subgrid─┐
row_val=-0.5  │  ...     │     │  ...     │     │  ...     │
              └──────────┘     └──────────┘     └──────────┘

ΔZ/pass [mm]   (rotated 90° CCW)
```

See <example_config_3d.toml> for a complete annotated example.
