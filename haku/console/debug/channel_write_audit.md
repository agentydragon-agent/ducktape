# Current outbound Matrix write audit

The invariant, stated by the operator on 2026-08-15:

> No events should be written directly into Matrix without going through our database. Because
> Matrix is just one of pluggable backends. Channels.

Read as a rule about facts rather than renderings: **every fact a channel shows is recorded first,
and the channel derives its rendering from that record**. Typing and the text of an editable status
line may remain Matrix-private renderings, but the state behind them must be reproducible from the
conversation. A direct homeserver write whose only source is a stack frame is invisible to every
other channel and unrecoverable after a crash.

This is the live inventory after the sealed-notice replay foundation (#4532). It names symbols rather
than line numbers so it remains grep-able as files move. The ordered follow-up is
<../TODO.md#the-console-as-a-channel-not-a-viewer>; the design is
<../plans/conversation_layers.md>.

## The Matrix write surface

`MatrixClient` is the only holder of a Matrix credential. Its state-changing calls are `join`,
`send_text`, `send_notice`, `edit_notice`, `set_typing` and `redact`. There are still no read
receipts, profile writes, room-state writes, invites sent by Haku or `leave` calls.

| Effect                                                        | Driver                                                                                  | Durable source / delivery state                                                                                        | Remaining gap                                                                                                                                          |
| ------------------------------------------------------------- | --------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Assistant reply (`send_text`)                                 | `RoomNotices` → `matrix_outbox` → `RoomOutboxDrain.post_reply`                          | Completed conversation item; attachment-scoped outbox row, ordered retry and stable transaction id                     | The outbox drain and notice reader are separate attachment owners                                                                                      |
| Sealed notice (`send_notice`)                                 | `RoomNotices` + `room_subscription.project_notice` → `MatrixSyncService.project_notice` | One conversation event; attachment/conversation/event source tag, deterministic transaction id, cursor kept after send | Duplicate protection becomes ambiguous after Synapse forgets the transaction id because Haku does not read its own tagged events                       |
| Relayed prompt (`send_notice`)                                | `RoomNotices._relayed` → `announce`                                                     | Prompt item and origin are durable                                                                                     | `announce` only queues an in-process closure; the cursor may advance before the room has it, and the event has no stable source identity               |
| Silent-turn narration (`send_notice`)                         | `RoomNotices._silent` → `announce`                                                      | Completed turn/items are durable                                                                                       | Same queued, cursor-detached delivery as the relay                                                                                                     |
| Status create/edit/redact                                     | `RoomNotices` folds `LiveStatus` → `show_status` / `clear_status`                       | Desired state is reconstructible from conversation events; `matrix_revision` keeps the current remote event id         | No own-event correspondence reader; the tag still names a session; duplicate/stale remote state is not compared with desired state after a long outage |
| Typing (`set_typing`)                                         | `RoomNotices` folds `LiveStatus` → `set_typing`                                         | Desired state is reconstructible; Synapse expires the effect                                                           | Deliberately best effort; it must become attachment-scoped before more than one room is served                                                         |
| Session lifecycle narration (`send_notice`)                   | `MatrixSessionSupervisor` → `announce`                                                  | Session rows/events hold some facts                                                                                    | The channel still creates/replaces sessions, deduplicates narration in `_last_announced`, and queues the Matrix effect directly                        |
| Invite refusal / joined / adopted-room notice (`send_notice`) | `_handle_invite` / sync adoption → `_queue_notice`                                      | `chat_attachment` records the binding decision                                                                         | The announcement has no durable Matrix-side subject; the one-room refusal is itself scheduled for removal                                              |
| Membership (`join`)                                           | `_handle_invite` after `bind_room`                                                      | Attachment is committed before the effect; Synapse retains a failed invite for retry                                   | No explicit attachment membership state or general repair loop                                                                                         |

## What is now record-driven

`RoomNotices` owns one durable `ChannelCursor` for the live attachment and reads the same
`ConversationStream` as the browser. It now:

- queues completed assistant messages in `matrix_outbox`;
- folds the stream into live status and typing through `LiveStatus`;
- projects prompt rejection and unreadable input;
- projects setup narration, session adoption and lease expiry;
- projects an operator-aborted turn; and
- relays a prompt from another surface and identifies a turn that completed without an answer.

The sealed one-event families — rejection, unreadable input, setup narration, session adoption,
lease expiry and operator abort — use the pure `project_notice` path. Returning from that path means
the homeserver accepted the send, and only then may the subscription cursor advance. A replay uses
the same attachment-scoped transaction id. This closes the old commit-then-queue crash window
**inside Synapse's transaction-cache lifetime**; it does not create durable exactly-once
correspondence.

The relay and silent-turn cases are intentionally listed separately. Their words require a fold over
item/turn state rather than one event body, and today they call `announce`, which returns after
placing an unrelated closure in `RoomPacer`. They are record-derived but not yet reconciled.

## What remains direct

### Matrix still owns session rows

`MatrixSessionSupervisor` creates the initial idle session, reports each observed status, reconciles
terminal claims and creates replacements. `_last_announced` is process-local, so a leadership change
can narrate the same state again. More importantly, a channel still knows that sessions exist. The
replacement is channel-neutral supervision behind the conversation: Matrix binds/offers input and
renders lifecycle events, while runtime code ensures durable demand has an idle or replacement
session.

### Attachment narration has no neutral event

Joining, refusing a second invite and adopting an existing room are Matrix attachment facts, not
session events. `chat_attachment` is the right durable authority for the binding, but there is no
channel-private subject saying what announcement (if any) the room should show. Do not put a
Matrix-shaped event in the conversation merely to eliminate `_queue_notice`; attachment
reconciliation needs its own durable desired state.

### Live status is the span prototype, not the finished reconciler

`LiveStatus` is already the desired shape on the conversation side: replaying the durable stream
reconstructs the same status/typing state, and `matrix_revision` survives a replica handoff with the
event id to edit or redact. What is absent is the room side of reconciliation. `MatrixClient._read`
drops Haku's own sender before ingress sees it, so no process verifies that the revision row still
matches the room, observes a redaction, or finds a duplicate created after transaction-cache expiry.

The correspondence reader must be a separate, opposite-filter path: only Haku's sender, tags parsed
as channel state, never offered as prompts.

## Why the remaining order is constrained

1. **Read correspondence before depending on edits.** The source tag from #4532 is the stable key;
   reading it turns transaction-window replay protection into durable reconciliation.
2. **Fold stable spans.** Generalise `LiveStatus` to bounded work/session subjects and move relay,
   silence and supervisor narration off direct sends.
3. **Remove channel-owned session lifecycle.** Otherwise a many-room Matrix implementation merely
   multiplies a forbidden edge.
4. **Unify delivery per attachment, then add rooms.** `MXSY`, `MXOB`, `MXNT` and `MXSE` currently
   elect independently; `bound_room()`, `_status_body` and one `RoomPacer` status slot are global.
   A second room would cross wires silently.

Commands and channel links do not block this spine. They remain separate affordances in the TODO.
The selectable-runtime/Agent work in #4431 is also separate: the neutral supervisor may consume its
runtime registry, but Matrix must not select or understand a backend.

## Standing tests for future PRs

- A crash after `room_send` and before cursor commit, replayed after Synapse's transaction cache has
  expired, produces one visible source event.
- A duplicate or redacted tagged event is discovered and repaired from desired state.
- Notice folds are pure and bounded: event sequence in, `(subject, body, lifecycle)` out, without a
  room or database.
- A leader handoff reconstructs status/spans without a second live event.
- Two rooms can prompt and receive replies concurrently without sharing cursor, event id, status
  slot or rate budget.
- Killing a session mid-turn is visible through conversation events, not through a supervisor push,
  and its replacement is invisible to channel code.
