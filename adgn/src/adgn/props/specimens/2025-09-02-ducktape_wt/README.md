# Specimen: ducktape/wt (behavior snapshot)

## Findings to propagate

### DaemonClient APIs and Paths

A critique claimed **wt/wt/client/worktree_utils.py** line 120 as a violation of “Pass Path objects to PathLike APIs” because it casts `Path` to `str` before passing to `DaemonClient.identify_worktree`.

That is not the correct way to state the finding. `identify_worktree` as written in specimen takes `str`, not `Path`.

The correct finding would have been that `identify_worktree` itself should be updated to *take `Path` instead of `str`* - plus *then* with that change it should be called with `Path` without any cast to `str`.

TODO: this is *both* a false positive, *and* a critique that should be present

## To resolve whether true/false finding

**wt/wt/shared/logging_config.py**
- Dynamic attribute access for level resolution (violates “Forbid dynamic attribute access and catching AttributeError”): 98

This is questionable.
It's a "given str, give me corresponding log level value". Without `getattr`, the next option
to do this would be a dict, but that would be also ugly.
TODO - to read mode and think about alternatives.
