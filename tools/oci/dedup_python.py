"""Replace duplicate python/python3 binaries with symlinks to python3.X in a tar.

The rules_python hermetic toolchain ships bin/python, bin/python3, and
bin/python3.X as three identical ~108 MB files. This script rewrites a tar
so that python and python3 become symlinks to python3.X, saving ~216 MB
per runfiles tree.
"""

from __future__ import annotations

import argparse
import re
import tarfile


def _rewrite(src: str, dst: str) -> None:
    with tarfile.open(src, "r") as inp, tarfile.open(dst, "w") as out:
        for member in inp.getmembers():
            name = member.name
            basename = name.split("/")[-1]

            # Match bin/python or bin/python3 (but not python3.X or python3-config)
            if (
                "/bin/" in name
                and basename in ("python", "python3")
                and "rules_python++python+" in name
                and member.size > 1_000_000
            ):
                # Find the version-specific binary name (python3.13, python3.14, etc.)
                # by looking at sibling entries we've already seen, or just construct it
                # from the toolchain path which contains the version.
                version = _extract_version(name)
                if version:
                    symlink = tarfile.TarInfo(name=name)
                    symlink.type = tarfile.SYMTYPE
                    symlink.linkname = f"python{version}"
                    symlink.uid = member.uid
                    symlink.gid = member.gid
                    symlink.mtime = member.mtime
                    out.addfile(symlink)
                    continue

            # Pass through everything else unchanged
            if member.isreg():
                out.addfile(member, inp.extractfile(member))
            else:
                out.addfile(member)


_VERSION_RE = re.compile(r"python_(\d+)_(\d+)_")


def _extract_version(path: str) -> str | None:
    """Extract Python major.minor from a rules_python toolchain path.

    Paths look like:
      .../rules_python++python+python_3_13_x86_64-unknown-linux-gnu/bin/python
    """
    m = _VERSION_RE.search(path)
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Input tar file")
    parser.add_argument("output", help="Output tar file")
    args = parser.parse_args()
    _rewrite(args.input, args.output)


if __name__ == "__main__":
    main()
