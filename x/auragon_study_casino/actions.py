"""Pydantic wire models for server-authoritative Study Casino actions."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from x.auragon_study_casino.events import GameEventRead, LedgerEventRead

_ACTION_ID_PATTERN = r"^[a-zA-Z0-9._:@-]+$"


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_action_id: str = Field(min_length=1, max_length=128, pattern=_ACTION_ID_PATTERN)
    state_vector_b64: str = Field(default="", max_length=4 * 1024 * 1024)


class ActionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_action_id: str
    event: LedgerEventRead
    result: dict[str, Any]
    update_b64: str
    state_vector_b64: str
    game_event: GameEventRead | None = None


class SessionCompleteRequest(ActionRequest):
    session_id: str | None = Field(default=None, max_length=128)
    ended_at_ms: int | None = Field(default=None, ge=0)


class AddPastSessionRequest(ActionRequest):
    subject: str = Field(min_length=1, max_length=120)
    seconds: int = Field(gt=0, le=90 * 24 * 60 * 60)
    ended_at_ms: int = Field(ge=0)
    session_id: str | None = Field(default=None, max_length=128)


class EditSessionRequest(ActionRequest):
    session_id: str = Field(min_length=1, max_length=128)
    subject: str | None = Field(default=None, min_length=1, max_length=120)
    seconds: int | None = Field(default=None, ge=0, le=90 * 24 * 60 * 60)


class DeleteSessionRequest(ActionRequest):
    session_id: str = Field(min_length=1, max_length=128)


class ConvertRequest(ActionRequest):
    amount: int = Field(gt=0)


class PrizeRedeemRequest(ActionRequest):
    prize_id: str = Field(min_length=1, max_length=128)


class ImportRequest(ActionRequest):
    data: dict[str, Any]


class ResetRequest(ActionRequest):
    pass


class SlotsSpinRequest(ActionRequest):
    wager_credits: int = Field(gt=0)


class RouletteSpinRequest(ActionRequest):
    wager_credits: int = Field(gt=0)
    bet_type: Literal["red", "black", "odd", "even", "low", "high", "dozen1", "dozen2", "dozen3", "number"]
    bet_number: int | None = Field(default=None, ge=0, le=36)


class BlackjackDealRequest(ActionRequest):
    wager_credits: int = Field(gt=0)


class BlackjackHandRequest(ActionRequest):
    hand_id: str = Field(min_length=1, max_length=64)
