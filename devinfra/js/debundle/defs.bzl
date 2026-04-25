load("@aspect_rules_js//js:defs.bzl", "js_binary")

def js_debundle_transform_binary(name, data = [], fixed_args = [], no_copy_to_bin = [], node_options = [], **kwargs):
    runtime_deps = [Label("//devinfra/js/debundle/transforms:libs")] + data
    passthrough_files = runtime_deps + [Label("//devinfra/js/debundle/transforms:run_transform_entry_point")] + no_copy_to_bin
    js_binary(
        name = name,
        data = runtime_deps,
        entry_point = Label("//devinfra/js/debundle/transforms:run_transform_entry_point"),
        fixed_args = fixed_args,
        no_copy_to_bin = passthrough_files,
        node_options = ["--max-old-space-size=8192"] + node_options,
        **kwargs
    )

def js_debundle_live_proxy_binary(name, data = [], fixed_args = [], no_copy_to_bin = [], **kwargs):
    runtime_deps = [Label("//devinfra/js/debundle/live_proxy:libs")] + data
    passthrough_files = runtime_deps + [Label("//devinfra/js/debundle/live_proxy:serve_live_proxy_entry_point")] + no_copy_to_bin
    js_binary(
        name = name,
        data = runtime_deps,
        entry_point = Label("//devinfra/js/debundle/live_proxy:serve_live_proxy_entry_point"),
        fixed_args = fixed_args,
        no_copy_to_bin = passthrough_files,
        **kwargs
    )
