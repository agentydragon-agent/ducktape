"""Pydantic models for Gmail data structures."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class LabelType(StrEnum):
    SYSTEM = "system"
    USER = "user"


class GmailMessage(BaseModel):
    """Simplified message structure extracted from Gmail API responses."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    thread_id: str | None = None
    sender: str = Field(alias="from")
    recipient: str | None = Field(default=None, alias="to")
    subject: str
    date: str
    internal_date: int  # milliseconds since epoch
    body: str
    snippet: str | None = None
    label_ids: list[str] = Field(default_factory=list)


class GmailLabel(BaseModel):
    id: str
    name: str  # e.g., 'receipts/anthropic'
    type: LabelType | None = None
