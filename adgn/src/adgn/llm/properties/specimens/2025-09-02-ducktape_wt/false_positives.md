## false positive / edit

- Broad try/except around whole body of handlers catching RuntimeError:
  - `wt/wt/client/handlers.py`: 85–99, 106–129, 138–185, 198–233, 286–336
  - flagged as violation of “Try/except is scoped around the operation it guards”:
  - actually mostly OK (it's an error boundary), but would be better to have a shared wrapper, e.g. a decorator

### shlex.quote does not accept PathLike

A critique claimed **wt/wt/client/worktree_utils.py** line 98 as a violation of “Pass Path objects to PathLike APIs” because it casts `Path` to `str` before passing to `shlex.quote`.
However, `shlex.quote` does not work with `PosixPath`:

```python
>>> shlex.quote(Path("foo"))
Traceback (most recent call last):
...
TypeError: expected string or bytes-like object, got 'PosixPath'
```

### Declared dependencies are present (false positive)

A critique claimed undeclared dependencies on:
- colorama, tabulate, pydantic, yaml (PyYAML), platformdirs, psutil, pygit2, github (PyGithub), pluggy, watchdog

Rationale:
- wt/pyproject.toml declares these runtime dependencies. The claim is incorrect.

Subject code pointers:
- wt/pyproject.toml (project dependency declarations)

### Simple go-links are fine (false positive)

A critique claimed manual URL construction via f-strings and recommended urllib.parse helpers:
- wt/wt/client/view_formatter.py:114, 179, 300

Rationale:
- These are internal convenience go-links of the form `http://go/pull/{number}` with `number: int`. There’s nothing to escape or parse; using urllib.parse here would add verbosity without additional safety or validation. At most one could assert the integer type, but constructing via URL helpers does not improve correctness.

Subject code pointers:
- wt/wt/client/view_formatter.py (see construction at the lines above)

