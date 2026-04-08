# legacy_create_init Investigation

## Summary

Commit `7265f7ccb` added `legacy_create_init = 0` to the global `py_test` macro
in `devinfra/testing/defs.bzl`. This broke 4 tests. Reverting fixes them.

## Root Cause: How Stubs Prevent Stdlib Shadowing

With `legacy_create_init = 1` (default), the runfiles manifest includes empty
`__init__.py` stubs for every directory:

```
_main/x/__init__.py                    (empty stub)
_main/x/claude_linter_v2/__init__.py   (empty stub)
_main/x/claude_linter_v2/types.py      (real source file)
_main/util/__init__.py                 (empty stub)
_main/util/bazel/__init__.py           (empty stub)
_main/util/bazel/subprocess.py         (real source file)
```

With `legacy_create_init = 0`, ALL the empty stubs disappear. Only real
`__init__.py` files from pip packages remain.

**Why stubs matter**: When `_main` is on `sys.path`:

- **With stubs**: `x/claude_linter_v2/` has `__init__.py` → it's a package.
  `import types` resolves to stdlib because `types.py` is only reachable as
  `x.claude_linter_v2.types` (a submodule of a package).
- **Without stubs**: `x/claude_linter_v2/` has no `__init__.py` → it's a bare
  directory. Python's import machinery can find `types.py` in it when the
  directory appears on `sys.path` (via PYTHONPATH propagation to subprocesses).

## Global Flag vs Per-Target Attribute

- `--@rules_python//python/config_settings:incompatible_default_to_explicit_init_py=True`
  → tests PASS
- `legacy_create_init = 0` on `py_test` → tests FAIL

**Why different?** `legacy_create_init` only exists on `py_binary`/`py_test` (not
`py_library`). Both settings should be equivalent for the test binary itself.
The global flag was tested only briefly — needs more verification. It may have
been a false positive (cached results).

## The FreeCAD Problem

FreeCAD's conda env has C extensions (`Part.so`) and package dirs (`Mod/Part/`).
Auto-generated `__init__.py` stubs in `Mod/Part/` shadow the C extensions:

- **With stubs**: `import Part` → finds empty `Mod/Part/__init__.py` → broken
- **Without stubs**: `import Part` → finds `lib/Part.so` → works

Only ~7 test targets in `skills/freecad/` need `legacy_create_init = 0`.

## Options

### Option 1: Per-target `legacy_create_init = 0` on FreeCAD tests only

Apply `legacy_create_init = 0` only to the ~7 FreeCAD test targets.
Everyone else keeps the default (stubs enabled).

**Pro**: Minimal blast radius, fixes FreeCAD without breaking anything.
**Con**: Each new FreeCAD test needs to remember to set this.

### Option 2: Global flag + fix subprocess PYTHONPATH propagation

Set `--incompatible_default_to_explicit_init_py` globally in `.bazelrc`.
Fix `util/bazel/subprocess.py` `python_env()` to filter PYTHONPATH to
prevent stdlib shadowing in child processes.

**Pro**: Moves toward the recommended rules_python direction.
**Con**: Risky, needs careful PYTHONPATH filtering, may have other fallout.

### Option 3: Fix FreeCAD's conda import issue differently

Use a conftest fixture or wrapper that reloads C extensions after import
(like the old `_fix_freecad_stub_modules()` approach from `9b924c2f6`).

**Pro**: No build system changes needed.
**Con**: Fragile, band-aid.

## Current Status

- Macro reverted to NOT set `legacy_create_init`
- FreeCAD tests need `legacy_create_init = 0` applied per-target
- All 4 previously broken tests pass again
