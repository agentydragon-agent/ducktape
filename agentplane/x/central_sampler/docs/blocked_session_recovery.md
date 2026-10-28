# Recovering a blocked Session

A blocked Session has an effect or live runtime handle whose outcome is uncertain. The sampler will
not continue it automatically because replaying an accepted provider request or executor operation
could duplicate external work.

Use the API to inspect the durable record:

1. Call `GetSession` and read `blocked_reason` for the unresolved intent or handle.
2. Call `GetCommand` for the active or last command. Its `failure_reason` explains the command
   outcome when a command was active.
3. Call `FollowEvents` from the Session cursor. Inspect `ExecutionProgress` and the linked
   `BoundaryRecord` entries; correlate fragments by record ID and operations by correlation ID.
4. Reconcile the named provider request, executor process, or JavaScript cell with the external
   system using its retained evidence. Confirm whether its side effects occurred before deciding
   what work to perform next.

Do not resubmit an uncertain operation or edit the database to clear `blocked` or `pending`. V1 has
no automatic unblock or effect-replay API. Preserve the blocked Session and its evidence. If its
continuation cannot be safely reconciled, open a new Session after deciding how to handle the
external work; the new Session does not inherit the old provider conversation or live JavaScript
state.

A known provider or pre-dispatch rejection with `blocked` false is different: its command outcome is
recorded as failed, and later input can continue without replaying the rejected operation.
