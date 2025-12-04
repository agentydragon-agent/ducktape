local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    model.py input message types (AssistantMessage, UserMessage, SystemMessage lines
    26-53) embed the discriminator field (role) directly in the message class,
    mixing API-level concerns with content structure.

    Current inconsistency: input messages use "role" as discriminator, other input
    items use "type" (ReasoningItem, FunctionCallItem), output messages use "kind"
    (AssistantMessageOut line 172-182). This creates three different discriminator
    naming conventions.

    Separate message from discriminator using wrapper pattern: message class contains
    content only, wrapper class contains discriminator "kind" plus message. This
    matches the output pattern (AssistantMessageOut) and enables clearer type
    discrimination for union types (InputItem line 93).

    Benefits: Consistent discriminator naming, separates transport/API concerns from
    content structure, message content can evolve independently from serialization
    format.
  |||,
  filesToRanges={
    'adgn/src/adgn/openai_utils/model.py': [
      [26, 33],   // AssistantMessage with role discriminator
      [36, 43],   // UserMessage with role discriminator
      [46, 53],   // SystemMessage with role discriminator
      [93, 93],   // InputItem union - would benefit from consistent discriminators
      [172, 182], // AssistantMessageOut uses kind discriminator (reference pattern)
    ],
  },
)
