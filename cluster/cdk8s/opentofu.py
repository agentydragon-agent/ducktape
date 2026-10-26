"""Inline OpenTofu roots from native HCL files shipped as Bazel runfiles."""

from util.bazel.runfiles import get_required_path, own_repo_rlocation


def inline_module(directory: str) -> str:
    """Combine an ordinary HCL root; the consumer declares its *.tf files as data.

    This does not package local modules, auxiliary files, JSON, or override semantics.
    """
    sources = sorted(get_required_path(own_repo_rlocation(directory)).glob("*.tf"))
    if not sources:
        raise ValueError(f"No Terraform source files in {directory}")
    return "\n".join(source.read_text() for source in sources)
