local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    TUI image loader uses context.Background() for HTTP fetches and provides no cancellation/timeout, preventing UI-driven aborts and risking hangs on slow endpoints.

    Evidence
    - internal/tui/components/image/load.go: http.NewRequestWithContext(context.Background(), ...); http.DefaultClient.Do(req)
    - No cancel func is retained; subsequent redraws/URL updates cannot abort an in-flight fetch.

    Why it matters
    - In a terminal UI, image previews should be best-effort and abortable when the user navigates or resizes.
    - Lack of timeout means slow/misbehaving servers can stall the load path until transport-level timeouts, degrading UX.

    Acceptance criteria
    - Derive a bounded context (e.g., context.WithTimeout of 3–5s) for the GET.
    - Retain a cancel func in the image.Model and invoke it on Redraw/UpdateURL to abort prior fetches.
    - Ensure resp.Body is always closed; handle cancellation errors gracefully.
  |||,
  filesToRanges={
    'internal/tui/components/image/load.go': [[31, 39], [54, 66]],
    'internal/tui/components/image/image.go': [[38, 45], [58, 76]],
  },
  expect_caught_from=[['internal/tui/components/image/load.go'], ['internal/tui/components/image/image.go']],
)
