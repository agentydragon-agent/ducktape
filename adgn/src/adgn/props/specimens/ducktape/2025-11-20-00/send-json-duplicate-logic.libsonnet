local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    send_json and _send_direct_all have identical logic except for how they send
    (runtime.py:119-128, 187-196).

    send_json uses q.put_nowait():
    for _ws, q, _task in list(self._clients.values()):
        q.put_nowait(dumped)

    _send_direct_all uses ws.send_json():
    for ws, _q, _task in list(self._clients.values()):
        await ws.send_json(dumped)

    Both:
    1. Create identical Envelope with same fields
    2. Call model_dump(mode="json")
    3. Iterate over self._clients.values()
    4. Send to each client

    Only difference: synchronous put_nowait vs async send_json.

    Should extract common logic:
    def _create_envelope(self, payload: ServerMessage) -> dict:
        return Envelope(
            session_id=self._session_id,
            event_id=self._next_event_id(),
            event_at=datetime.now(UTC),
            payload=payload,
        ).model_dump(mode="json")

    async def send_json(self, payload: ServerMessage) -> None:
        dumped = self._create_envelope(payload)
        for _ws, q, _task in list(self._clients.values()):
            q.put_nowait(dumped)

    async def _send_direct_all(self, payload: ServerMessage) -> None:
        dumped = self._create_envelope(payload)
        for ws, _q, _task in list(self._clients.values()):
            await ws.send_json(dumped)

    Or unify completely if possible.

    Benefits:
    - DRY: envelope creation in one place
    - Easier to maintain: change once, affects both
    - Clear separation: envelope creation vs distribution
  |||,

  filesToRanges={
    'adgn/src/adgn/agent/server/runtime.py': [
      [119, 128],   // send_json method
      [187, 196],   // _send_direct_all method (duplicate logic)
    ],
  },
)
