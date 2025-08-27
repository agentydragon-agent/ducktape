# Conversion candidates from adgn_instructions (prioritized)

Criteria
- Prefer rules that are precise, objective, and easy to check; avoid wiggly/nuanced ones for now.

1) forbid-dynamic-attrs
- Rule: Do not use getattr/hasattr/setattr; do not catch AttributeError.
- Source: general/code/python.md

2) use-pathlib
- Rule: Use pathlib for path manipulation; do not use os.path.* in new/edited code.
- Source: general/code/python.md

3) str-removeprefix-removesuffix
- Rule: Use str.removeprefix/str.removesuffix instead of slicing for prefix/suffix removal.
- Source: general/code/python.md

4) logging-no-exception-duplication
- Rule: Don’t embed exception text into logger.error/exception messages; rely on exc_info.
- Source: general/code/python.md

5) tests-pytest-layout
- Rule: Tests live in test_*.py files co-located with the code; no __main__ test harnesses.
- Source: general/code/python.md

6) hamcrest-single-item
- Rule: For single-element matching use has_item, not has_items.
- Source: general/code/python.md

7) avoid-broad-except
- Rule: Do not catch broad Exception; catch specific, expected exceptions only.
- Source: general/code/defensive.md

8) avoid-one-off-vars
- Rule: Avoid one-off variables used exactly once just to forward into the next call; inline when readable.
- Source: general/code/no_oneoff_vars.md

9) typing-self-reference
- Rule: Use typing.Self (or future annotations) for self-referential returns; do not use string class names.
- Source: general/code/python.md

Deprioritized for later (more nuanced)
- aggressive-dry (principle-level)
- early-bailout (style heuristic)
- document-current-state (judgment-heavy)
- refactor-tools-libcst-semgrep (process/behavioral)
- proper-serde-libs (better as decomposed sub-rules per format)
- self-describing-units (naming/typing judgment)
- ascii-art-prefer-generated (harder to detect reliably)
- rg-over-grep (tooling/process, not code outcome)

---

Converted (done)
- [x] imports-at-top — `properties/imports-at-top.md`
- [x] markdown-inline-formatting — `properties/markdown-inline-formatting.md`
- [x] use-walrus-trivial-conditions — `properties/use-walrus-for-trivial-conditions.md`
- [x] no-unnecessary-line-breaks — `properties/no-unnecessary-line-breaks.md`
- [x] no-useless-docs — `properties/no-useless-docs.md`
- [x] forbid-dynamic-attrs — `properties/forbid-dynamic-attrs.md`
- [x] modern-type-hints — `properties/modern-type-hints.md`
- [x] avoid-one-off-vars — `properties/no-oneoff-vars-and-trivial-wrappers.md`