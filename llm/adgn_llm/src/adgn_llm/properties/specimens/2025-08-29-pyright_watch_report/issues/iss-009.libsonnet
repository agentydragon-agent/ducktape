local obj = {
  id: "iss-009",
  should_flag: true,
  rationale: 'Inline trivial temporaries and trivial wrappers. Avoid assigning a value to a variable if the only thing you do with it is immediately pass it on. If it does not hurt readability, just immediately inline the value where it gets used.',
  properties: ['no-oneoff-vars-and-trivial-wrappers'],
  instances: [
    { files: { "pyright_watch_report.py": [ { start_line: 272, end_line: 279 } ] }, note: |||
  Per-include stats (kept):

  ```python
  incl_stats: list[tuple[str, int]] = sorted(
      ((pat, per_include_kept.get(pat, 0)) for pat in include),
      key=lambda x: x[1],
      reverse=True,
  )
  for pat, cnt in incl_stats:
      print(f"  {pat:40s} {cnt:8d}")
  ```

  Better: save yourself a temp var and iterate sorted(...) directly in the for:

  ```python
  for pat, cnt in sorted(
      ((pat, per_include_kept.get(pat, 0)) for pat in include),
      key=lambda x: x[1],
      reverse=True,
  ):
      print(f"  {pat:40s} {cnt:8d}")
  ```
|||,
},
    { files: { "pyright_watch_report.py": [ { start_line: 135, end_line: 139 } ] }, note: |||
  Top excludes:

  ```python
  exclude_impact: List[Tuple[str, int]] = sorted(exclude_hits.items(), key=lambda x: x[1], reverse=True)
  for pat, cnt in exclude_impact[:20]:
      print(f"  {pat:40s} -{cnt:7d}")
  ```

  Better: inline sorted slice at use site:

  ```
  for pat, cnt in exclude_impact[:20]:
      print(f"  {pat:40s} -{cnt:7d}")
  ```
|||,
},
    { files: { "pyright_watch_report.py": [ { start_line: 151, end_line: 158 } ] }, note: |||
  Total watched files:

  ```python
  total_files = len(kept_union)
  print(f"Total watched files (approx): {total_files}")
  ```

  Better:
  ```
  print(f"Total watched files (approx): {len(kept_union)}")
  ```
|||,
},
    { files: { "pyright_watch_report.py": [] }, note: |||
  Inline one-off total_code variable:

  ```python
  total_code = sum(1 for p in kept_union if p.suffix in CODE_EXTS)
  print(f"  of which code ({'/'.join(sorted(CODE_EXTS))}): {total_code}")
  ```

  Better:

  ```
  print(f"  of which code ({'/'.join(sorted(CODE_EXTS))}): {sum(p.suffix in CODE_EXTS for p in kept_union)}")
  ```
|||,
},
    { files: { "pyright_watch_report.py": [ { start_line: 228, end_line: 231 } ] }, note: |||
  `dp = Path(dirpath)`:

  ```python
  for dirpath, dirnames, filenames in os.walk(root):
      dp = Path(dirpath)
      for fn in filenames:
          p = dp / fn
  ```

  Better:

  ```python
  for dirpath, dirnames, filenames in os.walk(root):
      for fn in filenames:
          p = Path(dirpath) / fn
  ```
|||,
},
    { files: { "pyright_watch_report.py": [ { start_line: 246, end_line: 251 } ] }, note: |||
  ```python
  Redundant temp var `matched_any_excl`:

  ```python3
  hits = [pat for pat in exclude if matches_any(rp, [pat])]
  exclude_hits.update(hits)
  matched_any_excl = bool(hits)
  ...
  if matched_any_excl:
      progress_log(f"scan dirs={scanned_dirs} files={scanned_files} kept={len(kept_union)} at {rp}")
      continue
  ```

  Better: inline the condition:

  ```python3
  hits = [pat for pat in exclude if matches_any(rp, [pat])]
  exclude_hits.update(hits)
  ...
  if hits:  # same truthiness, fewer moving parts
      progress_log(f"scan dirs={scanned_dirs} files={scanned_files} kept={len(kept_union)} at {rp}")
      continue
  ```
|||,
},
    { files: { "pyright_watch_report.py": [ { start_line: 253, end_line: 256 } ] }, note: |||
  Periodic progress logging (extracted repeated block):

  ```python
  if progress and time.monotonic() - last_print >= 1.0:
      sys.stderr.write(
          f"scan dirs={scanned_dirs} files={scanned_files} kept={len(kept_union)} at {rp}\n",
      )
      sys.stderr.flush()
      last_print = time.monotonic()
  ```
|||,
}
  ],
};

obj
