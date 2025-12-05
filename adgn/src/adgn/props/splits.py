"""Train/validation/test split definitions for snapshot evaluation.

Each snapshot is explicitly assigned to 'train', 'valid', or 'test' in snapshots.yaml.
The split assignment is the single source of truth for snapshot classification.
Query splits via SnapshotRegistry methods: get_split(slug), get_snapshots_by_split(split).
"""

from __future__ import annotations

from enum import StrEnum


class Split(StrEnum):
    """Train/validation/test split enumeration."""

    TRAIN = "train"
    VALID = "valid"
    TEST = "test"
