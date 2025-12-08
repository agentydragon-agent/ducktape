local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The `OpenAIModelProto` protocol (line 401) is defined AFTER its implementations (`OpenAIModel` at line 345 and `BoundOpenAIModel` at line 376). This makes the code harder to understand - readers see implementations before understanding the interface contract.

    Additionally, the implementations don't explicitly inherit from the protocol. While structural typing means they satisfy the protocol, explicit inheritance would:
    1. Make the implementation relationship clear and intentional
    2. Catch errors at definition time if the implementation is incomplete
    3. Make it harder to accidentally create unintended implementations

    Better approach: Convert the protocol to an ABC (Abstract Base Class) and define it ABOVE its implementations. Have implementations explicitly inherit from it:

    ```python
    from abc import ABC, abstractmethod

    class OpenAIModelProto(ABC):
        @property
        @abstractmethod
        def model(self) -> str: ...

        @abstractmethod
        async def responses_create(self, req: ResponsesRequest) -> ResponsesResult: ...

    class OpenAIModel(OpenAIModelProto):
        # ... implementation

    class BoundOpenAIModel(OpenAIModelProto):
        # ... implementation
    ```

    This makes the contract explicit, prevents accidental implementations, and improves code organization.
  |||,
  filesToRanges={
    'adgn/src/adgn/openai_utils/model.py': [
      [401, 405],  // Protocol definition
      [345, 345],  // OpenAIModel class (should inherit)
      [376, 379],  // BoundOpenAIModel class (claims to implement but doesn't inherit)
    ],
  },
)
