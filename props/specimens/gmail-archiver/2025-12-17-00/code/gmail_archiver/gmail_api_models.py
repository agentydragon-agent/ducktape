"""Pydantic models for Gmail API resources.

These models represent the structure of Gmail API responses for filters and labels.
See: https://developers.google.com/gmail/api/reference/rest
"""

from enum import StrEnum

from pydantic import BaseModel, Field

# Label models


class LabelType(StrEnum):
    SYSTEM = "system"
    USER = "user"


class LabelListVisibility(StrEnum):
    LABEL_SHOW = "labelShow"
    LABEL_SHOW_IF_UNREAD = "labelShowIfUnread"
    LABEL_HIDE = "labelHide"


class MessageListVisibility(StrEnum):
    SHOW = "show"
    HIDE = "hide"


class GmailLabel(BaseModel):
    """Gmail label resource."""

    id: str
    name: str
    type: LabelType | None = None
    message_list_visibility: MessageListVisibility | None = Field(default=None, alias="messageListVisibility")
    label_list_visibility: LabelListVisibility | None = Field(default=None, alias="labelListVisibility")
    messages_total: int | None = Field(default=None, alias="messagesTotal")
    messages_unread: int | None = Field(default=None, alias="messagesUnread")
    threads_total: int | None = Field(default=None, alias="threadsTotal")
    threads_unread: int | None = Field(default=None, alias="threadsUnread")
    color: dict | None = None

    model_config = {"populate_by_name": True}


class CreateLabelRequest(BaseModel):
    """Request body for creating a label."""

    name: str
    label_list_visibility: LabelListVisibility = Field(
        default=LabelListVisibility.LABEL_SHOW, alias="labelListVisibility"
    )
    message_list_visibility: MessageListVisibility = Field(
        default=MessageListVisibility.SHOW, alias="messageListVisibility"
    )

    model_config = {"populate_by_name": True}


# Filter models


class SizeComparison(StrEnum):
    LARGER = "larger"
    SMALLER = "smaller"


class FilterCriteria(BaseModel):
    """Gmail filter matching criteria."""

    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    subject: str | None = None
    query: str | None = None
    negated_query: str | None = Field(default=None, alias="negatedQuery")
    has_attachment: bool | None = Field(default=None, alias="hasAttachment")
    exclude_chats: bool | None = Field(default=None, alias="excludeChats")
    size: int | None = None
    size_comparison: SizeComparison | None = Field(default=None, alias="sizeComparison")

    model_config = {"populate_by_name": True}


class FilterAction(BaseModel):
    """Gmail filter actions to perform on matching messages."""

    add_label_ids: list[str] = Field(default_factory=list, alias="addLabelIds")
    remove_label_ids: list[str] = Field(default_factory=list, alias="removeLabelIds")
    forward: str | None = None

    model_config = {"populate_by_name": True}


class GmailFilter(BaseModel):
    """Gmail filter resource."""

    id: str | None = None
    criteria: FilterCriteria = Field(default_factory=FilterCriteria)
    action: FilterAction = Field(default_factory=FilterAction)


class CreateFilterRequest(BaseModel):
    """Request body for creating a filter."""

    criteria: FilterCriteria
    action: FilterAction


class SystemLabel(StrEnum):
    """Gmail system label IDs."""

    INBOX = "INBOX"
    SPAM = "SPAM"
    TRASH = "TRASH"
    UNREAD = "UNREAD"
    STARRED = "STARRED"
    IMPORTANT = "IMPORTANT"
    SENT = "SENT"
    DRAFT = "DRAFT"
    CATEGORY_PERSONAL = "CATEGORY_PERSONAL"
    CATEGORY_SOCIAL = "CATEGORY_SOCIAL"
    CATEGORY_PROMOTIONS = "CATEGORY_PROMOTIONS"
    CATEGORY_UPDATES = "CATEGORY_UPDATES"
    CATEGORY_FORUMS = "CATEGORY_FORUMS"


# Keep frozenset for membership checks
SYSTEM_LABEL_IDS = frozenset(SystemLabel)


def is_system_label(label_id: str) -> bool:
    """Check if a label ID is a system label."""
    return label_id in SYSTEM_LABEL_IDS or label_id.startswith("CATEGORY_")
