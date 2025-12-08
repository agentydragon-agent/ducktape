local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Lines 390-391 in `BoundOpenAIModel.responses_create()` manually construct the reasoning dict:

    ```python
    if self.reasoning_effort and "reasoning" not in kwargs:
        kwargs["reasoning"] = {"effort": self.reasoning_effort.value}
    ```

    This bypasses the existing type-safe `ReasoningParams` TypedDict (defined in `openai_utils/types.py`) and duplicates conversion logic that already exists.

    The codebase already has:
    - `ReasoningParams` TypedDict with `effort` and `summary` fields (types.py)
    - `ResponsesRequest.reasoning: ReasoningParams | None` field (line 178)
    - `build_reasoning_params()` helper function for constructing ReasoningParams (types.py)
    - `to_kwargs()` which calls `model_dump()` and would automatically serialize ReasoningParams

    The manual dict construction is redundant and type-unsafe. Instead, `BoundOpenAIModel` should either:
    1. Construct a proper `ReasoningParams` object and inject it into the request before calling `to_kwargs()`, OR
    2. Let callers pass the reasoning params in the ResponsesRequest (which already has the field)

    Manual dict manipulation after `to_kwargs()` bypasses the type system and creates maintenance burden.
  |||,
  filesToRanges={
    'adgn/src/adgn/openai_utils/model.py': [
      [390, 391],  // Manual dict construction
      [178, 178],  // ResponsesRequest.reasoning field
    ],
  },
)
