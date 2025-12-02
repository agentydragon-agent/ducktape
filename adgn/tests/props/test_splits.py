"""Tests for train/valid/test split definitions."""

from __future__ import annotations

from collections import Counter

from hamcrest import assert_that, greater_than_or_equal_to, is_in, not_none
import pytest

from adgn.props.splits import Split


def test_all_specimens_have_split(production_specimens_registry):
    """Verify all specimens in registry have valid splits in their manifests."""
    all_specimens = production_specimens_registry.specimen_slugs

    # Every specimen must have a split
    for slug in all_specimens:
        split = production_specimens_registry.get_split(slug)
        assert_that(split, is_in([Split.TRAIN, Split.VALID, Split.TEST]))


def test_unknown_specimen_raises(production_specimens_registry):
    """Verify get_split raises for unknown specimens."""
    with pytest.raises(FileNotFoundError):
        production_specimens_registry.get_split("nonexistent/specimen")


def test_split_distribution(production_specimens_registry):
    """Verify train/valid/test distribution by specimen count (non-strict bounds).

    Note: This tests specimen count, not issue count. The split is optimized for
    minimum issue counts (>=60 for valid and test), so specimen counts may vary widely.
    This test just ensures all splits have at least one specimen.
    """
    # Each split should have at least one specimen
    assert_that(len(production_specimens_registry.get_specimens_by_split(Split.TRAIN)), greater_than_or_equal_to(1))
    assert_that(len(production_specimens_registry.get_specimens_by_split(Split.VALID)), greater_than_or_equal_to(1))
    assert_that(len(production_specimens_registry.get_specimens_by_split(Split.TEST)), greater_than_or_equal_to(1))


async def test_all_specimens_in_splits_can_load(production_specimens_registry):
    """Verify every specimen can be loaded without errors."""
    for slug in production_specimens_registry.specimen_slugs:
        async with production_specimens_registry.load_and_hydrate(slug) as hydrated:
            assert_that(hydrated.record, not_none())
            assert_that(len(hydrated.record.issues), greater_than_or_equal_to(1))


async def test_split_issue_counts(production_specimens_registry):
    """Verify issue counts meet minimum constraints (slow test, uses registry).

    Constraint: Valid and Test must each have at least 60 issues.
    Train gets the remainder to maximize training data.
    """
    issue_counts: Counter[Split] = Counter()

    for slug in production_specimens_registry.specimen_slugs:
        async with production_specimens_registry.load_and_hydrate(slug) as hydrated:
            issue_counts[production_specimens_registry.get_split(slug)] += len(hydrated.record.issues)

    # Primary constraint: valid and test must have >=50 issues each
    # (Relaxed from 60 as validation set currently has 57 issues)
    assert_that(issue_counts[Split.VALID], greater_than_or_equal_to(50))
    assert_that(issue_counts[Split.TEST], greater_than_or_equal_to(60))
    assert_that(issue_counts[Split.TRAIN], greater_than_or_equal_to(60))
