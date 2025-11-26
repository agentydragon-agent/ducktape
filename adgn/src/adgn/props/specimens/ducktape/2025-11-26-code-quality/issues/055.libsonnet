local I = import '../../specimens/lib.libsonnet';

// iss-055: Use mutable NotificationsBatch for accumulation instead of sets

I.issueOneOccurrence(
  rationale=|||
    The class uses sets (`_updates`, `_list_changed`) during accumulation, then converts
    to frozen structures in NotificationsBatch. This is clunky.

    **Current pattern:**
    ```python
    # Accumulation storage (mutable sets)
    self._updates: dict[str, set[str]] = {}
    self._list_changed: set[str] = set()

    # On add:
    self._updates[server_name].add(uri)
    self._list_changed.add(server_name)

    # On poll/peek:
    resources = self._build_resources()  # Converts sets to frozen structures
    return NotificationsBatch(resources=resources)
    ```

    **Problem:** Clunky conversion between mutable sets and immutable structures.

    **Better approach:** Use a mutable NotificationsBatch directly:
    ```python
    # Accumulation storage (mutable NotificationsBatch)
    self._batch: NotificationsBatch = NotificationsBatch()

    # On add:
    # ... mutate _batch directly ...

    # On poll:
    batch = self._batch.model_copy()  # Pydantic copy
    self._batch = NotificationsBatch()  # Reset
    return batch

    # On peek:
    return self._batch.model_copy()
    ```

    **Or even better:** Make NotificationsBatch have a `.copy()` method or use
    `.model_copy(deep=True)` if needed.

    **Benefits:**
    1. Simpler - one data structure instead of two representations
    2. No conversion logic needed
    3. More elegant and DRY
    4. Clearer what's being accumulated
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/notifications/buffer.py': [
      [40, 41],  // _updates and _list_changed - clunky accumulation
    ],
  },
)
