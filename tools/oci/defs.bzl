"""Shared OCI image helpers."""

def dedup_python_tar(name, src, **kwargs):
    """Post-process a pkg_tar to replace duplicate python binaries with symlinks.

    The rules_python hermetic toolchain ships bin/python, bin/python3, and
    bin/python3.X as three identical ~108 MB copies. This rule rewrites the
    tar so python and python3 become symlinks, saving ~216 MB per image.

    Args:
        name: Output target name (produces a .tar file).
        src: Input pkg_tar target to process.
        **kwargs: Passed to native.genrule (e.g. visibility).
    """
    native.genrule(
        name = name,
        srcs = [src],
        outs = [name + ".tar"],
        cmd = "$(execpath //tools/oci:dedup_python_bin) $< $@",
        tools = ["//tools/oci:dedup_python_bin"],
        **kwargs
    )
