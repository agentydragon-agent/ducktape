"""Material test grid generator for LightBurn (.lbrn2).

Reads a TOML configuration file that describes the grid parameters, then
generates a parametric material test grid as a .lbrn2 file.

Usage:
    python material_test.py config.toml [-o output.lbrn2]

See SPEC.md for full documentation and example_config.toml for a complete
annotated example configuration.
"""

from __future__ import annotations

import argparse
import tomllib
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator

from lightburn.lbrn2_writer import (
    AnyShape,
    CutMode,
    CutSetting,
    HAlign,
    LightBurnProject,
    RectShape,
    TextShape,
    VAlign,
    XForm,
)

# ── Cut parameter enum ─────────────────────────────────────────────────────────


class CutParam(StrEnum):
    """Named laser cut parameters that can be scanned or held constant."""

    POWER_PCT = "power_pct"  # sets both min_power and max_power simultaneously
    POWER_MIN_PCT = "power_min_pct"
    POWER_MAX_PCT = "power_max_pct"
    SPEED_MM_S = "speed_mm_s"
    KERF_MM = "kerf_mm"
    Z_OFFSET_MM = "z_offset_mm"
    Z_PER_PASS_MM = "z_per_pass_mm"
    NUM_PASSES = "num_passes"


_PARAM: dict[CutParam, tuple[str, str, bool]] = {
    # (label, unit, abbreviate_in_subtitle) — when abbreviate_in_subtitle is
    # True, the subtitle omits the label and just prints "value unit".
    CutParam.POWER_PCT: ("Power", "%", False),
    CutParam.POWER_MIN_PCT: ("Power min", "%", False),
    CutParam.POWER_MAX_PCT: ("Power max", "%", False),
    CutParam.SPEED_MM_S: ("Speed", "mm/s", True),
    CutParam.KERF_MM: ("Kerf", "mm", False),
    CutParam.Z_OFFSET_MM: ("Z", "mm", False),
    CutParam.Z_PER_PASS_MM: ("Z/pass", "mm", False),
    CutParam.NUM_PASSES: ("Passes", "", False),
}


def fmt_val(v: float) -> str:
    """Format a parameter value for human display (no trailing zeros)."""
    if v == int(v):
        return str(int(v))
    return f"{v:.4g}"


# ── Pydantic config models ─────────────────────────────────────────────────────


class AxisConfig(BaseModel):
    """Configuration for one grid axis (X or Y)."""

    model_config = ConfigDict(extra="forbid")

    param: CutParam
    values: list[float]
    label: str | None = None  # None = auto-generate from param name + unit; "" = no label
    show_annotations: bool = True


class CutConfig(BaseModel):
    """Laser cut parameters held constant across the entire grid.

    The x/y axis parameters override their respective entries here for each cell.

    Use 'power_pct' to set both power_min_pct and power_max_pct simultaneously.
    """

    model_config = ConfigDict(extra="forbid")

    power_pct: float | None = None  # shorthand: sets both power_min_pct and power_max_pct
    power_min_pct: float = 80.0
    power_max_pct: float = 80.0
    speed_mm_s: float = 100.0
    kerf_mm: float = 0.0
    z_offset_mm: float = 0.0
    z_per_pass_mm: float = 0.0  # Z step per pass (negative = deeper)
    num_passes: int = 1

    @model_validator(mode="after")
    def apply_power_shorthand(self) -> CutConfig:
        if self.power_pct is not None:
            self.power_min_pct = self.power_pct
            self.power_max_pct = self.power_pct
        return self

    def to_cut_setting(self, index: int, name: str) -> CutSetting:
        return CutSetting(
            index=index,
            name=name,
            min_power=self.power_min_pct,
            max_power=self.power_max_pct,
            speed=self.speed_mm_s,
            kerf=self.kerf_mm,
            z_offset=self.z_offset_mm,
            z_per_pass=self.z_per_pass_mm,
            num_passes=self.num_passes,
        )


class GeometryConfig(BaseModel):
    """Physical dimensions of the test grid cells."""

    model_config = ConfigDict(extra="forbid")

    cell_size_mm: float = 15.0  # square side length
    gap_mm: float = 8.0  # gap between adjacent cells


class AnnotationConfig(BaseModel):
    """In-cell text annotations."""

    model_config = ConfigDict(extra="forbid")

    show_cell_text: bool = False  # print param values inside each cell
    cell_text_gap_mm: float = 0.3  # vertical gap between the two in-cell text lines


class BorderConfig(BaseModel):
    """Optional border rectangle drawn around the entire grid."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    padding_mm: float = 3.0  # outside the grid cells
    power_pct: float = 10.0
    speed_mm_s: float = 200.0


class TextLayerConfig(BaseModel):
    """Cut settings for the annotation text layer (layer 0)."""

    model_config = ConfigDict(extra="forbid")

    power_pct: float = 15.0
    speed_mm_s: float = 200.0


class FontConfig(BaseModel):
    """Font and text size configuration."""

    model_config = ConfigDict(extra="forbid")

    name: str = "Arial"
    h_title_mm: float = 10.0  # title text height
    h_subtitle_mm: float = 7.0
    h_label_mm: float = 6.0  # axis label
    h_value_mm: float = 5.0  # axis value annotations
    h_cell_mm: float = 4.0  # in-cell parameter text


class GridConfig(BaseModel):
    """Root configuration for the material test grid.

    Corresponds to a single TOML config file.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = ""
    subtitle: str = ""  # extra text prepended to the auto-generated subtitle
    auto_subtitle: bool = True  # append constant-param summary to subtitle

    x: AxisConfig
    y: AxisConfig
    cut: CutConfig = CutConfig()
    geometry: GeometryConfig = GeometryConfig()
    annotations: AnnotationConfig = AnnotationConfig()
    border: BorderConfig = BorderConfig()
    text_layer: TextLayerConfig = TextLayerConfig()
    font: FontConfig = FontConfig()

    @model_validator(mode="after")
    def validate_axes(self) -> GridConfig:
        if self.x.param == self.y.param:
            raise ValueError(f"x.param and y.param must be different; both are {self.x.param!r}")
        return self


# ── Parameter helpers ──────────────────────────────────────────────────────────


def _apply_param(cut: CutSetting, param: CutParam, value: float) -> None:
    """Apply a named parameter value to a CutSetting."""
    if param == CutParam.POWER_PCT:
        cut.min_power = value
        cut.max_power = value
    elif param == CutParam.POWER_MIN_PCT:
        cut.min_power = value
    elif param == CutParam.POWER_MAX_PCT:
        cut.max_power = value
    elif param == CutParam.SPEED_MM_S:
        cut.speed = value
    elif param == CutParam.KERF_MM:
        cut.kerf = value
    elif param == CutParam.Z_OFFSET_MM:
        cut.z_offset = value
    elif param == CutParam.Z_PER_PASS_MM:
        cut.z_per_pass = value
    elif param == CutParam.NUM_PASSES:
        cut.num_passes = round(value)


def _get_param(cut: CutSetting, param: CutParam) -> float:
    """Read a named parameter value from a CutSetting."""
    if param in (CutParam.POWER_PCT, CutParam.POWER_MAX_PCT):
        return cut.max_power
    if param == CutParam.POWER_MIN_PCT:
        return cut.min_power
    if param == CutParam.SPEED_MM_S:
        return cut.speed
    if param == CutParam.KERF_MM:
        return cut.kerf
    if param == CutParam.Z_OFFSET_MM:
        return cut.z_offset
    if param == CutParam.Z_PER_PASS_MM:
        return cut.z_per_pass
    if param == CutParam.NUM_PASSES:
        return float(cut.num_passes)
    raise ValueError(f"Unknown param: {param!r}")  # unreachable with enum


def _auto_subtitle(config: GridConfig) -> str:
    """Build a subtitle listing the parameters constant across all cells."""
    varied: set[CutParam] = {config.x.param, config.y.param}
    if CutParam.POWER_PCT in varied:
        varied |= {CutParam.POWER_MIN_PCT, CutParam.POWER_MAX_PCT}
    if CutParam.POWER_MIN_PCT in varied or CutParam.POWER_MAX_PCT in varied:
        varied.add(CutParam.POWER_PCT)

    base = config.cut.to_cut_setting(0, "")
    parts: list[str] = []
    for param in [
        CutParam.Z_OFFSET_MM,
        CutParam.SPEED_MM_S,
        CutParam.KERF_MM,
        CutParam.Z_PER_PASS_MM,
        CutParam.NUM_PASSES,
        CutParam.POWER_PCT,
    ]:
        if param in varied:
            continue
        v = _get_param(base, param)
        if param == CutParam.NUM_PASSES and v == 1:
            continue
        label, unit, abbrev = _PARAM[param]
        if abbrev and unit:
            parts.append(f"{fmt_val(v)} {unit}")
        else:
            parts.append(f"{label}={fmt_val(v)}{' ' + unit if unit else ''}")
    return ", ".join(parts)


def _full_subtitle(config: GridConfig) -> str:
    pieces: list[str] = []
    if config.subtitle:
        pieces.append(config.subtitle)
    if config.auto_subtitle:
        auto = _auto_subtitle(config)
        if auto:
            pieces.append(auto)
    return ", ".join(pieces)


def _auto_label(param: CutParam) -> str:
    """Build an axis label from a CutParam (e.g. POWER_MAX_PCT → 'Power max [%]')."""
    label, unit, _abbrev = _PARAM[param]
    return f"{label} [{unit}]" if unit else label


# ── Layout constants ───────────────────────────────────────────────────────────

_SPACING = 3.0  # mm between text elements
_MARGIN_LEFT = 5.0  # mm left of the Y-axis label
_MARGIN_TOP = 5.0  # mm above the title
_TEXT_LAYER = 0  # layer index reserved for annotation text


def _estimate_text_width(text: str, height: float) -> float:
    """Rough rendered text width estimate (approx 0.55 x height per char)."""
    return len(text) * height * 0.55


# ── Grid generation ────────────────────────────────────────────────────────────


def generate(config: GridConfig) -> LightBurnProject:
    """Build a LightBurnProject from the grid configuration."""
    n_cols = len(config.x.values)
    n_rows = len(config.y.values)
    stride = config.geometry.cell_size_mm + config.geometry.gap_mm
    font = config.font

    cut_settings: list[CutSetting] = []
    shapes: list[AnyShape] = []

    # Layer 0: annotation text
    cut_settings.append(
        CutSetting(
            index=_TEXT_LAYER,
            name="Text",
            mode=CutMode.CUT,
            min_power=config.text_layer.power_pct,
            max_power=config.text_layer.power_pct,
            speed=config.text_layer.speed_mm_s,
        )
    )

    # Layers 1..N*M: one per grid cell
    cell_cut_index: dict[tuple[int, int], int] = {}
    next_index = 1
    for row_i, y_val in enumerate(config.y.values):
        for col_j, x_val in enumerate(config.x.values):
            cut = config.cut.to_cut_setting(next_index, f"C{next_index:02d}")
            _apply_param(cut, config.x.param, x_val)
            _apply_param(cut, config.y.param, y_val)
            cut_settings.append(cut)
            cell_cut_index[(row_i, col_j)] = next_index
            next_index += 1

    # Optional border layer
    border_layer_index: int | None = None
    if config.border.enabled:
        cut_settings.append(
            CutSetting(
                index=next_index,
                name="Border",
                mode=CutMode.CUT,
                min_power=config.border.power_pct,
                max_power=config.border.power_pct,
                speed=config.border.speed_mm_s,
            )
        )
        border_layer_index = next_index
        next_index += 1

    # ── Horizontal layout ─────────────────────────────────────────────────────
    # Both Y-axis label and value annotations are rotated 90° CCW, so their
    # horizontal footprint is their font height.
    x = _MARGIN_LEFT
    if config.y.show_annotations:
        x_y_label_cx = x + font.h_label_mm / 2.0
        x += font.h_label_mm + _SPACING
        x_y_val_cx = x + font.h_value_mm / 2.0
        x += font.h_value_mm + _SPACING
    else:
        x_y_label_cx = _MARGIN_LEFT
        x_y_val_cx = _MARGIN_LEFT
    x_grid_left = x

    x_col = [x_grid_left + config.geometry.cell_size_mm / 2.0 + col_j * stride for col_j in range(n_cols)]
    x_grid_right = x_grid_left + n_cols * stride - config.geometry.gap_mm
    x_grid_centre = (x_grid_left + x_grid_right) / 2.0

    # ── Vertical layout (Y increases upward — LightBurn CNC convention) ────────

    def add_text(
        text: str,
        x: float,
        y_pos: float,
        height: float,
        ah: HAlign = HAlign.LEFT,
        av: VAlign = VAlign.TOP,
        rotate90ccw: bool = False,
    ) -> None:
        xform = XForm.rotate90ccw(x, y_pos) if rotate90ccw else XForm.translate(x, y_pos)
        shapes.append(
            TextShape(cut_index=_TEXT_LAYER, text=text, height=height, xform=xform, font=font.name, ah=ah, av=av)
        )

    subtitle_text = _full_subtitle(config)
    x_label = config.x.label if config.x.label is not None else _auto_label(config.x.param)
    y_label = config.y.label if config.y.label is not None else _auto_label(config.y.param)

    # Pre-compute total content height so we can start from the top.
    grid_height = n_rows * stride - config.geometry.gap_mm
    v_total = 0.0
    if config.title:
        v_total += font.h_title_mm + _SPACING
    if subtitle_text:
        v_total += font.h_subtitle_mm + _SPACING
    v_total += grid_height
    if config.x.show_annotations:
        v_total += _SPACING + font.h_value_mm
        if x_label:
            v_total += _SPACING + font.h_label_mm

    # y starts at the top (large Y) and decreases as we place elements downward.
    y = v_total + _MARGIN_TOP

    content_left = 0.0  # border padding adds its own offset
    content_right = x_grid_right
    content_top = y  # highest Y

    if config.title:
        add_text(config.title, x_grid_centre, y, font.h_title_mm, ah=HAlign.CENTER)
        title_half_w = _estimate_text_width(config.title, font.h_title_mm) / 2.0
        content_right = max(content_right, x_grid_centre + title_half_w)
        y -= font.h_title_mm + _SPACING

    if subtitle_text:
        add_text(subtitle_text, x_grid_centre, y, font.h_subtitle_mm, ah=HAlign.CENTER)
        sub_half_w = _estimate_text_width(subtitle_text, font.h_subtitle_mm) / 2.0
        content_right = max(content_right, x_grid_centre + sub_half_w)
        y -= font.h_subtitle_mm + _SPACING

    # Grid: rows go downward from y.
    y_grid_top = y
    y_row = [y_grid_top - config.geometry.cell_size_mm / 2.0 - row_i * stride for row_i in range(n_rows)]
    y_grid_bottom = y_grid_top - grid_height
    y_grid_centre = (y_grid_top + y_grid_bottom) / 2.0

    # X-axis annotations below the grid: tick values, then label.
    y_below = y_grid_bottom - _SPACING
    if config.x.show_annotations:
        for col_j, x_val in enumerate(config.x.values):
            add_text(fmt_val(x_val), x_col[col_j], y_below, font.h_value_mm, ah=HAlign.CENTER, av=VAlign.TOP)
        y_below -= font.h_value_mm + _SPACING

        if x_label:
            add_text(x_label, x_grid_centre, y_below, font.h_label_mm, ah=HAlign.CENTER)
            y_below -= font.h_label_mm

    content_bottom = y_below if config.x.show_annotations else y_grid_bottom

    # Y-axis label (rotated 90° CCW, reads bottom-to-top)
    if config.y.show_annotations and y_label:
        add_text(
            y_label, x_y_label_cx, y_grid_centre, font.h_label_mm, ah=HAlign.CENTER, av=VAlign.CENTER, rotate90ccw=True
        )

    # Y-axis value annotations (rotated 90° CCW like the axis label, centred on each row)
    if config.y.show_annotations:
        for row_i, y_val in enumerate(config.y.values):
            add_text(
                fmt_val(y_val),
                x_y_val_cx,
                y_row[row_i],
                font.h_value_mm,
                ah=HAlign.CENTER,
                av=VAlign.CENTER,
                rotate90ccw=True,
            )

    # Grid cells
    for row_i, y_val in enumerate(config.y.values):
        for col_j, x_val in enumerate(config.x.values):
            cut_idx = cell_cut_index[(row_i, col_j)]
            cx = x_col[col_j]
            cy = y_row[row_i]

            shapes.append(
                RectShape(
                    cut_index=cut_idx,
                    width=config.geometry.cell_size_mm,
                    height=config.geometry.cell_size_mm,
                    xform=XForm.translate(cx, cy),
                )
            )

            if config.annotations.show_cell_text:
                half_gap = config.annotations.cell_text_gap_mm / 2.0
                y_line1 = cy + half_gap + font.h_cell_mm / 2.0  # above centre
                y_line2 = cy - half_gap - font.h_cell_mm / 2.0  # below centre
                margin = font.h_cell_mm * 0.2
                half_cell = config.geometry.cell_size_mm / 2.0
                y_line1 = min(cy + half_cell - margin - font.h_cell_mm / 2.0, y_line1)
                y_line2 = max(cy - half_cell + margin + font.h_cell_mm / 2.0, y_line2)

                add_text(fmt_val(x_val), cx, y_line1, font.h_cell_mm, ah=HAlign.CENTER, av=VAlign.BOTTOM)
                add_text(fmt_val(y_val), cx, y_line2, font.h_cell_mm, ah=HAlign.CENTER, av=VAlign.TOP)

    # Optional border — encompasses all content (title, labels, grid), not just cells
    # TODO: border width estimate doesn't account for actual rendered text width
    # (we use a rough heuristic), so the border may not fully cover the subtitle.
    if config.border.enabled and border_layer_index is not None:
        p = config.border.padding_mm
        border_w = (content_right - content_left) + 2.0 * p
        border_h = (content_top - content_bottom) + 2.0 * p
        border_cx = (content_left + content_right) / 2.0
        border_cy = (content_top + content_bottom) / 2.0
        shapes.append(
            RectShape(
                cut_index=border_layer_index,
                width=border_w,
                height=border_h,
                xform=XForm.translate(border_cx, border_cy),
            )
        )

    notes = f"Generated by material_test.py  x={config.x.param}:{config.x.values}  y={config.y.param}:{config.y.values}"
    return LightBurnProject(cut_settings=cut_settings, shapes=shapes, notes=notes)


# ── CLI ────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "config", metavar="CONFIG.toml", help="Path to the TOML configuration file (see example_config.toml)"
    )
    p.add_argument(
        "-o",
        "--output",
        default=None,
        metavar="FILE",
        help="Output .lbrn2 file path (default: derived from config filename)",
    )
    args = p.parse_args(argv)

    with Path(args.config).open("rb") as f:
        data = tomllib.load(f)

    config = GridConfig.model_validate(data)

    output_path = args.output
    if output_path is None:
        output_path = str(Path(args.config).with_suffix(".lbrn2"))

    project = generate(config)

    with Path(output_path).open("w", encoding="utf-8") as f:
        f.write(project.to_xml_str())

    n_cells = len(config.x.values) * len(config.y.values)
    print(f"Written {output_path}  ({len(config.x.values)} cols x {len(config.y.values)} rows = {n_cells} cells)")


if __name__ == "__main__":
    main()
