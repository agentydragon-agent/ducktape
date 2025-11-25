local I = import '../../specimens/lib.libsonnet';

// iss-027: Manual dictionary parsing instead of Pydantic discriminated unions

I.issueOneOccurrence(
  rationale= |||
    The `parse_event()` function manually parses event dictionaries using if-elif
    chains that inspect the `type` field and construct the appropriate payload class.
    This is exactly what Pydantic's discriminated union parsing does automatically,
    but the code reimplements it by hand.

    **Current implementation (events.py, lines 67-100):**
    ```python
    TypedPayload = Annotated[
        UserTextPayload
        | AssistantTextPayload
        | ToolCallPayload
        | FunctionCallOutputPayload
        | ReasoningPayload
        | ResponsePayload,
        Field(discriminator=None),  # ← discriminator is None!
    ]

    class EventRecord(BaseModel):
        seq: int
        ts: datetime
        type: EventType
        payload: TypedPayload
        call_id: str | None = None
        tool_key: str | None = None

    def parse_event(d: dict[str, Any]) -> EventRecord:
        raw_type = d.get("type")
        et = EventType(str(raw_type))
        seq = int(d.get("seq", 0))
        ts_raw = d.get("ts")
        ts = ts_raw if isinstance(ts_raw, datetime) else datetime.fromisoformat(str(ts_raw))
        call_id = d.get("call_id")
        tool_key = d.get("tool_key")
        payload_raw = d.get("payload") or {}

        payload: TypedPayload
        if et == EventType.USER_TEXT:
            payload = UserTextPayload(text=str(payload_raw.get("text", "")))
        elif et == EventType.ASSISTANT_TEXT:
            payload = AssistantTextPayload(text=str(payload_raw.get("text", "")))
        elif et == EventType.TOOL_CALL:
            payload = ToolCallPayload(
                name=str(payload_raw.get("name", "")),
                args_json=payload_raw.get("args_json"),
                call_id=str(payload_raw.get("call_id") or d.get("call_id") or ""),
            )
        elif et == EventType.FUNCTION_CALL_OUTPUT:
            result = TypeAdapter(mcp_types.CallToolResult).validate_python(payload_raw)
            payload = FunctionCallOutputPayload(call_id=str(d.get("call_id") or ""), result=result)
        elif et == EventType.REASONING:
            payload = ReasoningPayload(text=str(payload_raw.get("text", "")))
        elif et == EventType.RESPONSE:
            payload = ResponsePayload(content=payload_raw)
        else:
            payload = ResponsePayload(content=payload_raw)

        return EventRecord(seq=seq, ts=ts, type=et, payload=payload, call_id=call_id, tool_key=tool_key)
    ```

    **Problems:**

    1. **Reimplements Pydantic**: Manual if-elif dispatching duplicates what Pydantic does
    2. **Error-prone**: Easy to forget cases or mismatch type strings
    3. **Verbose**: 30 lines of manual parsing vs 3 lines with discriminated unions
    4. **No validation**: Manual `str()` casts and `.get()` don't validate structure
    5. **Inconsistent**: Some fields use TypeAdapter, others use manual dict access
    6. **Misleading type hint**: `Field(discriminator=None)` suggests discriminated union but doesn't use it
    7. **Maintenance burden**: Adding a new event type requires updating if-elif chain

    **The correct approach:**

    Use Pydantic's discriminated union parsing with a proper discriminator:

    ```python
    from typing import Annotated, Literal
    from pydantic import BaseModel, Field, Tag

    # Add 'type' literal to each payload class
    class UserTextPayload(BaseModel):
        type: Literal["user_text"] = "user_text"
        text: str


    class AssistantTextPayload(BaseModel):
        type: Literal["assistant_text"] = "assistant_text"
        text: str


    class ToolCallPayload(BaseModel):
        type: Literal["tool_call"] = "tool_call"
        name: str
        args_json: str | None = None
        call_id: str


    class FunctionCallOutputPayload(BaseModel):
        type: Literal["function_call_output"] = "function_call_output"
        call_id: str
        result: mcp_types.CallToolResult


    class ReasoningPayload(BaseModel):
        type: Literal["reasoning"] = "reasoning"
        text: str


    class ResponsePayload(BaseModel):
        type: Literal["response"] = "response"
        content: Response | None = None


    # Discriminated union with proper discriminator
    TypedPayload = Annotated[
        UserTextPayload
        | AssistantTextPayload
        | ToolCallPayload
        | FunctionCallOutputPayload
        | ReasoningPayload
        | ResponsePayload,
        Field(discriminator="type"),  # ← Use 'type' field as discriminator
    ]


    class EventRecord(BaseModel):
        seq: int
        ts: datetime
        # Remove separate 'type' field - it's in the payload now
        payload: TypedPayload
        call_id: str | None = None
        tool_key: str | None = None

        model_config = ConfigDict(extra="forbid")

        @property
        def type(self) -> EventType:
            """Derive event type from payload for backwards compatibility."""
            return EventType(self.payload.type)


    # Parse event is now trivial - just let Pydantic do it
    def parse_event(d: dict[str, Any]) -> EventRecord:
        # Move 'type' from top level into 'payload' if needed
        if "type" in d and "payload" in d:
            d = {**d, "payload": {**d["payload"], "type": d["type"]}}
        return EventRecord.model_validate(d)


    def parse_events(items: list[dict[str, Any]]) -> list[EventRecord]:
        return [parse_event(d) for d in items]
    ```

    **Alternative approach (if payload structure varies):**

    If the persisted JSON doesn't have `type` inside `payload`, use a custom validator:

    ```python
    class EventRecord(BaseModel):
        seq: int
        ts: datetime
        type: EventType  # Keep top-level type for wire format
        payload: TypedPayload
        call_id: str | None = None
        tool_key: str | None = None

        @model_validator(mode='before')
        @classmethod
        def inject_type_into_payload(cls, data: Any) -> Any:
            """Inject top-level 'type' into payload for discriminated union parsing."""
            if isinstance(data, dict):
                event_type = data.get("type")
                payload = data.get("payload")
                if event_type and isinstance(payload, dict):
                    # Add 'type' to payload dict for discriminator
                    data["payload"] = {**payload, "type": event_type}
            return data

        model_config = ConfigDict(extra="forbid")


    def parse_event(d: dict[str, Any]) -> EventRecord:
        return EventRecord.model_validate(d)
    ```

    **Benefits:**

    1. **Automatic dispatch**: Pydantic handles type-based routing
    2. **Full validation**: All fields validated according to payload schema
    3. **Type safety**: MyPy/Pyright understand the discriminated union
    4. **Concise**: 3 lines instead of 30+ lines of if-elif
    5. **Better errors**: ValidationError shows exactly what's wrong and where
    6. **Easy to extend**: Add new event type = add new payload class to union
    7. **Declarative**: Schema describes what's valid, not how to parse

    **Pydantic discriminated union features used:**

    - `Literal["event_type"]` on each variant for the discriminator value
    - `Field(discriminator="type")` on the union to tell Pydantic which field to inspect
    - `model_validate()` to parse and validate in one step
    - Optional `@model_validator(mode='before')` to massage data shape if needed

    **Testing discriminated unions:**

    ```python
    # Good payloads parse correctly
    event = EventRecord.model_validate({
        "seq": 1,
        "ts": "2024-01-15T10:30:00Z",
        "type": "user_text",
        "payload": {"text": "hello"},
    })
    assert isinstance(event.payload, UserTextPayload)

    # Bad payloads fail with clear errors
    with pytest.raises(ValidationError) as exc:
        EventRecord.model_validate({
            "seq": 1,
            "ts": "2024-01-15T10:30:00Z",
            "type": "unknown_type",  # Not in union
            "payload": {},
        })
    # Error message shows: "Input tag 'unknown_type' not recognized"
    ```
  |||,
  properties=['use-platform-primitives', 'declarative-validation'],
  filesToRanges={
    'adgn/src/adgn/agent/persist/events.py': [
      [47, 50],  // TypedPayload union with discriminator=None
      [67, 100], // Manual parse_event() with if-elif chains
    ],
  },
  gap_note= |||
    This finding illustrates **"use-platform-primitives"**: Pydantic provides
    discriminated union parsing with automatic dispatch based on a discriminator
    field. Don't reimplement this with manual if-elif chains.

    Discriminated unions (tagged unions) are a common pattern for parsing
    heterogeneous data where a "type" field determines the payload structure.
    Pydantic handles this idiomatically:

    1. Each variant has a Literal field matching its type
    2. The union is annotated with Field(discriminator="field_name")
    3. Pydantic automatically dispatches to the correct variant based on that field

    When to use discriminated unions:
    - JSON/API responses with a "type" or "kind" field determining structure
    - Event streams where event type determines payload shape
    - Polymorphic data (e.g., different tool call types, notification types)
    - Configuration objects with different schemas per type

    Common mistakes:
    - Setting `discriminator=None` (disables discriminated union parsing)
    - Manual if-elif dispatching instead of letting Pydantic do it
    - Not adding the discriminator field to each variant
    - Forgetting to use Literal for the discriminator value

    Related to **"declarative-validation"**: describe WHAT the data should be
    (union of typed payloads) rather than HOW to parse it (if-elif chains).

    The Pydantic way:
    - Define schemas declaratively (BaseModel classes with Literal discriminators)
    - Let the framework parse and validate
    - Get clear, structured errors for free
    - Type checkers understand the union and narrow types correctly
  |||,
)
