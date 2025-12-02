"""Load specimens as DSPy examples."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import dspy

if TYPE_CHECKING:
    from adgn.props.specimens.hydrated import HydratedSpecimen
    from adgn.props.specimens.registry import IssueRecord, SpecimenRegistry

from adgn.props.splits import Split


@dataclass
class SpecimenExample:
    """Specimen loaded as a DSPy-compatible example.

    Contains both the DSPy Example object and metadata needed for evaluation.
    """

    dspy_example: dspy.Example
    slug: str
    split: Split
    ground_truth_issues: list[dict]  # For metric computation
    known_false_positives: list[dict]

    @property
    def target_files(self) -> list[str]:
        return self.dspy_example.target_files


def _issue_record_to_dict(issue_id: str, record: "IssueRecord") -> dict:
    """Convert IssueRecord to dict for DSPy."""
    return {
        "id": issue_id,
        "rationale": record.core.rationale,
        "occurrences": [
            {
                "files": {str(f): lines for f, lines in occ.files.items()},
                "notes": occ.notes,
            }
            for occ in record.instances
        ],
    }


def specimen_to_example(slug: str, hydrated: "HydratedSpecimen", split: Split) -> SpecimenExample:
    """Convert a hydrated specimen to a DSPy example.

    Args:
        slug: Specimen slug (e.g., 'ducktape/2025-11-20-00')
        hydrated: Hydrated specimen with issues and content
        split: Train/valid/test split assignment

    Returns:
        SpecimenExample containing DSPy Example and metadata
    """
    # Get files with issues as target files
    target_files = [str(f) for f in hydrated.files_with_issues()]

    # Convert ground truth issues to dicts
    ground_truth = [_issue_record_to_dict(issue_id, record) for issue_id, record in hydrated.issues.items()]

    # Convert known false positives
    known_fps = [_issue_record_to_dict(fp_id, record) for fp_id, record in hydrated.false_positives.items()]

    # Create DSPy example with inputs
    # Note: we don't include expected issues in the Example because
    # DSPy's ReAct doesn't use them directly - the metric function does
    example = dspy.Example(
        specimen_slug=slug,
        target_files=target_files,
    ).with_inputs("specimen_slug", "target_files")

    return SpecimenExample(
        dspy_example=example,
        slug=slug,
        split=split,
        ground_truth_issues=ground_truth,
        known_false_positives=known_fps,
    )


async def load_specimens_as_examples(
    registry: "SpecimenRegistry",
    split: Split | None = None,
) -> list[SpecimenExample]:
    """Load specimens from registry as DSPy examples.

    Args:
        registry: SpecimenRegistry instance
        split: Optional filter by split (None = all specimens)

    Returns:
        List of SpecimenExample objects
    """
    examples = []

    # Get specimen slugs, optionally filtered by split
    if split is not None:
        slugs = registry.get_specimens_by_split(split)
    else:
        slugs = list(registry.list_specimens())

    for slug in slugs:
        specimen_split = registry.get_split(slug)
        if specimen_split is None:
            continue

        # Load and hydrate specimen
        async with registry.load_and_hydrate(slug) as hydrated:
            example = specimen_to_example(slug, hydrated, specimen_split)
            examples.append(example)

    return examples


def split_examples(
    examples: list[SpecimenExample],
) -> tuple[list[SpecimenExample], list[SpecimenExample], list[SpecimenExample]]:
    """Split examples by their assigned split.

    Returns:
        (train, valid, test) tuple of example lists
    """
    train = [ex for ex in examples if ex.split == Split.TRAIN]
    valid = [ex for ex in examples if ex.split == Split.VALID]
    test = [ex for ex in examples if ex.split == Split.TEST]
    return train, valid, test
