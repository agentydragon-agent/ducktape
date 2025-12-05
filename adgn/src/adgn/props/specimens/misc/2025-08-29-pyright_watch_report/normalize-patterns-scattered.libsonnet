local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Specimen has many scattered calls to `normalize_pattern`; internal variables are a mix of normalized/un-normalized patterns:

    Original (normalizes per call inside matcher):
    ```python
    def matches_any(path_rel: str, patterns: Iterable[str]) -> bool:
      return any(
          fnmatch.fnmatch(path_rel, normalize_pattern(p))
          or fnmatch.fnmatch("/" + path_rel, normalize_pattern(p))
          for p in patterns
      )
    ```

    Avoid calling `normalize_pattern` in every match - this scatters the responsibility for "patterns should be normalized" all over the code.
    Instead, pass input un-normalized patterns (both include/exclude) *exactly once* through a normalization boundary, and after it, consistently deal only with normalized patterns:

    Better (normalize once; matcher assumes normalized):
    ```python
    include = expand_include_patterns(include)  # returns normalized
    exclude = [normalize_pattern(p) for p in exclude]
    def matches_any(path_rel: str, patterns: Iterable[str]) -> bool:
      return any(
          fnmatch.fnmatch(path_rel, p) or fnmatch.fnmatch("/" + path_rel, p)
          for p in patterns
      )
    ```

    Supplemental: Options for adding more clarity which code assumes normalized / un-normalized patterns:
    * Document normalization requirements/contracts in docstrings/comments
    * Name variable hints, e.g. 'xyzzy_normalized` prefix/suffix
    * Marker type like `NormalizedPattern = NewType("NormalizedPattern", str)`
  |||,
  filesToRanges={
    'pyright_watch_report.py': [65, 70],
  },
)
