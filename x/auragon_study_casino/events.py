"""Pydantic schemas for client-reported casino audit events."""

from __future__ import annotations

import json
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from x.auragon_study_casino.models import GameEventRow

_MAX_OUTCOME_JSON_BYTES = 16 * 1024


class GameEventCreate(BaseModel):
    """One client-reported completed wager.

    Until game resolution moves server-side, this is an audit record of what
    the browser says happened. The server adds its own timestamp and observed
    canonical balance when it persists the event.
    """

    model_config = ConfigDict(extra="forbid")

    client_event_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9._:@-]+$")
    occurred_at_ms: int = Field(ge=0)
    game: Literal["roulette", "slots", "blackjack"]
    event_type: Literal["settle"] = "settle"
    wager_credits: int = Field(ge=0)
    payout_tokens: int = Field(ge=0)
    credits_before: int = Field(ge=0)
    credits_after: int = Field(ge=0)
    tokens_before: int = Field(ge=0)
    tokens_after: int = Field(ge=0)
    outcome: dict[str, Any] = Field(default_factory=dict)

    @field_validator("outcome")
    @classmethod
    def _outcome_must_stay_small(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
        except TypeError as e:
            raise ValueError(f"outcome must be JSON-serializable: {e}") from e
        if len(encoded.encode("utf-8")) > _MAX_OUTCOME_JSON_BYTES:
            raise ValueError(f"outcome JSON must be <= {_MAX_OUTCOME_JSON_BYTES} bytes")
        return value

    def outcome_json(self) -> str:
        return json.dumps(self.outcome, sort_keys=True, separators=(",", ":"))


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
        outcome=json.loads(row.outcome_json),
    )
