# glm-4.6 strict tool schema experiments

**Date:** 2026-06-06

## Context

Props critic direct exec was failing on `glm-4.6` because the model returned stringified values for
nullable required tool fields. The important exec fields were:

- `exec.env`: previously `list[EnvVar] | None`; z.ai returned `"null"`, `"[]"`, or a stringified
  JSON array instead of a native JSON null/list.
- `exec.stdin_text`: previously `str | None`; z.ai returned `"null"`, which passed validation as a
  literal stdin string.

One live critic run (`641e1a49-de5f-4338-8d19-f6db8be63b5a`) also produced an `exec.cmd` value as a
stringified argv list and a malformed tool-call name resembling `python3</arg_value>`. Minimal
experiments did not reproduce a general failure for required non-null `list[str]`, so treat that as a
weaker/model-quality symptom rather than the primary schema-shape bug.

## Experiment

Tested `glm-4.6` against both:

- z.ai coding Chat Completions directly (`https://api.z.ai/api/coding/paas/v4/chat/completions`)
- cluster LiteLLM Chat Completions forwarding to z.ai

Both paths behaved the same for the relevant schema shapes.

## Results

Working shapes:

- Required `string` emitted a native JSON string.
- Required `array` of strings emitted a native JSON array.
- Required `array` of command-like strings, including pipe tokens inside `"sh -c"` argv, emitted a
  native JSON array.
- Optional nullable field omitted from `required` was omitted when not needed.
- Required non-null sentinel shapes worked:
  - empty-string sentinel for stdin-like text
  - empty-array sentinel for env-like lists
  - object wrapper such as `{"mode": "inherit", "values": []}`
  - enum sentinel such as `"none"`

Broken shapes:

- Required nullable string (`anyOf: [{"type": "string"}, {"type": "null"}]`) returned `"null"` as a
  string when asked to pass JSON null.
- Required nullable array (`anyOf: [{"type": "array"}, {"type": "null"}]`) returned `"null"` as a
  string when asked to pass JSON null.
- Required nullable array returned a stringified JSON array when asked to pass a list.

## Decision

For direct props exec, remove model-controlled optional/nullable args instead of trying to coerce
them. `env` was already removed; `stdin_text` was removed after this experiment. If a future tool
needs these concepts, prefer non-null sentinel shapes or an explicit object with a mode discriminator,
and validate that exact shape against z.ai before deploying it.
