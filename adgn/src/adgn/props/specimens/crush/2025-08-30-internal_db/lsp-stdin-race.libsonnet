local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    LSP client performs unsynchronized concurrent writes to the server's stdin, risking interleaved headers/bodies and JSON‑RPC/LSP stream corruption.

    Evidence
    - WriteMessage writes header (fmt.Fprintf) then body (w.Write) with no locking.
    - Multiple goroutines call WriteMessage concurrently:
      - replying to server requests (WriteMessage(c.stdin, response))
      - sending requests (WriteMessage(c.stdin, msg))
      - sending notifications (WriteMessage(c.stdin, msg))

    Why it matters
    - Concurrent fmt.Fprintf + Write to the same pipe can interleave bytes across messages (e.g., header from A + body from B).
    - Results in parse errors, dropped/ misrouted responses, and hard‑to‑debug protocol failures.

    Context
    - In typical Crush usage a single agent instance may drive LSP interactions mostly sequentially, so the bug can be latent under light load. However, server‑initiated requests and concurrent notifications still overlap with client calls, and the code provides no serialization. Treat this as bad practice to be fixed regardless of current incidence.

    Acceptance criteria
    - Serialize all writes to c.stdin (e.g., add a write mutex on the client and guard all WriteMessage calls).
    - Optional: buffer compose the full frame into a single []byte and write once under the mutex.
    - Add a stress test that concurrently Call/Notify + server replies and validates stream integrity.
  |||,
  filesToRanges={
    'internal/lsp/transport.go': [
      [15, 38],   // WriteMessage: header then body, no lock
      [145, 148], // server request reply -> WriteMessage(c.stdin, response)
      [215, 218], // client request send   -> WriteMessage(c.stdin, msg)
      [260, 267], // client notify send    -> WriteMessage(c.stdin, msg)
    ],
  },
)
