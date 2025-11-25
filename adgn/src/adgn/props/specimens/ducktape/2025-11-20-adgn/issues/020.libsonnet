local I = import '../../specimens/lib.libsonnet';

// iss-020: Should construct Pydantic objects directly, not via dict

I.issueOneOccurrence(
  rationale=|||
    Code builds intermediate dict then passes to parse_event (sqlite.py:445-454):

    for event in events:
        row_dict = {
            "seq": event.seq,
            "ts": event.event_at,  # Map event_at back to ts
            "type": event.type,
            "payload": event.payload,
            "call_id": event.call_id,
            "tool_key": event.tool_key,
        }
        out.append(parse_event(row_dict))

    Should construct Pydantic EventRecord directly:
    for event in events:
        out.append(EventRecord(
            seq=event.seq,
            ts=event.event_at,
            type=event.type,
            payload=event.payload,
            call_id=event.call_id,
            tool_key=event.tool_key,
        ))

    Benefits:
    - Type safety: Pydantic validates at construction
    - No intermediate dict allocation
    - Clearer: direct mapping from ORM to domain model
    - Field name mismatches caught immediately (not in parse_event)

    The row_dict pattern suggests legacy migration from dict-based storage.
  |||,
  properties=['structured-data-over-untyped-mappings', 'no-oneoff-vars-and-trivial-wrappers'],
  filesToRanges={
    'adgn/src/adgn/agent/persist/sqlite.py': [
      [445, 454],   // row_dict construction and parse_event call
    ],
  },
)
