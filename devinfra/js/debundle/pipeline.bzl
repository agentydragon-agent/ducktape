"""Bazel-driven debundle pipeline rule.

Runs the ducktape debundler with `--out-root` pointing at a tree-artifact
output directory. All pipeline outputs (manifests, analysis, emitted JS) land
under the rule's declared output directory in `bazel-bin/`. Each corpus may
layer a `write_source_files` regen target on top to commit a subset of outputs
into the source tree.
"""

load("@bazel_skylib//lib:paths.bzl", "paths")
load("@bazel_skylib//lib:shell.bzl", "shell")

_TREE_SOURCE_PATH_FLAGS = {
    "--tree-ancillary-modules": True,
    "--tree-config": True,
    "--tree-modules": True,
    "--tree-vendor-marks": True,
}

def _debundle_pipeline_impl(ctx):
    out_dir = ctx.actions.declare_directory(ctx.label.name + ".out")
    bin_dir = ctx.bin_dir.path

    if ctx.file.spec and ctx.attr.spec_tree_args:
        fail("pass either spec or spec_tree_args, not both")
    if not ctx.file.spec and not ctx.attr.spec_tree_args:
        fail("one of spec or spec_tree_args is required")

    debundler_args = []
    if ctx.file.spec:
        debundler_args.extend(["--spec", ctx.file.spec.path])
    else:
        debundler_args.extend(ctx.attr.spec_tree_args)
        debundler_args.extend(["--out-root", out_dir.short_path])

    if ctx.attr.force:
        debundler_args.append("--force")

    for pkg_label, pkg_name in ctx.attr.package_roots.items():
        pkg_files = pkg_label[DefaultInfo].files.to_list()
        if not pkg_files:
            fail("package_roots entry {} has no files".format(pkg_name))

        # The `:dir` filegroup is a single tree artifact whose `.path`
        # already points directly at the package directory containing
        # `package.json`. Make it bin-dir-relative for the post-cd cwd.
        pkg_dir = paths.relativize(pkg_files[0].path, bin_dir)
        debundler_args.append("--package-root")
        debundler_args.append("{}={}".format(pkg_name, pkg_dir))

    inputs = depset(
        direct = [ctx.file.spec] if ctx.file.spec else [],
        transitive = [dep[DefaultInfo].files for dep in ctx.attr.spec_tree_inputs] +
                     [dep[DefaultInfo].files for dep in ctx.attr.input_data] +
                     [pkg[DefaultInfo].files for pkg in ctx.attr.package_roots.keys()],
    )

    ctx.actions.run_shell(
        inputs = inputs,
        tools = [ctx.executable.debundler],
        outputs = [out_dir],
        command = "cd \"${{BAZEL_BINDIR}}\" && exec \"${{OLDPWD}}/{debundler}\" {args}".format(
            debundler = ctx.executable.debundler.path,
            args = " ".join(_debundler_shell_args(debundler_args)),
        ),
        env = {"BAZEL_BINDIR": bin_dir},
        # The debundler asserts that each vendor package's resolved subpath
        # canonicalizes to a location within the package root. Inside
        # Bazel's linux-sandbox, package-dir entries are real directories
        # but their leaf files are symlinks to the host execroot's bazel-bin
        # — so `realpath(file)` lands outside `realpath(dir)` and the check
        # spuriously fails. Disable sandboxing for this action; inputs are
        # declared via Bazel attrs, so reproducibility is preserved.
        execution_requirements = {"no-sandbox": "1"},
        progress_message = "Running debundle pipeline for %{label}",
        mnemonic = "DebundlePipeline",
    )

    return [DefaultInfo(files = depset([out_dir]))]

def _debundler_shell_args(args):
    out = []
    execroot_path_next = False
    for arg in args:
        if execroot_path_next:
            out.append(_execroot_path_arg(arg))
            execroot_path_next = False
            continue
        out.append(shell.quote(arg))
        execroot_path_next = arg in _TREE_SOURCE_PATH_FLAGS
    return out

def _execroot_path_arg(path):
    if path.startswith("/"):
        return shell.quote(path)
    return "\"${{OLDPWD}}/{}\"".format(path)

debundle_pipeline = rule(
    implementation = _debundle_pipeline_impl,
    attrs = {
        "spec": attr.label(
            allow_single_file = True,
            doc = "Optional flat transform spec YAML. Mutually exclusive with spec_tree_args.",
        ),
        "spec_tree_args": attr.string_list(
            doc = "Tree-shaped authoring arguments passed to debundle before --out-root.",
        ),
        "spec_tree_inputs": attr.label_list(
            allow_files = True,
            doc = "Source-tree inputs the tree-shaped spec compiler reads.",
        ),
        "debundler": attr.label(
            executable = True,
            cfg = "exec",
            mandatory = True,
            doc = "Debundler binary; must accept flat transform spec or tree-shaped spec args.",
        ),
        "force": attr.bool(
            doc = "Pass --force to debundle so output-tree stages may replace existing directories.",
        ),
        "input_data": attr.label_list(
            allow_files = True,
            doc = "Source-tree inputs the spec references (extracted/, snapshots/).",
        ),
        "package_roots": attr.label_keyed_string_dict(
            allow_files = True,
            doc = "Vendor package roots: label of the package's `:dir` filegroup → package name. The first file's dirname is passed as `--package-root <name>=<dir>`.",
        ),
    },
)
