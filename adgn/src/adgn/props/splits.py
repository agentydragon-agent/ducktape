"""Train/validation/test split definitions for specimen evaluation.

Each specimen is explicitly assigned to 'train', 'valid', or 'test'.
The split is deterministic and aims for ~60/20/20 distribution by issue count.
"""

from __future__ import annotations

from enum import StrEnum


class Split(StrEnum):
    """Train/validation/test split enumeration."""

    TRAIN = "train"
    VALID = "valid"
    TEST = "test"


# Explicit train/valid/test assignment for each specimen
# Format: specimen_slug -> split_name
# Total: 304 issues across 9 specimens
# Constraint: valid and test must each have >=60 issues
SPECIMEN_SPLITS: dict[str, Split] = {
    # Train set (157 issues, 51.6%)
    "ducktape/2025-09-03-llm": Split.TRAIN,  # 71 issues
    "ducktape/2025-11-20-adgn": Split.TRAIN,  # 45 issues
    "crush/2025-08-30-internal_db": Split.TRAIN,  # 41 issues
    # Validation set (79 issues, 26.0%)
    "ducktape/2025-11-21-repo": Split.VALID,  # 39 issues
    "2025-08-29-pyright_watch_report": Split.VALID,  # 20 issues
    "ducktape/2025-11-22-repo": Split.VALID,  # 17 issues
    "2025-11-22-post-fixes": Split.VALID,  # 3 issues
    # Test set (68 issues, 22.4%)
    "ducktape/2025-11-22-repo-2": Split.TEST,  # 37 issues
    "ducktape/2025-11-20-repo": Split.TEST,  # 31 issues
}


def get_split(specimen_slug: str) -> Split:
    """Get the train/valid/test split for a specimen.

    Args:
        specimen_slug: Specimen identifier (e.g., "ducktape/2025-11-20-adgn")

    Returns:
        Split.TRAIN, Split.VALID, or Split.TEST

    Raises:
        KeyError: If specimen is not in the split mapping
    """
    return SPECIMEN_SPLITS[specimen_slug]


def get_train_specimens() -> list[str]:
    """Get list of all training specimen slugs."""
    return [slug for slug, split in SPECIMEN_SPLITS.items() if split == Split.TRAIN]


def get_valid_specimens() -> list[str]:
    """Get list of all validation specimen slugs."""
    return [slug for slug, split in SPECIMEN_SPLITS.items() if split == Split.VALID]


def get_test_specimens() -> list[str]:
    """Get list of all test specimen slugs."""
    return [slug for slug, split in SPECIMEN_SPLITS.items() if split == Split.TEST]


def is_train(specimen_slug: str) -> bool:
    """Check if specimen is in training set."""
    return get_split(specimen_slug) == Split.TRAIN


def is_valid(specimen_slug: str) -> bool:
    """Check if specimen is in validation set."""
    return get_split(specimen_slug) == Split.VALID


def is_test(specimen_slug: str) -> bool:
    """Check if specimen is in test set."""
    return get_split(specimen_slug) == Split.TEST
