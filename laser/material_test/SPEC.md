# Material Test Grid — Implementation Specification

Internal specification for label positioning, layer structure, and geometry calculations.
See <README.md> for usage and <example_config.toml> for all config options.

## Grid Geometry

- Cell stride = `cell_size_mm + gap_mm`
- Grid is tight: no outer padding beyond the cell edges (border padding is separate)

## Text Labels

### X-axis labels (below the grid)

Per-column parameter values appear below each column, centered.
Below the values, the X-axis label appears (centered over all columns).

### Y-axis labels (left of the grid)

Per-row parameter values appear to the left of each row, right-aligned
and vertically centered on the row.

To the left of the values, the Y-axis label appears rotated 90° CCW (reading bottom-to-top),
centered vertically over the grid height.

### In-cell text (optional)

The X and Y parameter values for each cell are printed as two text lines
inside the cell (centered). Font size is configurable.

### Legend cell (optional)

When `show_legend` is enabled and `cell_text` is not `nothing`, a legend
square is drawn in the bottom-left corner (where the Y-axis label area
meets the X-axis label area). It uses the same two-line layout as in-cell
text but shows short parameter labels (e.g. "mm/s" and "Power %") instead of
values.

### Title and subtitle

Title line appears above the grid, subtitle below the title. The auto-generated
subtitle includes only parameters that are not being varied on any axis.

### Border (optional)

A border rectangle drawn around the entire grid using a separate cut setting,
padded a configurable amount outside the grid cells.

## LightBurn Layer Structure

| Layer index      | Content                                        |
| ---------------- | ---------------------------------------------- |
| 0                | All text (title, labels, values, in-cell text) |
| 1 … N×M          | One cut layer per grid cell (N cols × M rows)  |
| N×M+1 (optional) | Border rectangle layer                         |

Each grid cell gets its own `CutSetting` because the combination of X and Y parameter
values is unique per cell. Layer 0 uses a distinct, low-power cut setting for marking.

### Layer structure (3D/4D)

| Layer index    | Content                                             |
| -------------- | --------------------------------------------------- |
| 0              | All text (title, labels, values, in-cell text)      |
| 1 … T          | One cut layer per cell, sequential across sub-grids |
| T+1 (optional) | Border rectangle layer                              |

Cells are numbered sequentially: outer_row × outer_col × inner_row × inner_col.

## 3D/4D Layout Details

- Single shared title/subtitle at top
- Each sub-grid has its own inner axis labels (values + label)
- Outer column values appear above the sub-grid columns, with axis label below them
- Outer row values appear to the left (rotated 90° CCW), with axis label further left
- Auto-subtitle excludes all varied parameters (inner + outer)

## Future Work

- **Engrave mode** (Fill/Scan): expose `interval` (line interval mm) and `crosshatch` (bool).
  Show only engrave-relevant params in auto-subtitle.
