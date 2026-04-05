"""Golden-file comparators for FreeCAD export formats (DXF, SVG, PDF).

Each comparator normalizes non-deterministic content before comparison:
- DXF: strips version strings, timestamps, and comment lines
- SVG: sorts XML attributes (Qt emits them in non-deterministic order)
- PDF: strips non-deterministic metadata via pypdf before byte comparison
"""

import difflib
import io
import re
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image
from pypdf import PdfReader, PdfWriter

# --- DXF ---

_DXF_STRIP_PATTERNS = re.compile(r"^\$TD(CREATE|UPDATE)|^\$VERSIONSTRING$")
_DXF_FLOAT_RE = re.compile(r"^[- ]?\d*\.?\d+([eE][+-]?\d+)?$")


def _normalize_dxf_value(line: str) -> str:
    """Normalize floating-point values: snap near-zero to 0, round to 6 decimals."""
    stripped = line.strip()
    if not _DXF_FLOAT_RE.match(stripped):
        return line
    try:
        val = float(stripped)
    except ValueError:
        return line
    if abs(val) < 1e-9:
        val = 0.0
    # Round to 6 significant decimals to absorb FP drift across runs
    normalized = f"{val:.6f}".rstrip("0").rstrip(".")
    # Preserve original line ending
    ending = line[len(line.rstrip()) :]
    return normalized + ending


def _normalize_dxf(text: str) -> list[str]:
    """Strip non-deterministic lines and normalize floats in DXF text."""
    lines = text.splitlines(keepends=True)
    result = []
    skip_next = False
    for line in lines:
        if skip_next:
            skip_next = False
            continue
        stripped = line.rstrip("\n").strip()
        # DXF group code 999 = comment, or header vars that change between runs.
        # These are key-value pairs: skip this line (key) and the next (value).
        if stripped == "999" or _DXF_STRIP_PATTERNS.match(stripped):
            skip_next = True
            continue
        result.append(_normalize_dxf_value(line))
    return result


def assert_dxf_equal(actual_path: Path, golden_path: Path) -> None:
    """Assert two DXF files match after normalizing non-deterministic fields."""
    actual = _normalize_dxf(actual_path.read_text())
    golden = _normalize_dxf(golden_path.read_text())
    if actual != golden:
        diff = "".join(difflib.unified_diff(golden, actual, fromfile="golden", tofile="actual", n=3))
        raise AssertionError(f"DXF mismatch:\n{diff[:500]}")


# --- SVG ---


def _normalize_svg_element(elem: ElementTree.Element) -> None:
    """Recursively sort attributes for stable comparison."""
    attribs = sorted(elem.attrib.items())
    elem.attrib.clear()
    for k, v in attribs:
        elem.attrib[k] = v
    for child in elem:
        _normalize_svg_element(child)


def _normalize_svg(text: str) -> str:
    """Parse SVG XML and re-serialize with sorted attributes for stable comparison."""
    root = ElementTree.fromstring(text)
    _normalize_svg_element(root)
    ElementTree.indent(root)
    return ElementTree.tostring(root, encoding="unicode", xml_declaration=True) + "\n"


def assert_svg_equal(actual_path: Path, golden_path: Path) -> None:
    """Assert two SVG files match after normalizing XML attribute order."""
    actual = _normalize_svg(actual_path.read_text())
    golden = _normalize_svg(golden_path.read_text())
    if actual != golden:
        diff = "".join(
            difflib.unified_diff(
                golden.splitlines(keepends=True),
                actual.splitlines(keepends=True),
                fromfile="golden",
                tofile="actual",
                n=3,
            )
        )
        raise AssertionError(f"SVG mismatch:\n{diff[:500]}")


# --- PDF ---


# Font names in embedded PDFs are non-deterministic: subset prefix varies (e.g., QNAAAA+)
# and the font itself may differ across workers (DejaVuSans vs osifont).
_FONT_NAME_RE = re.compile(rb"/FontName /[A-Z]{6}\+\S+")
_FONT_NAME_REPLACEMENT = b"/FontName /AAAAAA+NormalizedFont"


def _strip_pdf_metadata(pdf_path: Path) -> bytes:
    """Re-serialize a PDF with all non-deterministic metadata stripped via pypdf."""
    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    # Strip document-level metadata (CreationDate, ModDate, Producer, UUIDs, etc.)
    writer.add_metadata({"/Producer": "", "/Creator": "", "/CreationDate": "", "/ModDate": ""})
    # Remove XMP metadata stream entirely
    if "/Metadata" in writer._root_object:
        del writer._root_object["/Metadata"]
    buf = io.BytesIO()
    writer.write(buf)
    # Normalize non-deterministic font subset prefixes in the raw bytes
    return _FONT_NAME_RE.sub(_FONT_NAME_REPLACEMENT, buf.getvalue())


def assert_pdf_equal(actual_path: Path, golden_path: Path) -> None:
    """Assert two PDF files match after stripping non-deterministic metadata."""
    actual = _strip_pdf_metadata(actual_path)
    golden = _strip_pdf_metadata(golden_path)
    if actual == golden:
        return
    if len(actual) != len(golden):
        raise AssertionError(f"PDF size mismatch: golden={len(golden)} actual={len(actual)}")
    for i, (a, g) in enumerate(zip(actual, golden, strict=False)):
        if a != g:
            context = actual[max(0, i - 20) : i + 20]
            raise AssertionError(f"PDF differs at byte {i}: golden=0x{g:02x} actual=0x{a:02x}, context: {context!r}")


# --- PNG ---


def assert_png_equal(actual_path: Path, golden_path: Path, max_diff_fraction: float = 0.02) -> None:
    """Assert two PNG images match within a pixel channel diff tolerance."""
    actual = Image.open(actual_path).convert("RGB")
    golden = Image.open(golden_path).convert("RGB")
    if actual.size != golden.size:
        raise AssertionError(f"Size mismatch: {actual.size} vs {golden.size}")
    a_data = actual.tobytes()
    g_data = golden.tobytes()
    differing = sum(1 for a, g in zip(a_data, g_data, strict=True) if a != g)
    diff_fraction = differing / len(a_data)
    if diff_fraction > max_diff_fraction:
        raise AssertionError(
            f"Rendered PNG differs from golden by {diff_fraction:.1%} (threshold {max_diff_fraction:.1%})"
        )
