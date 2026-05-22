from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast


def default_packages_root() -> Path:
    for runfiles_dir in [os.environ.get("RUNFILES_DIR"), os.environ.get("TEST_SRCDIR")]:
        if not runfiles_dir:
            continue
        for candidate in [Path(runfiles_dir) / "_main" / "node_modules", Path(runfiles_dir) / "node_modules"]:
            if candidate.exists():
                return candidate
    raise RuntimeError("Could not locate Bazel-provided package tree; pass packages_root explicitly")


def read_installed_package_metadata(
    package_name: str,
    *,
    package_root: Path | None = None,
    package_roots: dict[str, Path] | None = None,
    packages_root: Path | None = None,
) -> dict:
    resolved_package_root = package_root or resolve_package_root(
        package_name, package_roots=package_roots, packages_root=packages_root
    )
    metadata_path = resolved_package_root / "package.json"
    if not metadata_path.exists():
        raise RuntimeError(f"Package metadata missing for {package_name}: {metadata_path}")
    return cast(dict[str, Any], json.loads(metadata_path.read_text(encoding="utf-8")))


def resolve_package_root(
    package_name: str, *, package_roots: dict[str, Path] | None = None, packages_root: Path | None = None
) -> Path:
    mapped_root = package_roots.get(package_name) if package_roots else None
    if mapped_root is not None:
        resolved_package_root = mapped_root.resolve()
        if not resolved_package_root.exists():
            raise RuntimeError(f"Package root not found for {package_name}: {resolved_package_root}")
        return resolved_package_root
    if package_roots and packages_root is None:
        raise RuntimeError(f"Package root not provided for {package_name}")

    resolved_packages_root = (packages_root or default_packages_root()).resolve()
    package_root = resolved_packages_root.joinpath(*package_path_segments(package_name)).resolve()
    assert_path_within_root(package_root, resolved_packages_root, f"Package {package_name} escapes packages root")
    if not package_root.exists():
        raise RuntimeError(f"Package root not found for {package_name}: {package_root}")
    return package_root


def resolve_package_subpath(
    package_name: str,
    subpath: str,
    *,
    package_root: Path | None = None,
    package_roots: dict[str, Path] | None = None,
    packages_root: Path | None = None,
) -> Path:
    resolved_package_root = package_root or resolve_package_root(
        package_name, package_roots=package_roots, packages_root=packages_root
    )
    file_path = (resolved_package_root / subpath).resolve()
    assert_path_within_root(
        file_path, resolved_package_root, f"Package {package_name} subpath escapes package root: {subpath}"
    )
    if not file_path.exists():
        raise RuntimeError(f"Package file not found for {package_name}: {subpath} -> {file_path}")
    assert_real_path_within_root(
        file_path, resolved_package_root, f"Package {package_name} subpath realpath escapes package root: {subpath}"
    )
    return file_path


def assert_real_path_within_root(path: Path, root: Path, message: str) -> Path:
    real_path = path.resolve()
    real_root = root.resolve()
    assert_path_within_root(real_path, real_root, message)
    return real_path


def assert_path_within_root(path: Path, root: Path, message: str) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError(f"{message}: {path}") from exc


def package_path_segments(package_name: str) -> list[str]:
    if not isinstance(package_name, str) or package_name == "":
        raise RuntimeError(f"Invalid package name: {package_name}")
    segments = package_name.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise RuntimeError(f"Invalid package name: {package_name}")
    return segments
