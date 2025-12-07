local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Lines 361-372 manually parse event types using dict.get() and string comparison:
      ev = obj.get("event") if isinstance(obj, dict) else None
      if ev == "hook_output":
          hook_ev = HookOutputEvent.model_validate(obj)
      if ev == "progress":
          prog_ev = ProgressEvent.model_validate(obj)

    The codebase already defines a StreamMessage discriminated union in protocol.py.
    Use pydantic's TypeAdapter with the existing union type and Python's match
    statement for type-safe, exhaustive event handling:
      stream_adapter = TypeAdapter(StreamMessage)
      event = stream_adapter.validate_python(obj)
      match event:
          case HookOutputEvent() as hook_ev: ...
          case ProgressEvent() as prog_ev: ...
  |||,
  filesToRanges={'wt/src/wt/client/wt_client.py': [[361, 372]]},
)
