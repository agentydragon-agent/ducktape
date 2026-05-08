"""Pydantic schemas for casino audit event reads.

Both `client_reported` (pre-2026-05-07 cutover) and `server_resolved` rows live
in `game_events`; the corresponding `legacy_client_sync` and `server_action`
rows in `ledger_events` are likewise historical. The Literal unions below
preserve those source values so old rows still deserialize cleanly.
"""

from __future__ import annotations

import json
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict

from x.auragon_study_casino.models import GameEventRow, LedgerEventRow


class GameEventRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    client_event_id: str
    server_at_ms: int
    occurred_at_ms: int
    game: Literal["roulette", "slots", "blackjack"]
    event_type: Literal["settle"]
    source: Literal["client_reported", "server_resolved"]
    wager_credits: int
    payout_tokens: int
    credits_before: int
    credits_after: int
    tokens_before: int
    tokens_after: int
    server_credits: int
    server_tokens: int
    rules_version: str | None = None
    rng_version: str | None = None
    outcome: dict[str, Any]


def game_event_from_row(row: GameEventRow) -> GameEventRead:
    return GameEventRead(
        id=row.id,
        client_event_id=row.client_event_id,
        server_at_ms=row.server_at_ms,
        occurred_at_ms=row.occurred_at_ms,
        game=cast(Literal["roulette", "slots", "blackjack"], row.game),
        event_type=cast(Literal["settle"], row.event_type),
        source=cast(Literal["client_reported", "server_resolved"], row.source),
        wager_credits=row.wager_credits,
        payout_tokens=row.payout_tokens,
        credits_before=row.credits_before,
        credits_after=row.credits_after,
        tokens_before=row.tokens_before,
        tokens_after=row.tokens_after,
        server_credits=row.server_credits,
        server_tokens=row.server_tokens,
        rules_version=row.rules_version,
        rng_version=row.rng_version,
        outcome=json.loads(row.outcome_json),
    )


class LedgerEventRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    client_action_id: str
    server_at_ms: int
    action_type: str
    source: Literal["server_action", "legacy_client_sync"]
    rules_version: str
    rng_version: str | None = None
    credits_before: int
    credits_after: int
    tokens_before: int
    tokens_after: int
    details: dict[str, Any]
    result: dict[str, Any]


def ledger_event_from_row(row: LedgerEventRow) -> LedgerEventRead:
    return LedgerEventRead(
        id=row.id,
        client_action_id=row.client_action_id,
        server_at_ms=row.server_at_ms,
        action_type=row.action_type,
        source=cast(Literal["server_action", "legacy_client_sync"], row.source),
        rules_version=row.rules_version,
        rng_version=row.rng_version,
        credits_before=row.credits_before,
        credits_after=row.credits_after,
        tokens_before=row.tokens_before,
        tokens_after=row.tokens_after,
        details=json.loads(row.details_json),
        result=json.loads(row.result_json),
    )
