# History read and follow consumers

The implemented raw-entry API and its cursor, correction and renewal contract are in the
[History Service README](../history_service/README.md#read-and-follow-one-session).
The browser stays on Electric; a browser facade remains separate work.

## What the orchestration executor builds on it

- `read_turns(N)`: `back {TURN_STARTED, N}`, filtering `harness_user_message_confirmed`, `turn_started`,
  `turn_completed`, `item_started` and `item_completed`, no follow. The executor groups entries by
  turn: the confirmed input, tool calls by `item_started.tool_name`, the turn's status, and its final assistant
  message, the last `item_completed` whose `item_started` kind was `ITEM_KIND_ASSISTANT_TEXT`. It returns the last
  `through_cursor` as an opaque resume token.
- `wait_for_turn(token, wait)`: `after_cursor` from the token, `kinds [TURN_COMPLETED]`, follow, with a gRPC deadline
  just under the tool's wait. It returns the turn that completed, or "still running" with the newest token, so the
  next call continues where this one stopped.

## Remaining consumers and decisions

- Implement orchestration `read_turns` and `wait_for_turn` on `FollowSession`, as described above.
- Move the Notification Service's outcome scan only if `NOTIFICATION_COMMAND_OUTCOME_DESIGN` still
  requires History reads. The app's raw debug reads stay on `ReadSessionEvents`.
- Decide whether `ReadSessionEvents` can later become `FollowSession` with `follow = false`, once
  its callers need nothing else from it.
