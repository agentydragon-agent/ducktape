local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The `to_kwargs()` method (lines 184-192) is unnecessarily complex - it's essentially just `.model_dump()` but "painted blue" with redundant manual processing.

    Current implementation:
    ```python
    def to_kwargs(self) -> dict[str, Any]:
        payload = self.model_dump(exclude_none=True)
        input_value = payload.get("input")
        if isinstance(input_value, list):
            payload["input"] = [
                it.model_dump(exclude_none=True) if isinstance(it, BaseModel) else it for it in input_value
            ]
        return payload
    ```

    The manual iteration to check `isinstance(it, BaseModel)` and conditionally call `model_dump()` on list items (lines 188-191) is redundant. Pydantic's `model_dump()` already recursively serializes nested BaseModel instances, including items in lists. This is built-in Pydantic behavior.

    The entire method should be simplified to:
    ```python
    def to_kwargs(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)
    ```

    This does exactly the same thing but without the unnecessary complexity.
  |||,
  filesToRanges={'adgn/src/adgn/openai_utils/model.py': [[184, 192]]},
)
