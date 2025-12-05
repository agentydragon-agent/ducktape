local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    The TokenUsage model has a total_tokens field that is a trivial sum of two other fields:

    class TokenUsage(BaseModel):
        input_tokens: int | None = Field(None, ...)
        output_tokens: int | None = Field(None, ...)
        total_tokens: int | None = Field(None, description="Total tokens consumed (input + output)")

    The total_tokens field is redundant:
    - It's always input_tokens + output_tokens
    - No additional information
    - Must be kept in sync manually (error-prone)
    - Wastes storage/bandwidth

    This violates DRY - the total is trivially computable from the parts.

    Fix options:
    1. Preferred: Remove total_tokens field entirely. Callers compute:
       total = (usage.input_tokens or 0) + (usage.output_tokens or 0)

    2. For API compatibility, make it a computed property:
       @property
       def total_tokens(self) -> int | None:
           if self.input_tokens is None and self.output_tokens is None:
               return None
           return (self.input_tokens or 0) + (self.output_tokens or 0)

    This ensures:
    - Single source of truth (input + output)
    - Cannot get out of sync
    - No redundant storage
    - Backward compatible if needed
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/handler.py': [
      29,  // total_tokens field definition
    ],
  },
)
