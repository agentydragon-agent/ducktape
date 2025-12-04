"""Test the ID type system (BaseIssueID, namespaced IDs, context-aware validation)."""

from pathlib import Path

from hamcrest import assert_that, equal_to, has_length, instance_of, only_contains
from pydantic import ValidationError
import pytest

from adgn.props.grader.models import GradeSubmitInput
from adgn.props.ids import FalsePositiveID, InputIssueID, SnapshotSlug, TruePositiveID
from adgn.props.paths import FileType
from adgn.props.validation_context import GradedCritiqueContext, SpecimenContext


class TestBaseIssueID:
    """Tests for BaseIssueID validation."""

    def test_valid_base_ids(self, base_issue_id_model):
        """Valid base IDs should be accepted."""
        # All of these should work
        base_issue_id_model(id="issue-001")
        base_issue_id_model(id="my_issue")
        base_issue_id_model(id="a-b-c")
        base_issue_id_model(id="abc123")

    def test_rejects_id_with_colon(self, base_issue_id_model):
        """BaseIssueID should reject IDs containing colons (reserved for namespace separator)."""
        with pytest.raises(ValidationError, match="cannot contain colon"):
            base_issue_id_model(id="TP:issue-001")

    @pytest.mark.parametrize("invalid_id", ["", "   "])
    def test_rejects_empty_id(self, base_issue_id_model, invalid_id):
        """BaseIssueID should reject empty or whitespace-only IDs."""
        with pytest.raises(ValidationError):
            base_issue_id_model(id=invalid_id)

    def test_rejects_too_short_id(self, base_issue_id_model):
        """BaseIssueID should reject IDs shorter than 5 characters."""
        with pytest.raises(ValidationError):
            base_issue_id_model(id="abc")  # Only 3 characters

    def test_rejects_too_long_id(self, base_issue_id_model):
        """BaseIssueID should reject IDs longer than 40 characters."""
        with pytest.raises(ValidationError):
            base_issue_id_model(id="a" * 41)  # 41 characters

    @pytest.mark.parametrize(("invalid_id", "reason"), [("Issue-001", "Uppercase"), ("issue@001", "Special character")])
    def test_rejects_invalid_characters(self, base_issue_id_model, invalid_id, reason):
        """BaseIssueID should reject IDs with invalid characters (must be lowercase alphanumeric, underscore, hyphen only)."""
        with pytest.raises(ValidationError):
            base_issue_id_model(id=invalid_id)


class TestNamespacedIDsWithoutContext:
    """Tests for namespaced ID construction with NewType.

    NewTypes are just wrappers - they work without context.
    """

    @pytest.mark.parametrize(
        ("id_class", "id_str"),
        [(TruePositiveID, "issue-001"), (FalsePositiveID, "false-pos"), (InputIssueID, "critique-001")],
    )
    def test_construction_works(self, id_class, id_str):
        """Namespaced IDs using NewType can be constructed from BaseIssueID strings."""
        # NewType is just a wrapper at runtime - construction always works
        result = id_class(id_str)
        # At runtime, it's just the string
        assert result == id_str
        assert isinstance(result, str)


class TestNamespacedIDsWithNewType:
    """Tests for namespaced IDs using NewType approach."""

    def test_newtype_is_runtime_string(self):
        """NewType IDs are strings at runtime."""
        tp = TruePositiveID("issue-001")
        fp = FalsePositiveID("false-pos")
        inp = InputIssueID("critique-001")

        # All are strings at runtime
        assert isinstance(tp, str)
        assert isinstance(fp, str)
        assert isinstance(inp, str)

        # Values are preserved
        assert tp == "issue-001"
        assert fp == "false-pos"
        assert inp == "critique-001"

    def test_hashable_and_usable_as_dict_keys(self):
        """NewType IDs are hashable (strings) and work as dict keys."""
        tp1 = TruePositiveID("issue-001")
        tp2 = TruePositiveID("issue-002")
        tp1_dup = TruePositiveID("issue-001")

        # Can be set members
        id_set = {tp1, tp2, tp1_dup}
        assert_that(id_set, has_length(2))  # tp1 and tp1_dup are equal

        # Can be dict keys (this is the key requirement!)
        id_dict = {tp1: "first", tp2: "second"}
        assert_that(id_dict[tp1_dup], equal_to("first"))  # Same as tp1


def test_grade_submit_uses_typed_id_dicts():
    """GradeSubmitInput should use dicts with typed NewType IDs as keys (strings at runtime)."""
    payload = GradeSubmitInput.model_validate(
        {
            "canonical_tp_coverage": {
                "issue-001": {"covered_by": {"input-001": 1.0}, "recall_credit": 1.0, "rationale": "Fully covered"},
                "issue-002": {"covered_by": {}, "recall_credit": 0.0, "rationale": "Not covered"},
            },
            "canonical_fp_coverage": {"fp-001": {"covered_by": [], "rationale": "Not matched"}},
            "novel_critique_issues": {"input-002": {"rationale": "Novel issue not in canonicals"}},
            "reported_issue_ratios": {"tp": 0.8, "fp": 0.1, "unlabeled": 0.1},
            "recall": 0.5,
            "summary": "Test summary",
            "per_file_recall": {"src/main.py": 0.5},
            "per_file_ratios": {"src/main.py": {"tp": 0.8, "fp": 0.1, "unlabeled": 0.1}},
        }
    )

    # Verify dict keys are strings (NewType is string at runtime)
    assert_that(payload.canonical_tp_coverage.keys(), only_contains(instance_of(str)))
    assert_that(payload.canonical_fp_coverage.keys(), only_contains(instance_of(str)))
    assert_that(payload.novel_critique_issues.keys(), only_contains(instance_of(str)))

    # Verify specific structure
    assert_that(payload.canonical_tp_coverage, has_length(2))
    assert_that(payload.canonical_fp_coverage, has_length(1))
    assert_that(payload.novel_critique_issues, has_length(1))


def test_grade_submit_serialization_round_trip():
    """GradeSubmitInput should serialize and deserialize correctly."""
    original = GradeSubmitInput.model_validate(
        {
            "canonical_tp_coverage": {
                "issue-001": {
                    "covered_by": {"input-001": 1.0},
                    "recall_credit": 1.0,
                    "rationale": "Fully matched the canonical issue",
                }
            },
            "canonical_fp_coverage": {},
            "novel_critique_issues": {},
            "reported_issue_ratios": {"tp": 1.0, "fp": 0.0, "unlabeled": 0.0},
            "recall": 1.0,
            "summary": "All issues were matched correctly",
            "per_file_recall": {"src/example.py": 1.0},
            "per_file_ratios": {"src/example.py": {"tp": 1.0, "fp": 0.0, "unlabeled": 0.0}},
        }
    )

    # Serialize
    dumped = original.model_dump(mode="json")

    # Deserialize and compare
    assert_that(GradeSubmitInput.model_validate(dumped), equal_to(original))


class TestValidationContexts:
    """Tests for validation context classes."""

    def test_specimen_context_from_hydrated_specimen(self, tmp_path: Path):
        """SpecimenContext.from_hydrated_specimen should build context correctly."""
        # Create a fake hydrated specimen
        (tmp_path / "file1.py").write_text("# test")
        (tmp_path / "file2.txt").write_text("test")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "file3.py").write_text("# test")

        ctx = SpecimenContext.from_hydrated_specimen(
            snapshot_slug=SnapshotSlug("test/specimen"),
            hydrated_root=tmp_path,
            specimen_issues={"issue-001", "issue-002"},
            specimen_fps={"false-pos"},
        )

        # Check snapshot_slug
        assert_that(ctx.snapshot_slug, equal_to(SnapshotSlug("test/specimen")))

        # Check allowed IDs
        assert_that(ctx.allowed_tp_ids, equal_to(frozenset(["issue-001", "issue-002"])))
        assert_that(ctx.allowed_fp_ids, equal_to(frozenset(["false-pos"])))

        # Check all_discovered_files includes all files (relative paths)
        assert Path("file1.py") in ctx.all_discovered_files
        assert Path("file2.txt") in ctx.all_discovered_files
        assert Path("subdir") in ctx.all_discovered_files
        assert Path("subdir/file3.py") in ctx.all_discovered_files

        # Check file types
        assert_that(ctx.all_discovered_files[Path("file1.py")], equal_to(FileType.REGULAR))
        assert_that(ctx.all_discovered_files[Path("subdir")], equal_to(FileType.DIRECTORY))

    def test_graded_critique_context_construction(self):
        """GradedCritiqueContext construction with frozenset."""
        ctx = GradedCritiqueContext(allowed_input_ids=frozenset(["critique-001", "critique-002"]))

        assert_that(ctx.allowed_input_ids, equal_to(frozenset(["critique-001", "critique-002"])))
