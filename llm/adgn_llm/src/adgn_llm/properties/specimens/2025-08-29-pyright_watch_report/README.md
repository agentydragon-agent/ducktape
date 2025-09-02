---
source:
  vcs: local
  root: .
scope:
  include:
    - pyright_watch_report.py
---

# pyright_watch_report.py specimen

## Context
- Snapshot date: 2025-08-29

## TODO (future properties to document and enforce)
- python/scoped-try-except.md: Broad try/except blocks; should scope to specific exceptions and smallest necessary block.
- High‑level property gap (planned): No footguns, clear/unambiguous outputs
  - Outputs should be clear, correct, and unsurprising to readers. When behavior depends on a mode (e.g., first‑match vs all‑matches), that mode must be explicitly surfaced in output/docs to avoid confusion, especially under overlapping patterns.
  - This specimen risks confusion by reporting per‑pattern counts without stating the attribution mode. Capture this under a future property (e.g., properties/no-footguns.md) to require unambiguous labeling and documentation of such choices.


## Freeform review items (specimen discovery)

### Violations of pre-existing properties

- python/type-hints.md (lines 30, 36, 90, 192, 198, 211): Uses legacy `typing` aliases (`List`/`Dict`/`Set`/`Tuple`).
  Should use modern built‑in generics (`list`/`dict`/`set`/`tuple`) and using `collections.abc` for protocols like `Iterable`, to keep types concise and idiomatic.
- self-describing-names.md (lines 121, 137, 143, 151):
  Progress interval is encoded as a magic float literal `1.0` (seconds) in multiple places, which makes the unit implicit.
  The property requires that units be self‑describing; define an explicit constant with a duration type (e.g., `PROGRESS_INTERVAL = timedelta(seconds=1)`) and compare using datetime consistently (e.g., `last_print: datetime`, `now = datetime.now(timezone.utc)`, and `if now - last_print >= PROGRESS_INTERVAL:`).

### Findings under known properties

- Truthfulness (../definitions/truthfulness.md)
  - Output labeling: attribution mode is first-match-wins but not stated; logs/docs should explicitly state the chosen mode to avoid ambiguity.
  - Label drift: printed extension list is hard-coded as `.py/.pyi/.pyx` while `CODE_EXTS == {'.py', '.pyi'}`; derive labels from constants.
  - Overstated optionality: `dump_path` is always a Path (never None) — annotation `Path | None` misleads; align name/docs/types with behavior.

### Feedback not mapped to pre-existing properties

#### Higher-level

##### Clarify accounting: first‑match vs all‑matches

- Overlapping patterns mean a file may match multiple include/exclude patterns. There are two valid attribution modes:
  - First‑match wins (config order): attribute a file to the first include pattern that matches. Useful for “unique additional” counts; order‑sensitive and easy to explain.
  - All‑matches: count a file under every pattern it matches. Useful for coverage/overlap analysis; order‑insensitive.
- In specimen, first‑match wins (order‑sensitive). All‑matches is a valid alternative; document the chosen mode to avoid confusion (which is a minor footgun).

##### Explicit `--config` must be authoritative (no fallback)

In `load_config`, specimen does:

```python
candidates: list[Path] = []
if config_path:
    candidates.append(config_path)  # <- from explicit commandline arg
# ... add other candidates ...
for cand in candidates:
  if cand.is_file():
      try:
          return cand, json.loads(cand.read_text())
      except Exception:
          pass
```

If user explicitly sets `--config` and it fails to load, this code silently skips it and moves on to other candidates, explicitly *and silently* violating user intent.

If explicitly provided `--config` is not present or fails to load, code must fail fast and surface the error.
Fallback discovery as in specimen would only be acceptable as "friendly default" with no explicit `--config` passed.

##### Compute include impacts during the scan (not post‑hoc)

Account include and exclude pattern hits symmetrically: accumulate include stats inside the main walk instead of reconstructing later.
This avoids a second pass and keeps ordering semantics obvious.

Specimen's post-hoc reconstruction of include hits from `kept_union`:

```python
per_include_kept: Dict[str, int] = {}
for pat in include:
  per_include_kept[pat] = sum(1 for p in kept_union if matches_any(rel(p, root), [pat]))
# and a separate loop to compute "unique additional" with a seen set
```

Better (gather hits during the scan):

```python
from collections import Counter
include_hits = Counter()                 # all includes that match a file
per_include_unique: dict[str, set[Path]] = {pat: set() for pat in include}
seen: set[Path] = set()
...
# Inside the os.walk loop, after rp = rel(p, root)
matches = [pat for pat in include if matches_any(rp, [pat])]
include_hits.update(matches)
# First-match wins for order-sensitive "unique additional" counting
for pat in matches:
  if p not in seen:
      per_include_unique[pat].add(p)
      seen.add(p)
  break
```

##### Normalize patterns in one place (original specimen)

Specimen has many scattered calls to `normalize_pattern`; internal variables are a mix of normalized/un-normalized patterns:

```python
# original (normalizes per call inside matcher)
def matches_any(path_rel: str, patterns: Iterable[str]) -> bool:
  return any(
      fnmatch.fnmatch(path_rel, normalize_pattern(p))
      or fnmatch.fnmatch("/" + path_rel, normalize_pattern(p))
      for p in patterns
  )
```

Avoid calling `normalize_pattern` in every match - this scatters the responsibility for "patterns should be normalized" all over the code.
Instead, pass input un-normalized patterns (both include/exclude) *exactly once* through a normalization boundary, and after it, consistently deal only with normalized patterns:

```python
# better (normalize once; matcher assumes normalized)
include = expand_include_patterns(include)  # returns normalized
exclude = [normalize_pattern(p) for p in exclude]
def matches_any(path_rel: str, patterns: Iterable[str]) -> bool:
  return any(
      fnmatch.fnmatch(path_rel, p) or fnmatch.fnmatch("/" + path_rel, p)
      for p in patterns
  )
```

Options for adding more clarity which code assumes normalized / un-normalized patterns:

* Document normalization requirements/contracts in docstrings/comments
* Name variables with hints like `normalized` prefix/suffix
* Use a marker type like `NormalizedPattern = NewType("NormalizedPattern", str)`

#### Lower-level

##### General themes

- Prefer equivalent formulations with fewer lines and less state when readability is equal or better.
  Patterns here include:
  - Comprehensions over imperative accumulation
  - Inlining throwaway temporaries
  - Deriving output from a single source of truth (constants)
  - Condensing trivial branches

##### Feedback

- Progress logging block repeats 4× (lines ~121, 137, 143, 151):

  ```python
  # pyright_watch_report.py, e.g. lines 120–125
  if progress and time.monotonic() - last_print >= 1.0:
      sys.stderr.write(f"scan dirs={scanned_dirs} files={scanned_files} kept={len(kept_union)} at {rp}\n")
      sys.stderr.flush()
      last_print = time.monotonic()
  ```

  Extract helper or small class to deduplicate.

- Final dump error handling catches Exception right before program end and turns a real failure (“stacktrace + non‑zero exit”) into a shorter message and exit 0.

  ```python
  # pyright_watch_report.py, lines 248–257
  try:
      with dump_path.open("w", encoding="utf-8") as f:
          for p in sorted(kept_union):
              f.write(str(p) + "\n")
      print(f"Dumped {len(kept_union)} files to {dump_path}")
  except Exception as e:
      print(f"WARN: failed to write dump file: {e}")
  ```
  
  This adds lines/indentation without value. Remove the try/except and let the failure propagate without explicit handling.

- `load_config` silently swallows read/parse errors across candidate configs (and skips to next candidate):

  ```python
  # pyright_watch_report.py, lines 46–51
  try:
      return cand, json.loads(cand.read_text())
  except Exception:
      pass
  ```

  Broken candidate files are unlikely and if they happen, they should be flagged to user.
  Do not catch exceptions here — let them propagate and crash instead of silently trying the next candidate.

- `dump_path` type annotation overstates optionality:

  ```python
  dump_path: Path | None = Path(args.dump).resolve() if args.dump else (root / "scratch/pyright_watched_files.txt")
  ```

  The expression always yields a `Path`. Annotate as `Path` (not `Path | None`).

- `per_include_kept` should be a dict comprehension (imperative build-up adds noise):

  ```python
  # pyright_watch_report.py (original)
  per_include_kept: Dict[str, int] = {}
  for pat in include:
      per_include_kept[pat] = sum(1 for p in kept_union if matches_any(rel(p, root), [pat]))
  # better:
  per_include_kept: dict[str, int] = {
      pat: sum(1 for p in kept_union if matches_any(rel(p, root), [pat]))
      for pat in include
  }
  ```

- `per_include_unique` nested accumulation should gather with comprehensions and keep state minimal.

  ```python
  # pyright_watch_report.py (original)
  seen: Set[Path] = set()
  per_include_unique: List[Tuple[str, int]] = []
  for pat in include:
      uniq_count = 0
      for p in sorted(kept_union):
          if p in seen:
              continue
          if matches_any(rel(p, root), [pat]):
              uniq_count += 1
              seen.add(p)
      per_include_unique.append((pat, uniq_count))
  ```

  Clearer formulation in a more functional style:

  ```python
  # 'seen' retained to avoid double-counting across overlaps
  per_include_unique: dict[str, set[Path]] = {}
  seen: set[Path] = set()
  for pat in include:
      paths = {p for p in sorted(kept_union) if p not in seen and matches_any(rel(p, root), [pat])}
      per_include_unique[pat] = paths
      seen.update(paths)
  ```

- Inline trivial temporaries:

  ```python
  # 1) Per-include kept counts
  incl_stats: List[Tuple[str, int]] = sorted(((pat, per_include_kept.get(pat, 0)) for pat in include), key=lambda x: x[1], reverse=True)
  for pat, cnt in incl_stats:
      print(f"  {pat:40s} {cnt:8d}")
  # better: inline sorted(...) in loop header

  # 2) Top excludes
  exclude_impact: List[Tuple[str, int]] = sorted(exclude_hits.items(), key=lambda x: x[1], reverse=True)
  for pat, cnt in exclude_impact[:20]:
      print(f"  {pat:40s} -{cnt:7d}")
  # better: inline sorted slice at use site

  # 3) Total wached files
  total_files = len(kept_union)
  print(f"Total watched files (approx): {total_files}")
  # better:
  print(f"Total watched files (approx): {len(kept_union)}")

  # 4) `dp = Path(dirpath)`:
  for dirpath, dirnames, filenames in os.walk(root):
      dp = Path(dirpath)
      for fn in filenames:
          p = dp / fn
  # better
  for dirpath, dirnames, filenames in os.walk(root):
      for fn in filenames:
          p = Path(dirpath) / fn

  # 5) Redundant temp var `matched_any_excl`:
  hits = [pat for pat in exclude if matches_any(rp, [pat])]
  exclude_hits.update(hits)
  matched_any_excl = bool(hits)
  ...
  if matched_any_excl:
      progress_log(f"scan dirs={scanned_dirs} files={scanned_files} kept={len(kept_union)} at {rp}")
      continue

  # better: inline the condition
  hits = [pat for pat in exclude if matches_any(rp, [pat])]
  exclude_hits.update(hits)
  ...
  if hits:  # same truthiness, fewer moving parts
      progress_log(f"scan dirs={scanned_dirs} files={scanned_files} kept={len(kept_union)} at {rp}")
      continue

  # 6) Inline one-off total_code variable:
  total_code = sum(1 for p in kept_union if p.suffix in CODE_EXTS)
  print(f"  of which code ({'/'.join(sorted(CODE_EXTS))}): {total_code}")
  # better:
  print(f"  of which code ({'/'.join(sorted(CODE_EXTS))}): {sum(1 for p in kept_union if p.suffix in CODE_EXTS)}")
  ```

- Use `Counter` for tallying exclude pattern hits:

  ```python
  # pyright_watch_report.py:
  exclude_hits: Dict[str, int] = {pat: 0 for pat in exclude}
  ...
  for pat in exclude:
      if matches_any(rp, [pat]):
          exclude_hits[pat] += 1

  # better (collections.Counter)
  from collections import Counter
  exclude_hits = Counter()
  ...
  exclude_hits.update(pat for pat in exclude if matches_any(rp, [pat]))
  ```

  `Counter` saves the initialization/default-to-zero and expresses intent.

- Extension list is misleading and duplicated. Printed list is hard-coded `.py/.pyi/.pyx` which does not match `CODE_EXTS` (set to `{'.py', '.pyi'}`).

  ```python
  print(f"  of which code (.py/.pyi/.pyx): {total_code}")
  ```

  Derive from one source of truth - `CODE_EXTS` - instead:

  ```python
  print(f"  of which code ({'/'.join(sorted(CODE_EXTS))}): {total_code}")
  ```

- Write equivalent logic with fewer lines/state when readability is equal or better (example here uses `Path.write_text`):

  ```python
  # pyright_watch_report.py:
  with dump_path.open("w", encoding="utf-8") as f:
      for p in sorted(kept_union):
          f.write(str(p) + "\n")
  # better:
  dump_path.write_text("\n".join(str(p) for p in sorted(kept_union)), encoding="utf-8")
  ```

- If running on Python ≥ 3.12, use `Path.walk`:

  ```python
  # Python 3.12+
  for dirpath, dirnames, filenames in Path(root).walk():
      ...
  ```

  For earlier Python versions, `os.walk` remains the portable choice.

- Condense config print:

  ```python
  # original
  if cfg_file:
      print(f"config: {cfg_file}")
  else:
      print("config: <not found, using defaults>")
  # better:
  print(f"config: {cfg_file or '<not found, using defaults>'}")
  ```

- Self-describing progress interval (avoid 1.0 magic number):

  ```python
  # original (multiple places)
  if progress and time.monotonic() - last_print >= 1.0:
      ...
      last_print = time.monotonic()

  # better (use datetime consistently for time arithmetic):
  from datetime import datetime, timedelta, timezone
  PROGRESS_INTERVAL = timedelta(seconds=1)
  last_print = datetime.now(timezone.utc)
  ...
  now = datetime.now(timezone.utc)
  if progress and (now - last_print) >= PROGRESS_INTERVAL:
      ...
      last_print = now
  # or extract a tiny helper to avoid repetition
  ```
