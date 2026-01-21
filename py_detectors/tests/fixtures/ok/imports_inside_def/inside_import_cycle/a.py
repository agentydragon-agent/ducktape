def f():
    from pkg.imports_inside_def.inside_import_cycle import b  # noqa: F401
