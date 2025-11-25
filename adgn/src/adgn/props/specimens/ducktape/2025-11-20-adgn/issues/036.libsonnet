local I = import '../../specimens/lib.libsonnet';

// iss-036: Should inline envelope and dumped into put_nowait/send_json

I.issueOneOccurrence(
  rationale=|||
    send_json and _send_direct_all create intermediate variables for envelope
    and dumped, used once immediately.

    Current pattern (runtime.py:120-128):
    envelope = Envelope(
        session_id=self._session_id,
        event_id=self._next_event_id(),
        event_at=datetime.now(UTC),
        payload=payload,
    )
    dumped = envelope.model_dump(mode="json")
    for _ws, q, _task in list(self._clients.values()):
        q.put_nowait(dumped)

    Same pattern in _send_direct_all (runtime.py:188-196).

    Should inline both:
    for _ws, q, _task in list(self._clients.values()):
        q.put_nowait(
            Envelope(
                session_id=self._session_id,
                event_id=self._next_event_id(),
                event_at=datetime.now(UTC),
                payload=payload,
            ).model_dump(mode="json")
        )

    Or extract to helper method if this pattern repeats.

    Benefits:
    - No intermediate variables
    - Clearer data flow: create → serialize → send
    - Less line count

    The variables have no semantic value and aren't referenced elsewhere.
  |||,
  properties=['no-oneoff-vars-and-trivial-wrappers'],
  filesToRanges={
    'adgn/src/adgn/agent/server/runtime.py': [
      [120, 128],   // send_json envelope and dumped
      [188, 196],   // _send_direct_all envelope and dumped
    ],
  },
)
