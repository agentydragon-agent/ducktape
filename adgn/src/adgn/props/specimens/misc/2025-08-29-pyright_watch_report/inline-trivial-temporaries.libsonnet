local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Multiple trivial temporary variables should be inlined where they're used. Variables are
    assigned once and immediately passed on without additional logic, hurting readability.

    **Examples:**
    - Lines 272-279: `incl_stats` assigned from `sorted(...)`, used once in for loop — inline sorted() in the for statement
    - Lines 135-139: `exclude_impact` assigned sorted slice, used once — inline `sorted(...)[20]` in for
    - Lines 151-158: `total_files = len(kept_union)` used once in print — inline `len(kept_union)` in f-string
    - Lines 228-231: `dp = Path(dirpath)` used once as `dp / fn` — inline to `Path(dirpath) / fn`
    - Lines 246-251: `matched_any_excl = bool(hits)` used once in if — use `if hits:` directly

    **Fix:** Remove intermediate variables and inline expressions at their single use sites.
    This follows the principle: avoid assigning to a variable if the only thing you do with
    it is immediately pass it on.
  |||,
  filesToRanges={
    'pyright_watch_report.py': [
      [272, 279],  // incl_stats
      [135, 139],  // exclude_impact
      [151, 158],  // total_files
      // total_code (line not specified in original)
      [228, 231],  // dp = Path(dirpath)
      [246, 251],  // matched_any_excl
      [253, 256],  // Periodic progress logging
    ],
  },
)
