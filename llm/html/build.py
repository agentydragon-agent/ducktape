#!/usr/bin/env python3
import pathlib
import sys
from pathlib import Path

import markdown


def md2html(src: pathlib.Path, dst: pathlib.Path):
    html = markdown.markdown(src.read_text(), extensions=["tables", "fenced_code"])
    dst.write_text(html)


def main():
    path = Path("index.md")
    md2html(path, path.with_suffix(".html"))


if __name__ == "__main__":
    sys.exit(main())
