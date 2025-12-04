local I = import '../lib.libsonnet';

// iss-054: Make poll() use peek(), inline _build_resources if called once

I.issue(
  snapshot='ducktape/2025-11-26-00',
  rationale=|||
    Lines 62-72 define `poll()` and `peek()` which both call `_build_resources()`.
    These should be refactored to avoid duplication.

    **Current:**
    ```python
    def poll(self) -> NotificationsBatch:
        """Poll and clear buffered notifications, returning grouped batch."""
        resources = self._build_resources()
        self._updates.clear()
        self._list_changed.clear()
        return NotificationsBatch(resources=resources)

    def peek(self) -> NotificationsBatch:
        """Peek at buffered notifications without clearing them."""
        resources = self._build_resources()
        return NotificationsBatch(resources=resources)
    ```

    **Problem:** `_build_resources()` is called in both methods.

    **Fix:**
    ```python
    def peek(self) -> NotificationsBatch:
        """Peek at buffered notifications without clearing them."""
        return NotificationsBatch(resources=self._build_resources())

    def poll(self) -> NotificationsBatch:
        """Poll and clear buffered notifications, returning grouped batch."""
        batch = self.peek()
        self._updates.clear()
        self._list_changed.clear()
        return batch
    ```

    **Then check:** If `_build_resources()` is now called only once (in peek()), inline it.

    **Benefits:**
    1. DRY - batch creation logic in one place
    2. `poll()` clearly shows it's `peek()` + clear
    3. Fewer calls to track
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/notifications/buffer.py': [
      [62, 72],  // poll() and peek() both call _build_resources()
    ],
  },
)
