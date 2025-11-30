"""Hydrated specimen - single object containing record + content root."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from adgn.props.models.specimen import SpecimenDoc
from adgn.props.paths import FileType

# Direct import - circular dependency is broken by deferred import in registry.py
from adgn.props.specimens.registry import IssueRecord, SpecimenRecord


@dataclass
class HydratedSpecimen:
    """Single object containing specimen record + hydrated content root.

    Replaces awkward tuple unpacking from load_and_hydrate().
    Provides convenient access to specimen data and the hydrated working tree.

    Example:
        async with SpecimenRegistry.load_and_hydrate("ducktape/2025-11-20") as hydrated:
            # Access specimen data
            files = hydrated.all_discovered_files
            issues = hydrated.issues

            # Access hydrated content
            wiring = properties_docker_spec(hydrated.content_root, ...)
    """

    record: SpecimenRecord
    content_root: Path

    # Convenience properties (delegate to record)
    @property
    def manifest(self) -> SpecimenDoc:
        """Specimen manifest (source, bundle)."""
        return self.record.manifest

    @property
    def all_discovered_files(self) -> dict[Path, FileType]:
        """All files discovered during hydration (includes files without ground truth issues)."""
        return self.record.all_discovered_files

    @property
    def slug(self) -> str:
        """Specimen slug (e.g., 'ducktape/2025-11-20')."""
        return self.record.slug

    @property
    def issues(self) -> dict[str, IssueRecord]:
        """True positive issues (canonical ground truth)."""
        return self.record.issues

    @property
    def false_positives(self) -> dict[str, IssueRecord]:
        """Known false positives."""
        return self.record.false_positives

    def files_with_issues(self) -> set[Path]:
        """Return files that have known ground truth TP or FP issues.

        Returns:
            Set of relative paths mentioned in issues or false_positives.
        """
        from itertools import chain

        return set(
            chain.from_iterable(
                occurrence.files.keys()
                for issue_record in chain(self.issues.values(), self.false_positives.values())
                for occurrence in issue_record.instances
            )
        )
