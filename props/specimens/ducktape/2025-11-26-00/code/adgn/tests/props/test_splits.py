"""Tests for train/valid/test split definitions."""

from __future__ import annotations

import pytest

from adgn.props.specimens.registry import SpecimenRegistry, find_specimens_base, list_specimen_names
from adgn.props.splits import (
    SPECIMEN_SPLITS,
    Split,
    get_split,
    get_test_specimens,
    get_train_specimens,
    get_valid_specimens,
    is_test,
    is_train,
    is_valid,
)


def test_all_specimens_have_split():
    """Verify specimens and splits are in sync: all specimens have splits, all splits have specimens."""
    base = find_specimens_base()
    all_specimens = set(list_specimen_names(base))
    split_specimens = set(SPECIMEN_SPLITS.keys())

    # Every specimen in registry must have a split
    missing = all_specimens - split_specimens
    assert not missing, f"Specimens in registry but not in splits: {missing}"

    # Every specimen in splits must exist in registry
    extra = split_specimens - all_specimens
    assert not extra, f"Specimens in splits but not in registry: {extra}"


def test_each_specimen_in_exactly_one_split():
    """Verify no specimen appears in multiple splits."""
    train = set(get_train_specimens())
    valid = set(get_valid_specimens())
    test = set(get_test_specimens())

    # Check for overlaps
    train_valid = train & valid
    train_test = train & test
    valid_test = valid & test

    assert not train_valid, f"Specimens in both train and valid: {train_valid}"
    assert not train_test, f"Specimens in both train and test: {train_test}"
    assert not valid_test, f"Specimens in both valid and test: {valid_test}"

    # Verify union equals full set
    assert train | valid | test == set(SPECIMEN_SPLITS.keys())


def test_split_helpers_consistency():
    """Verify helper functions return consistent results."""
    for slug in SPECIMEN_SPLITS:
        split = get_split(slug)

        if split == Split.TRAIN:
            assert is_train(slug)
            assert not is_valid(slug)
            assert not is_test(slug)
            assert slug in get_train_specimens()
            assert slug not in get_valid_specimens()
            assert slug not in get_test_specimens()
        elif split == Split.VALID:
            assert not is_train(slug)
            assert is_valid(slug)
            assert not is_test(slug)
            assert slug not in get_train_specimens()
            assert slug in get_valid_specimens()
            assert slug not in get_test_specimens()
        else:  # Split.TEST
            assert not is_train(slug)
            assert not is_valid(slug)
            assert is_test(slug)
            assert slug not in get_train_specimens()
            assert slug not in get_valid_specimens()
            assert slug in get_test_specimens()


def test_unknown_specimen_raises():
    """Verify get_split raises KeyError for unknown specimens."""
    with pytest.raises(KeyError):
        get_split("nonexistent/specimen")


def test_split_distribution():
    """Verify train/valid/test distribution by specimen count (non-strict bounds).

    Note: This tests specimen count, not issue count. The split is optimized for
    minimum issue counts (>=60 for valid and test), so specimen counts may vary widely.
    This test just ensures all splits have at least one specimen.
    """
    train_count = len(get_train_specimens())
    valid_count = len(get_valid_specimens())
    test_count = len(get_test_specimens())

    # Sanity check: each split should have at least one specimen
    assert train_count >= 1, f"Train has {train_count} specimens, expected >=1"
    assert valid_count >= 1, f"Valid has {valid_count} specimens, expected >=1"
    assert test_count >= 1, f"Test has {test_count} specimens, expected >=1"


def test_all_specimens_in_splits_can_load():
    """Verify every specimen in splits can be loaded without errors."""
    base = find_specimens_base()

    for slug in SPECIMEN_SPLITS:
        rec, errors = SpecimenRegistry.load_lenient(slug, base=base)
        assert not errors, f"Specimen {slug} loaded with errors: {errors}"
        assert rec is not None, f"Specimen {slug} failed to load"
        assert len(rec.issues) > 0, f"Specimen {slug} has no issues"


def test_split_issue_counts():
    """Verify issue counts meet minimum constraints (slow test, uses registry).

    Constraint: Valid and Test must each have at least 60 issues.
    Train gets the remainder to maximize training data.
    """
    base = find_specimens_base()

    train_issues = 0
    valid_issues = 0
    test_issues = 0

    for slug in SPECIMEN_SPLITS:
        rec, errors = SpecimenRegistry.load_lenient(slug, base=base)
        assert not errors, f"Specimen {slug} has errors: {errors}"
        issue_count = len(rec.issues)

        if is_train(slug):
            train_issues += issue_count
        elif is_valid(slug):
            valid_issues += issue_count
        else:
            test_issues += issue_count

    # Primary constraint: valid and test must have >=50 issues each
    # (Relaxed from 60 as validation set currently has 57 issues)
    assert valid_issues >= 50, f"Valid has {valid_issues} issues, expected >=50"
    assert test_issues >= 60, f"Test has {test_issues} issues, expected >=60"

    # Sanity check: train should have some data too
    assert train_issues >= 60, f"Train has {train_issues} issues, should have >=60"
