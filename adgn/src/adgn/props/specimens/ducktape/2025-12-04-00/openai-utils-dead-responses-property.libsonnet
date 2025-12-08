local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The `responses` property (lines 348-357) in `OpenAIModel` is dead code. It provides a `.responses.create()` interface that wraps `responses_create()`, but this property is never used anywhere in the codebase.

    Evidence:
    - `BoundOpenAIModel` (line 376), which implements the `OpenAIModelProto` protocol, only implements `responses_create()` (line 386), not the `responses` property
    - The protocol `OpenAIModelProto` (line 401) only requires `responses_create()`, not `responses`
    - No code in the codebase calls `.responses.create()`
    - All consumers use `responses_create()` directly

    The property adds complexity (nested class `_Compat`, cast) without providing any value. Delete the entire property.
  |||,
  filesToRanges={'adgn/src/adgn/openai_utils/model.py': [[348, 357]]},
)
