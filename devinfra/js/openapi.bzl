"""Macro: js_openapi_schema — generate TypeScript types from an OpenAPI-emitting binary."""

load("@aspect_rules_js//js:defs.bzl", "js_library", "js_run_binary")
load("@npm_ducktape//:openapi-typescript/package_json.bzl", openapi_ts_bin = "bin")

def js_openapi_schema(name, generator, out = "api/schema.d.ts", visibility = None):
    """Generate a js_library with TypeScript type definitions from an OpenAPI schema.

    Runs *generator* (a binary that prints an OpenAPI JSON schema to stdout),
    then pipes the result through openapi-typescript to produce a ``.d.ts``
    file, and wraps that in a ``js_library`` target.

    Private intermediate targets are prefixed with ``_<name>_`` to avoid
    collisions when the macro is called more than once in a package.

    Args:
        name:       Name of the output ``js_library`` target.
        generator:  Label of the executable that writes OpenAPI JSON to stdout.
        out:        Package-relative path for the generated ``.d.ts`` file.
                    Defaults to ``api/schema.d.ts``.
        visibility: Visibility of the output ``js_library``.

    Example:
        js_openapi_schema(
            name = "schema",
            generator = "//my/backend:export_schema_bin",
        )
    """
    json_out = "_" + name + "_openapi.json"

    openapi_ts_bin.openapi_typescript_binary(
        name = "_" + name + "_openapi_ts_bin",
    )

    native.genrule(
        name = "_" + name + "_openapi_json",
        outs = [json_out],
        cmd = "$(location {}) > $@".format(generator),
        tools = [generator],
    )

    js_run_binary(
        name = "_" + name + "_generate",
        srcs = [":_" + name + "_openapi_json"],
        outs = [out],
        args = [
            json_out,
            "-o",
            out,
        ],
        chdir = native.package_name(),
        tool = ":_" + name + "_openapi_ts_bin",
    )

    js_library(
        name = name,
        srcs = [":_" + name + "_generate"],
        tags = ["no-lint"],
        visibility = visibility,
    )
