"""PDF rendering utilities shared across extraction and eval."""

import hashlib
import subprocess
from pathlib import Path

from more_itertools import one

DEFAULT_DPI = 300


def file_hash(path: Path) -> str:
    """MD5 hash of file contents."""
    return hashlib.md5(path.read_bytes()).hexdigest()


def render_pdf_page(pdf_path: Path, page: int, tmpdir: Path, dpi: int = DEFAULT_DPI) -> Path:
    """Render a single page of a PDF to PNG via pdftoppm.

    Returns path to the rendered PNG.
    Raises RuntimeError if no PNG is produced.
    """
    prefix = tmpdir / "page"
    subprocess.run(
        ["pdftoppm", "-png", "-r", str(dpi), "-f", str(page), "-l", str(page), str(pdf_path), str(prefix)],
        check=True,
        capture_output=True,
    )
    return one(tmpdir.glob("page-*.png"))
