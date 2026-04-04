@README.md

## Skill authoring

Follow the `verify-docs` skill when writing or reviewing documentation and skills. Invoke `/verify-docs` to audit.

## Example scripts and testing

Skills that include example scripts (referenced from `SKILL.md`) should package them into the skill tarball via `skill_package(srcs=...)`. Tests that verify these examples actually work live alongside but outside the skill package as `testonly` targets.

Pattern:

- `SKILL.md` references example scripts (e.g., `parametric_rect.py`)
- `skill_package(srcs=[...])` includes `SKILL.md` + all example scripts
- `py_test` / `sh_test` targets run the examples and compare outputs against committed golden files
- Golden files live in `golden/` subdirectory
- Test helpers (comparators, fixtures) are `testonly = True` and not part of the skill package

Example (`skills/freecad/`):

- Skill package: `SKILL.md`, `parametric_rect.py`, `export_dxf.py`, etc.
- Test: `test_parametric_rect.py` runs `parametric_rect.py` in a FreeCAD Docker container, compares DXF output against `golden/rect.dxf`
- Test helper: `compare_dxf.py` (`testonly`) strips non-deterministic headers before diffing
