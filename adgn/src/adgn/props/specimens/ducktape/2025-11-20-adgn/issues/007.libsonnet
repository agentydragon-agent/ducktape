local I = import '../../specimens/lib.libsonnet';

// iss-007: Unnecessary pre-serialization before persistence

I.issueOneOccurrence(
  rationale=|||
    Multiple locations serialize Pydantic models to dict before passing to persistence layer,
    when the persistence layer should accept the models directly and handle serialization internally.

    Location 1 (lines 102-110): _record_event method
    - Calls payload.model_dump() to create payload_dict
    - Passes payload_dict to self._persistence.append_event(payload=payload_dict)
    - Should: Pass payload directly, let append_event serialize

    Location 2 (lines 145-146): on_response method
    - Calls evt.model_dump() to create content_dict
    - Creates ResponsePayload(content=content_dict)
    - Should: ResponsePayload should accept Response directly, not pre-serialized dict

    Anti-pattern: Serialization happens at caller site instead of callee site.
    This violates separation of concerns - caller knows about persistence format.

    Correct approach:
    - append_event should accept payload: TypedPayload (not dict)
    - ResponsePayload should accept content: Response (not dict)
    - Serialization happens inside persistence layer where it belongs

    Benefits:
    - Type safety: catch mismatches at type-check time
    - Single serialization point (DRY)
    - Clearer responsibility boundaries
  |||,
  properties=['least-power', 'structured-data-over-untyped-mappings', 'type-correctness-and-specificity'],
  filesToRanges={
    'adgn/src/adgn/agent/persist/handler.py': [
      [102, 103],   // payload.model_dump() before append_event
      110,          // payload=payload_dict passed to append_event
      [145, 146],   // evt.model_dump() before ResponsePayload
    ],
  },
)
