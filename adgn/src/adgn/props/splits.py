"""Train/validation/test split definitions for specimen evaluation.

Each specimen is explicitly assigned to 'train', 'valid', or 'test' in its manifest.yaml.
The split assignment is the single source of truth for specimen classification.
Query splits via SpecimenRegistry methods: get_split(slug), get_specimens_by_split(split).
"""

from __future__ import annotations

from enum import StrEnum


class Split(StrEnum):
    """Train/validation/test split enumeration."""

    TRAIN = "train"
    VALID = "valid"
    TEST = "test"
