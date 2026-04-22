"""Macros for packaging skills for deployment."""

load("@bazel_skylib//lib:paths.bzl", "paths")
load("@rules_pkg//pkg:mappings.bzl", "pkg_files", "strip_prefix")
load("@rules_pkg//pkg:tar.bzl", "pkg_tar")
load("//devinfra/python:defs.bzl", "py_test")

_FRONTMATTER_TEST_LIB = "//skills:skill_frontmatter_test_lib"

def skill_mapping(srcs, prefix = "", preserve_paths = False):
    return struct(
        srcs = srcs,
        prefix = prefix,
        preserve_paths = preserve_paths,
    )

def skill_package(name, srcs = None, contents = None, visibility = None):
    """Package a skill's deployable files (excludes BUILD, evals, etc.).

    Args:
        name: Skill name / package_dir.
        srcs: Simple same-package file list. Preserves relative paths within the package.
        contents: Optional list of skill_mapping(...) entries for prefixed or cross-package files.
        visibility: Visibility override.
    """
    if srcs == None and contents == None:
        fail("skill_package requires either srcs or contents in {}".format(name))
    if srcs != None and contents != None:
        fail("skill_package accepts either srcs or contents, not both, in {}".format(name))

    entries = contents if contents != None else [skill_mapping(srcs = srcs, preserve_paths = True)]
    packaged_targets = []
    public_srcs = []
    seen_destinations = {}

    for entry_idx, entry in enumerate(entries):
        for src in entry.srcs:
            public_srcs.append(src)
            if entry.preserve_paths and (src.startswith("//") or ":" in src):
                fail("skill_package preserve_paths=True only supports same-package files: {}".format(src))

            if entry.preserve_paths:
                destination = src
            else:
                basename = paths.basename(src.split(":")[-1])
                destination = "{}/{}".format(entry.prefix, basename) if entry.prefix else basename

            if destination in seen_destinations:
                fail("skill_package would package duplicate destination '{}' from '{}' and '{}'".format(
                    destination,
                    seen_destinations[destination],
                    src,
                ))
            seen_destinations[destination] = src

        pkg_name = "{}_pkg_{}".format(name, entry_idx)
        pkg_files(
            name = pkg_name,
            srcs = entry.srcs,
            prefix = entry.prefix if entry.prefix else None,
            strip_prefix = strip_prefix.from_pkg() if entry.preserve_paths else strip_prefix.files_only(),
        )
        packaged_targets.append(":" + pkg_name)

    pkg_tar(
        name = name + "_tar",
        srcs = packaged_targets,
        package_dir = name,
        visibility = visibility or ["//visibility:public"],
    )
    py_test(
        name = name + "_frontmatter_test",
        main_module = "skills.skill_frontmatter_test",
        data = [":" + name + "_tar"],
        deps = [_FRONTMATTER_TEST_LIB],
        env = {
            "SKILL_TAR": "$(location :{})".format(name + "_tar"),
        },
        visibility = visibility or ["//visibility:public"],
    )
    native.filegroup(
        name = name,
        srcs = public_srcs,
        visibility = visibility or ["//visibility:public"],
    )
