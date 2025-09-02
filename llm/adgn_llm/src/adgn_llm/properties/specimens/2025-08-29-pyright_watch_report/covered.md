## [Modern type hints](../../definitions/python/type-hints.md)

(lines 30, 36, 90, 192, 198, 211): Uses legacy `typing` aliases (`List`/`Dict`/`Set`/`Tuple`).
Should use modern built‑in generics (`list`/`dict`/`set`/`tuple`) and using `collections.abc` for protocols like `Iterable`, to keep types concise and idiomatic.

## [Self-describing names](../../definitions/self-describing-names.md)

(lines 121, 137, 143, 151):

Progress interval is encoded as a magic float literal `1.0` (seconds) in multiple places, which makes the unit implicit.
The property requires that units be self‑describing; define an explicit constant with a duration type (e.g., `PROGRESS_INTERVAL = timedelta(seconds=1)`) and compare using datetime consistently (e.g., `last_print: datetime`, `now = datetime.now(timezone.utc)`, and `if now - last_print >= PROGRESS_INTERVAL:`).

Self-describing progress interval (avoid 1.0 magic number):

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

## [Truthfulness](../../definitions/truthfulness.md)
- Output labeling: attribution mode is first-match-wins but not stated; logs/docs should explicitly state the chosen mode to avoid ambiguity.

### Extension list is misleading and duplicated

Printed list is hard-coded `.py/.pyi/.pyx` which does not match `CODE_EXTS` (set to `{'.py', '.pyi'}`).

```python
print(f"  of which code (.py/.pyi/.pyx): {total_code}")
```

Derive from one source of truth - `CODE_EXTS` - instead:

```python
print(f"  of which code ({'/'.join(sorted(CODE_EXTS))}): {total_code}")
```

### `dump_path` type annotation overstates optionality:

```python
dump_path: Path | None = Path(args.dump).resolve() if args.dump else (root / "scratch/pyright_watched_files.txt")
```

The expression always yields a `Path`. Annotate as `Path` (not `Path | None`).

## [No one-off vars and trivial wrappers](../../definitions/no-oneoff-vars-and-trivial-wrappers.md)

### Inline trivial temporaries

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
