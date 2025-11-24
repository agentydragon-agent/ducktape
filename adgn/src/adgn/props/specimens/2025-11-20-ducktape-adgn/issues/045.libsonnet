local I = import '../../specimens/lib.libsonnet';

// iss-045: reduce_ui_state docstring duplicates type documentation

I.issueOneOccurrence(
  rationale=|||
    reduce_ui_state docstring lists all accepted event types (reducer.py:46-52):

    Accepted event types:
    - UserText: User text input
    - ToolCall: Tool call start event
    - FunctionCallOutput: Tool execution output
    - ApprovalDecisionEvt: Approval decision event
    - UiMessageEvt: Assistant message event
    - UiEndTurnEvt: End turn separator event

    This duplicates information already in the type system and type definitions.

    Problems:
    1. Duplication: UiStateEvent union already lists these (reducer.py:33)
    2. Desync risk: if UiStateEvent changes, docstring may not update
    3. No added value: type hints and definitions already document this
    4. Verbose: descriptions like "User text input" don't add information

    The type union is the source of truth:
    UiStateEvent = UserText | ToolCall | FunctionCallOutput | ApprovalDecisionEvt | UiMessageEvt | UiEndTurnEvt

    Documentation should live at type definition sites, not duplicated in
    every function that uses the type.

    Should simplify docstring to:
    """Pure reducer: match by Pydantic type; never treat models as dicts.

    Args:
        state: Current UI state.
        evt: Event to apply (one of the UiStateEvent union types).

    Returns:
        Updated UI state with the event applied.
    """

    Or just reference the union: "Accepts UiStateEvent (see type definition)."
  |||,
  properties=['no-useless-docs', 'truthfulness'],
  filesToRanges={
    'adgn/src/adgn/agent/server/reducer.py': [
      [46, 52],     // Verbose event type enumeration in docstring
    ],
  },
)
