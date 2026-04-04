"""
Render a DXF file to PNG using ezdxf.

Usage: python3 render_dxf.py <input.dxf> <output.png> [--dpi 200]

Requires: ezdxf[draw] (which pulls in matplotlib + Pillow).
Uses the ezdxf CLI internally — it handles color inversion, viewport fitting,
and dimension rendering correctly.

TODO: dimension text renders as tofu (empty squares) because ezdxf can't find
fonts in the Bazel sandbox. Need to either bundle a font via data dep or point
ezdxf at matplotlib's bundled DejaVu fonts via EZDXF_FONT_PATH or similar.
"""

import argparse
import subprocess
import sys
from pathlib import Path


def render_dxf(input_path: Path, output_path: Path, *, dpi: int = 200) -> None:
    """Render a DXF file to a PNG image."""
    subprocess.run(
        [
            sys.executable,
            "-m",
            "ezdxf",
            "draw",
            "--background",
            "WHITE",
            "--dpi",
            str(dpi),
            "-f",
            "-o",
            output_path,
            input_path,
        ],
        check=True,
    )
    print(f"Rendered: {output_path} ({output_path.stat().st_size} bytes, {dpi} dpi)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Render DXF to PNG")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--dpi", type=int, default=200)
    args = parser.parse_args()
    render_dxf(args.input, args.output, dpi=args.dpi)


if __name__ == "__main__":
    main()
