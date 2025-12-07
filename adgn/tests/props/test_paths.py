"""Tests for path type system (FileType, classify_path, SnapshotRelativePath)."""

from pathlib import Path

from hamcrest import assert_that, contains_inanyorder, equal_to, instance_of
from pydantic import ValidationError
import pytest

from adgn.props.ids import SnapshotSlug
from adgn.props.paths import FileType, classify_path
from adgn.props.validation_context import SnapshotContext


@pytest.fixture
def mock_snapshot_context(tmp_path: Path) -> SnapshotContext:
    """Create a minimal snapshot context with a few mock files for testing."""
    # Create a minimal file structure
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text("# mock")
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "utils").mkdir()
    (tmp_path / "lib" / "utils" / "helpers.py").write_text("# mock")
    (tmp_path / "README.md").write_text("# mock")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b").mkdir()
    (tmp_path / "a" / "b" / "c").mkdir()
    (tmp_path / "a" / "b" / "c" / "d").mkdir()
    (tmp_path / "a" / "b" / "c" / "d" / "file.txt").write_text("# mock")
    (tmp_path / "single.txt").write_text("# mock")
    (tmp_path / "src" / "file.test.py").write_text("# mock")

    return SnapshotContext.from_hydrated_snapshot(
        snapshot_slug=SnapshotSlug("test/mock"), hydrated_root=tmp_path, snapshot_issues=[], snapshot_fps=[]
    )


def test_classify_symlink_to_file(tmp_path: Path):
    """classify_path should identify symlinks (not the target type)."""
    target = tmp_path / "target.txt"
    target.write_text("content")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    assert_that(classify_path(link), equal_to(FileType.SYMLINK))


def test_classify_nonexistent_returns_other(tmp_path: Path):
    """classify_path should return OTHER for nonexistent paths."""
    nonexistent = tmp_path / "does_not_exist"
    assert_that(classify_path(nonexistent), equal_to(FileType.OTHER))


# SnapshotRelativePath validation tests


@pytest.mark.parametrize("path_str", ["src/module.py", "README.md", "a/b/c/d/file.txt"])
def test_valid_relative_paths(validate_snapshot_path, mock_snapshot_context: SnapshotContext, path_str: str):
    """Valid relative paths should be accepted with context."""
    m = validate_snapshot_path(path_str, mock_snapshot_context)
    assert_that(str(m.path), equal_to(path_str))


def test_accepts_string_or_path_input(snapshot_relative_path_model, mock_snapshot_context: SnapshotContext):
    """SnapshotRelativePath should accept both string and Path inputs."""
    ctx = {"snapshots": mock_snapshot_context}

    # String input
    m1 = snapshot_relative_path_model.model_validate({"path": "src/module.py"}, context=ctx)
    assert_that(m1.path, instance_of(Path))

    # Path input
    m2 = snapshot_relative_path_model.model_validate({"path": Path("src/module.py")}, context=ctx)
    assert_that(m2.path, instance_of(Path))

    # Both should be equal
    assert_that(m1.path, equal_to(m2.path))


@pytest.mark.parametrize(
    ("path_str", "error_match"),
    [
        ("/src/module.py", "absolute"),
        ("../other/file.py", "parent references"),
        ("src/../lib/file.py", "parent references"),
        ("", "empty"),
    ],
)
def test_rejects_invalid_format(snapshot_relative_path_model, path_str, error_match):
    """Format validation should reject invalid paths (no context needed)."""
    with pytest.raises(ValidationError, match=error_match):
        snapshot_relative_path_model(path=path_str)


def test_validation_without_context_skips_existence_check(snapshot_relative_path_model):
    """Without snapshots, validation skips existence check (allows standalone parsing).

    This enables parsing critiques without loading full specimen context.
    Format validation (relative path, no ..) still applies.
    """
    # Should succeed - format validation passes, existence check skipped
    result = snapshot_relative_path_model(path="nonexistent/file.py")
    assert str(result.path) == "nonexistent/file.py"


def test_validation_with_wrong_context_key_skips_existence_check(snapshot_relative_path_model):
    """With context dict but no snapshots key, existence check is skipped."""
    # Should succeed - format validation passes, existence check skipped
    result = snapshot_relative_path_model.model_validate({"path": "nonexistent.py"}, context={"other_key": "value"})
    assert str(result.path) == "nonexistent.py"


def test_validation_with_context_checks_existence(
    validate_snapshot_path, snapshot_relative_path_model, mock_snapshot_context: SnapshotContext
):
    """With snapshots, paths must exist in known_files."""
    # Existing file should pass
    m = validate_snapshot_path("src/module.py", mock_snapshot_context)
    assert_that(m.path, equal_to(Path("src/module.py")))

    # Non-existent file should fail
    ctx = {"snapshots": mock_snapshot_context}
    with pytest.raises(ValidationError, match="not found"):
        snapshot_relative_path_model.model_validate({"path": "nonexistent.py"}, context=ctx)


def test_validation_rejects_symlinks(snapshot_relative_path_model, tmp_path: Path):
    """With context, symlinks should be rejected as issue anchors."""
    # Create a symlink
    target = tmp_path / "target.py"
    target.write_text("# mock")
    link = tmp_path / "link.py"
    link.symlink_to(target)

    ctx_obj = SnapshotContext.from_hydrated_snapshot(
        snapshot_slug=SnapshotSlug("test/symlink"), hydrated_root=tmp_path, snapshot_issues=[], snapshot_fps=[]
    )

    with pytest.raises(ValidationError, match="regular file"):
        snapshot_relative_path_model.model_validate({"path": "link.py"}, context={"snapshots": ctx_obj})


def test_validation_rejects_directories(snapshot_relative_path_model, tmp_path: Path):
    """With context, directories should be rejected as issue anchors."""
    (tmp_path / "src").mkdir()

    ctx_obj = SnapshotContext.from_hydrated_snapshot(
        snapshot_slug=SnapshotSlug("test/dir"), hydrated_root=tmp_path, snapshot_issues=[], snapshot_fps=[]
    )

    with pytest.raises(ValidationError, match="regular file"):
        snapshot_relative_path_model.model_validate({"path": "src"}, context={"snapshots": ctx_obj})


def test_validation_multiple_files_in_known_files(
    validate_snapshot_path, snapshot_relative_path_model, mock_snapshot_context: SnapshotContext
):
    """Test validation with multiple files in known_files."""
    # All regular files should pass
    validate_snapshot_path("src/module.py", mock_snapshot_context)
    validate_snapshot_path("README.md", mock_snapshot_context)
    validate_snapshot_path("single.txt", mock_snapshot_context)

    # Unknown file should fail
    ctx = {"snapshots": mock_snapshot_context}
    with pytest.raises(ValidationError, match="not found"):
        snapshot_relative_path_model.model_validate({"path": "unknown.py"}, context=ctx)


# Serialization tests


def test_json_serialization(validate_snapshot_path, mock_snapshot_context: SnapshotContext):
    """SnapshotRelativePath should serialize to string in JSON mode."""
    m = validate_snapshot_path("src/module.py", mock_snapshot_context)
    json_data = m.model_dump(mode="json")
    assert_that(json_data["path"], equal_to("src/module.py"))


def test_python_serialization_returns_path(validate_snapshot_path, mock_snapshot_context: SnapshotContext):
    """SnapshotRelativePath should return Path in Python mode."""
    m = validate_snapshot_path("src/module.py", mock_snapshot_context)
    python_data = m.model_dump(mode="python")
    assert_that(python_data["path"], equal_to(Path("src/module.py")))


def test_round_trip(validate_snapshot_path, snapshot_relative_path_model, mock_snapshot_context: SnapshotContext):
    """SnapshotRelativePath should round-trip through JSON."""
    ctx = {"snapshots": mock_snapshot_context}
    m1 = validate_snapshot_path("src/module.py", mock_snapshot_context)
    json_str = m1.model_dump_json()
    m2 = snapshot_relative_path_model.model_validate_json(json_str, context=ctx)
    assert_that(m1.path, equal_to(m2.path))


def test_round_trip_via_dict(
    validate_snapshot_path, snapshot_relative_path_model, mock_snapshot_context: SnapshotContext
):
    """SnapshotRelativePath can round-trip through dict (workaround for JSON issue)."""
    ctx = {"snapshots": mock_snapshot_context}
    m1 = validate_snapshot_path("src/module.py", mock_snapshot_context)
    json_dict = m1.model_dump(mode="json")
    m2 = snapshot_relative_path_model.model_validate(json_dict, context=ctx)
    assert_that(m1.path, equal_to(m2.path))
    assert_that(m2.path, equal_to(Path("src/module.py")))


# Edge cases


def test_single_component_path(validate_snapshot_path, mock_snapshot_context: SnapshotContext):
    """Single component paths should work (e.g., README.md)."""
    m = validate_snapshot_path("README.md", mock_snapshot_context)
    assert_that(m.path, equal_to(Path("README.md")))


def test_path_with_dots_in_filename(validate_snapshot_path, mock_snapshot_context: SnapshotContext):
    """Paths with dots in filename (not ..) should work."""
    m = validate_snapshot_path("src/file.test.py", mock_snapshot_context)
    assert_that(m.path, equal_to(Path("src/file.test.py")))


def test_path_normalization(validate_snapshot_path, mock_snapshot_context: SnapshotContext):
    """Path should be normalized (extra slashes removed)."""
    # Path constructor normalizes this
    m = validate_snapshot_path("src//module.py", mock_snapshot_context)
    # Path normalizes to src/module.py
    assert_that(m.path.parts, contains_inanyorder("src", "module.py"))
