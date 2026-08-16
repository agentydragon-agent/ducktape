"""Small persistence-neutral vocabulary shared by the Console lease authority and ORM."""

from enum import StrEnum


class KubernetesAccessGrantState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"
