"""Shared test fixtures for props tests."""

from collections.abc import Iterable
import hashlib
import inspect
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel
import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text

from adgn.openai_utils.model import AssistantMessageOut, OutputText, ResponsesResult
from adgn.props.critic.models import CriticSubmitPayload, CriticSuccess, ReportedIssue
from adgn.props.db import dispose_db, get_session, init_db, recreate_database
from adgn.props.db.config import get_database_config
from adgn.props.db.models import Critique, FalsePositive, Snapshot, TruePositive
from adgn.props.db.prompts import hash_and_upsert_prompt
from adgn.props.db.setup import ensure_database_exists
from adgn.props.db.snapshots import (
    DBCriticContextLengthExceeded,
    DBCriticMaxTurnsExceeded,
    DBCriticOutput,
    DBCriticSubmitPayload,
    DBCriticSuccess,
    DBGraderOutput,
    DBReportedIssue,
)
from adgn.props.db.sync import get_specimens_base_path, sync_examples_to_db, sync_issues_to_db, sync_snapshots_to_db
from adgn.props.files_hash import hash_file_set
from adgn.props.grader.models import (
    GraderInput,
    GraderSuccess,
    InputIssueID,
    OccurrenceResult,
    TruePositiveID,
    UnknownIssue,
)
from adgn.props.grader.persistence import grader_success_to_db
from adgn.props.hydration import SnapshotHydrator
from adgn.props.ids import SnapshotSlug
from adgn.props.models.snapshot import LocalSource
from adgn.props.models.true_positive import FalsePositiveOccurrence, LineRange, TruePositiveOccurrence
from adgn.props.rationale import Rationale
from adgn.props.runs_context import RunsContext
from tests.llm.support.openai_mock import FakeOpenAIModel


@pytest.fixture(autouse=True)
def block_production_config_in_tests(monkeypatch):
    """Prevent test functions from accidentally using production database.

    Tests should use the test_db fixture, which creates isolated test databases.
    Calling get_database_config() from test code is a bug - it returns production
    database credentials instead of the test-specific isolated database.

    This fixture blocks ALL calls to get_database_config() from test files.
    Production code (like database session management, Alembic offline mode) can
    still call it normally.
    """

    original = get_database_config

    def _block_from_tests(*args, **kwargs):
        # Check the immediate caller (frame 1)
        stack = inspect.stack()
        if len(stack) > 1:
            caller_frame = stack[1]
            caller_file = caller_frame.filename
            # If called from a test file, fail
            if "/tests/" in caller_file and caller_file.endswith(".py"):
                raise RuntimeError(
                    f"Tests must use test_db fixture, not get_database_config()!\n"
                    f"Called from: {caller_file}:{caller_frame.lineno}\n"
                    f"Fix: Use 'config = test_db' instead of 'get_database_config()'."
                )
        # Called from production code - allow it
        return original(*args, **kwargs)

    monkeypatch.setattr("adgn.props.db.config.get_database_config", _block_from_tests)

    # Return original for test_db fixture to use
    return original


# Common test data for database fixtures
TEST_FILES_LIST = ["test.py"]
TEST_FILES = {Path(f) for f in TEST_FILES_LIST}
TEST_FILES_HASH = hash_file_set(TEST_FILES)


def make_grader_output(
    tp_count: int = 1, summary: str = "Test grader output", found_credit: float = 0.0, unknowns: list[str] | None = None
) -> DBGraderOutput:
    """Build test grader output with per-occurrence results.

    Args:
        tp_count: Number of test occurrences to create (default: 1)
        summary: Summary text (default: "Test grader output")
        found_credit: Credit for each occurrence (0.0 = not found, 1.0 = fully found). Default: 0.0
        unknowns: Optional list of unknown issue IDs (unlabeled issues found by critic)

    Returns:
        DBGraderSuccess with specified parameters (or DBGraderOutput for unknowns)

    Example:
        # Create output with 80% recall across all occurrences
        output = make_grader_output(tp_count=5, found_credit=0.8)

        # Create output with unknowns (unlabeled issues)
        output = make_grader_output(tp_count=2, unknowns=["unknown-001", "unknown-002"])
    """
    occurrence_results = [
        OccurrenceResult(
            tp_id=TruePositiveID(f"tp-{i:03d}"),
            occurrence_id=f"occ-{i:03d}",
            found_credit=found_credit,
            matched_by=[],
            rationale=Rationale(
                "Test occurrence - not found" if found_credit == 0.0 else f"Test occurrence (credit={found_credit})"
            ),
        )
        for i in range(1, tp_count + 1)
    ]

    grader_success = GraderSuccess(
        occurrence_results=occurrence_results,
        summary=Rationale(summary),
        unknowns=[UnknownIssue(input_id=InputIssueID(u), rationale=Rationale(f"Unknown issue: {u}")) for u in unknowns]
        if unknowns
        else [],
    )
    return grader_success_to_db(grader_success)


def make_critic_success(issues: list[DBReportedIssue] | None = None, notes_md: str | None = None) -> DBCriticOutput:
    """Build successful critic output for test storage.

    Uses actual Pydantic DB models to ensure test data matches the schema.

    Args:
        issues: List of reported issues (empty list if None)
        notes_md: Optional notes in markdown

    Returns:
        DBCriticSuccess with the provided payload
    """
    return DBCriticSuccess(result=DBCriticSubmitPayload(issues=issues or [], notes_md=notes_md))


def make_critic_max_turns_exceeded(max_turns: int = 10) -> DBCriticOutput:
    """Build max_turns_exceeded critic output for test storage.

    Args:
        max_turns: Maximum turns that were allowed

    Returns:
        DBCriticMaxTurnsExceeded with the provided max_turns
    """
    return DBCriticMaxTurnsExceeded(max_turns=max_turns)


def make_critic_context_length_exceeded(error_message: str = "Context length exceeded") -> DBCriticOutput:
    """Build context_length_exceeded critic output for test storage.

    Args:
        error_message: Error message from the API

    Returns:
        DBCriticContextLengthExceeded with the provided error message
    """
    return DBCriticContextLengthExceeded(error_message=error_message)


def make_critique_payload(issues: list[DBReportedIssue] | None = None, notes_md: str = "") -> DBCriticSubmitPayload:
    """Build critique payload (for Critique.payload field) for test storage.

    Args:
        issues: List of reported issues (empty list if None)
        notes_md: Notes in markdown (empty string by default)

    Returns:
        DBCriticSubmitPayload with the provided data
    """
    return DBCriticSubmitPayload(issues=issues or [], notes_md=notes_md)


# ============================================================================
# Test Fixture Builders (Pydantic models, not dicts!)
# ============================================================================


def make_tp_occurrence(
    occurrence_id: str = "occ-1",
    files: dict[str | Path, list[dict | LineRange] | None] | None = None,
    expect_caught_from: Iterable[Iterable[str | Path]] | set[frozenset[Path]] | None = None,
    note: str | None = None,
) -> TruePositiveOccurrence:
    """Build TruePositiveOccurrence with proper Pydantic types.

    Converts test-friendly inputs (strings, dicts) to Pydantic types (Paths, LineRange objects).

    Args:
        occurrence_id: Unique ID within the TP (default: "occ-1")
        files: File paths with optional line ranges. Accepts:
            - None (default): Single file "test.py" with no ranges
            - {"file.py": None}: File with no line ranges
            - {"file.py": [{"start_line": 1, "end_line": 10}]}: File with line range dict
            - {"file.py": [LineRange(start_line=1, end_line=10)]}: File with LineRange object
            - {Path("file.py"): [...]}: Path keys (already typed)
        expect_caught_from: Minimal file sets for detection. Accepts:
            - None (default): Single trigger set containing "test.py"
            - [["file.py"]]: List of lists of strings (converted to set[frozenset[Path]])
            - [[Path("file.py")]]: List of lists of Paths (converted to set[frozenset[Path]])
            - {frozenset([Path("file.py")])}: Set of frozensets of Paths (proper type)
        note: Occurrence-specific note (optional)

    Returns:
        TruePositiveOccurrence with validated Pydantic types

    Examples:
        # Simple file, no line range (most common):
        make_tp_occurrence(files={"test.py": None})

        # File with line range:
        make_tp_occurrence(
            files={"server.py": [{"start_line": 10, "end_line": 20}]}
        )

        # Multiple trigger sets (OR logic):
        make_tp_occurrence(
            expect_caught_from=[["file1.py"], ["file2.py"]]
        )

        # Trigger set requiring multiple files (AND logic):
        make_tp_occurrence(
            expect_caught_from=[["client.py", "utils.py"]]
        )
    """
    # Default: single file with no ranges
    if files is None:
        files_typed: dict[Path, list[LineRange] | None] = {Path("test.py"): None}
    else:
        # Convert string keys to Paths and dict line ranges to LineRange objects
        files_typed = {}
        for file_key, ranges in files.items():
            path = Path(file_key) if isinstance(file_key, str) else file_key

            if ranges is None:
                files_typed[path] = None
            else:
                # Convert dict line ranges to LineRange objects
                ranges_typed = []
                for r in ranges:
                    if isinstance(r, dict):
                        ranges_typed.append(LineRange(**r))
                    else:
                        ranges_typed.append(r)
                files_typed[path] = ranges_typed

    # Default: single trigger set containing first file
    if expect_caught_from is None:
        first_file = next(iter(files_typed.keys()))
        expect_caught_from_typed: set[frozenset[Path]] = {frozenset([first_file])}
    elif isinstance(expect_caught_from, set):
        # Already proper type
        expect_caught_from_typed = expect_caught_from
    else:
        # Convert iterable[iterable[str|Path]] to set[frozenset[Path]]
        expect_caught_from_typed = {
            frozenset(Path(f) if isinstance(f, str) else f for f in fs) for fs in expect_caught_from
        }

    return TruePositiveOccurrence(
        occurrence_id=occurrence_id, files=files_typed, note=note, expect_caught_from=expect_caught_from_typed
    )


def make_fp_occurrence(
    occurrence_id: str = "occ-1",
    files: dict[str | Path, list[dict | LineRange] | None] | None = None,
    relevant_files: Iterable[str | Path] | set[Path] | None = None,
    note: str | None = None,
) -> FalsePositiveOccurrence:
    """Build FalsePositiveOccurrence with proper Pydantic types.

    Converts test-friendly inputs (strings, dicts) to Pydantic types (Paths, LineRange objects).

    Args:
        occurrence_id: Unique ID within the FP (default: "occ-1")
        files: File paths with optional line ranges (same format as make_tp_occurrence)
        relevant_files: Files that make this FP relevant. Accepts:
            - None (default): Single file "test.py"
            - ["file.py"]: List of strings (converted to set of Paths)
            - {Path("file.py")}: Set of Paths (proper type)
        note: Occurrence-specific note (optional)

    Returns:
        FalsePositiveOccurrence with validated Pydantic types

    Examples:
        # Simple FP:
        make_fp_occurrence(
            files={"helper.py": None},
            relevant_files=["helper.py"]
        )
    """
    # Reuse file conversion logic from make_tp_occurrence
    if files is None:
        files_typed: dict[Path, list[LineRange] | None] = {Path("test.py"): None}
    else:
        files_typed = {}
        for file_key, ranges in files.items():
            path = Path(file_key) if isinstance(file_key, str) else file_key

            if ranges is None:
                files_typed[path] = None
            else:
                ranges_typed = []
                for r in ranges:
                    if isinstance(r, dict):
                        ranges_typed.append(LineRange(**r))
                    else:
                        ranges_typed.append(r)
                files_typed[path] = ranges_typed

    # Default: first file from files dict
    if relevant_files is None:
        first_file = next(iter(files_typed.keys()))
        relevant_files_typed: set[Path] = {first_file}
    elif isinstance(relevant_files, set):
        # Already proper type
        relevant_files_typed = relevant_files
    else:
        # Convert iterable[str|Path] to set[Path]
        relevant_files_typed = {Path(f) if isinstance(f, str) else f for f in relevant_files}

    return FalsePositiveOccurrence(
        occurrence_id=occurrence_id, files=files_typed, note=note, relevant_files=relevant_files_typed
    )


# ============================================================================
# TruePositive / FalsePositive Builders
# ============================================================================


def make_true_positive(
    snapshot_slug: str,
    tp_id: str = "tp-test",
    rationale: str = "Test true positive",
    occurrences: list[TruePositiveOccurrence | dict] | None = None,
) -> TruePositive:
    """Build TruePositive with single occurrence by default.

    Args:
        snapshot_slug: Snapshot this TP belongs to
        tp_id: Unique ID for this TP (default: "tp-test")
        rationale: Why this is an issue (default: generic message)
        occurrences: List of occurrences. Accepts:
            - None (default): Single occurrence via make_tp_occurrence()
            - [TruePositiveOccurrence(...)]: List of properly typed occurrences
            - [{"occurrence_id": ..., "files": ...}]: List of dicts (converted)

    Returns:
        TruePositive ORM model (not yet added to session)

    Examples:
        # Simple TP (single file, single occurrence):
        make_true_positive("train/spec-a")

        # TP with custom ID and files:
        make_true_positive(
            "train/spec-a",
            tp_id="dead-import",
            rationale="Unused import detected",
            occurrences=[
                make_tp_occurrence(
                    occurrence_id="occ-1",
                    files={"server.py": [{"start_line": 5, "end_line": 5}]},
                    expect_caught_from=[["server.py"]],
                )
            ],
        )

        # Multiple occurrences (same logical issue in different places):
        make_true_positive(
            "train/spec-b",
            tp_id="duplicated-enum",
            occurrences=[
                make_tp_occurrence("occ-1", files={"types.py": None}),
                make_tp_occurrence("occ-2", files={"persist.py": None}),
            ],
        )
    """
    if occurrences is None:
        occurrences_typed = [make_tp_occurrence()]
    else:
        # Convert any dict occurrences to TruePositiveOccurrence
        occurrences_typed = []
        for occ in occurrences:
            if isinstance(occ, dict):
                # Convert dict to TruePositiveOccurrence via make_tp_occurrence
                occurrences_typed.append(make_tp_occurrence(**occ))
            else:
                occurrences_typed.append(occ)

    return TruePositive(
        snapshot_slug=SnapshotSlug(snapshot_slug), tp_id=tp_id, rationale=rationale, occurrences=occurrences_typed
    )


def make_false_positive(
    snapshot_slug: str,
    fp_id: str = "fp-test",
    rationale: str = "Test false positive (acceptable pattern)",
    occurrences: list[FalsePositiveOccurrence | dict] | None = None,
) -> FalsePositive:
    """Build FalsePositive with single occurrence by default.

    Args:
        snapshot_slug: Snapshot this FP belongs to
        fp_id: Unique ID for this FP (default: "fp-test")
        rationale: Why this is acceptable (default: generic message)
        occurrences: List of occurrences (same pattern as make_true_positive)

    Returns:
        FalsePositive ORM model (not yet added to session)

    Examples:
        # Simple FP:
        make_false_positive(
            "train/spec-a",
            fp_id="intentional-duplication",
            rationale="Visual consistency in UI components",
        )
    """
    if occurrences is None:
        occurrences_typed = [make_fp_occurrence()]
    else:
        occurrences_typed = []
        for occ in occurrences:
            if isinstance(occ, dict):
                occurrences_typed.append(make_fp_occurrence(**occ))
            else:
                occurrences_typed.append(occ)

    return FalsePositive(
        snapshot_slug=SnapshotSlug(snapshot_slug), fp_id=fp_id, rationale=rationale, occurrences=occurrences_typed
    )


# ============================================================================
# Other Model Builders
# ============================================================================


def make_test_snapshot(slug: str, split: str = "train") -> Snapshot:
    """Build test snapshot with default LocalSource.

    Args:
        slug: Snapshot slug (e.g., "train/spec-a")
        split: Split assignment ("train", "valid", or "test")

    Returns:
        Snapshot ORM model (not yet added to session)

    Examples:
        make_test_snapshot("train/spec-a")
        make_test_snapshot("valid/spec-b", split="valid")
    """
    return Snapshot(slug=SnapshotSlug(slug), split=split, source=LocalSource(vcs="local", root="."))


def make_critique(
    snapshot_slug: str, issues: list[ReportedIssue] | None = None, critique_id: UUID | None = None, notes_md: str = ""
) -> Critique:
    """Build critique with minimal issues.

    Args:
        snapshot_slug: Snapshot this critique belongs to
        issues: List of reported issues (default: empty list)
        critique_id: UUID for this critique (default: random UUID)
        notes_md: Markdown notes (default: empty string)

    Returns:
        Critique ORM model (not yet added to session)

    Examples:
        # Empty critique:
        make_critique("train/spec-a")

        # Critique with specific ID and issues:
        critique_id = uuid4()
        make_critique(
            "train/spec-a",
            issues=[...],
            critique_id=critique_id,
        )
    """
    if critique_id is None:
        critique_id = uuid4()
    if issues is None:
        issues = []

    return Critique(
        id=critique_id,
        snapshot_slug=SnapshotSlug(snapshot_slug),
        payload=CriticSubmitPayload(issues=issues, notes_md=notes_md),
    )


@pytest.fixture
def test_prompt_sha():
    """Create and return a test prompt hash (upserts to DB once)."""
    return hash_and_upsert_prompt("test prompt for database tests")


@pytest.fixture
def rationale_model():
    """Fixture providing a Pydantic model with Rationale field."""

    class Model(BaseModel):
        rationale: Rationale

    return Model


# === Snapshot Hydrator Fixtures (DI Pattern) ===
# Two explicit hydrators:
# 1. production_specimens_hydrator - for real specimens (src/adgn/props/specimens/)
# 2. test_specimens_hydrator - for test fixtures (tests/props/fixtures/specimens/)


@pytest.fixture
def production_specimens_hydrator() -> SnapshotHydrator:
    """Production specimens hydrator from ADGN_PROPS_SPECIMENS_ROOT environment variable.

    Uses specimens from the external specimens repository.
    """
    return SnapshotHydrator.from_env()


@pytest.fixture
def test_specimens_base() -> Path:
    """Base directory for test-only fixture specimens.

    Returns path to tests/props/fixtures/specimens/ which contains
    minimal specimens for testing specific scenarios.
    """
    return Path(__file__).parent / "fixtures" / "specimens"


@pytest.fixture
def test_specimens_hydrator(test_specimens_base: Path) -> SnapshotHydrator:
    """Test fixtures specimens hydrator (DI pattern - no monkeypatching).

    Uses test fixtures from tests/props/fixtures/specimens/ which contains
    minimal test-only specimens like test-trivial.
    """
    return SnapshotHydrator(test_specimens_base)


@pytest_asyncio.fixture
async def loaded_specimen(production_specimens_hydrator, test_db):
    """Load a real specimen using hydrator.

    Yields HydratedSnapshot object (content_root + all_discovered_files).
    Issues must be loaded separately from database via ORM.

    Uses ducktape/2025-11-22-02 as the canonical test specimen.
    Depends on test_db to ensure database is initialized before hydration.
    """
    async with production_specimens_hydrator.hydrate("ducktape/2025-11-22-02") as hydrated:
        yield hydrated


@pytest.fixture
def test_trivial_snapshot_record(test_db):
    """Create database record for test-trivial specimen.

    Must run before hydration to ensure snapshot exists in database.
    """
    slug = "test-fixtures/test-trivial"
    with get_session() as session:
        spec_record = Snapshot(slug=slug, split="test", source=LocalSource(vcs="local", root="."))
        session.add(spec_record)
        session.commit()
    return slug


@pytest_asyncio.fixture
async def test_trivial_specimen(test_specimens_hydrator, test_trivial_snapshot_record):
    """Load test-trivial fixture specimen (clean Python code, zero issues).

    Test-only specimen for validating zero-issues case.
    Lives in tests/props/fixtures/specimens/test-fixtures/test-trivial/.
    Uses DI - no monkeypatching needed.
    Depends on test_trivial_snapshot_record to ensure database record exists before hydration.
    """
    async with test_specimens_hydrator.hydrate("test-fixtures/test-trivial") as hydrated:
        yield hydrated


# =============================================================================
# Run managers fixtures
# =============================================================================


@pytest.fixture
def mock_snapshot_slug() -> SnapshotSlug:
    """Shared test snapshot slug."""
    return SnapshotSlug("ducktape/2025-11-26-00")


@pytest.fixture
def mock_prompt_sha256() -> str:
    """Mock SHA-256 hash for test prompts."""
    return "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"  # SHA256 of empty string


@pytest.fixture
def sample_critic_success() -> CriticSuccess:
    """Sample CriticSuccess with empty issues list."""
    return CriticSuccess(result=CriticSubmitPayload(issues=[], notes_md=None))


@pytest.fixture
def sample_grader_input() -> GraderInput:
    """Sample GraderInput with train specimen and critique ID."""
    return GraderInput(snapshot_slug=SnapshotSlug("ducktape/2025-11-26-00"), critique_id=uuid4())


@pytest.fixture
def runs_context(tmp_path: Path) -> RunsContext:
    """RunsContext using pytest tmp_path fixture.

    Available to props tests for creating temporary run directories.
    """
    return RunsContext(tmp_path)


@pytest.fixture
def mock_openai_client() -> FakeOpenAIModel:
    """Mock OpenAI client that returns empty assistant messages.

    For tests that need specific responses, create a custom FakeOpenAIModel
    with the desired response sequence.
    """
    # Single generic success response
    result = ResponsesResult(
        id="resp_test",
        usage=None,
        output=[AssistantMessageOut(parts=[OutputText(text="Task completed successfully.")])],
    )
    return FakeOpenAIModel([result])


@pytest.fixture
def make_openai_client():
    """Factory fixture for creating mock OpenAI clients from response sequences.

    Usage:
        responses = [factory.make(...), factory.make(...)]
        client = make_openai_client(responses)

    This is a props-specific alias for the pattern used in agent tests (make_fake_openai).
    """

    def _factory(responses: list[ResponsesResult]) -> FakeOpenAIModel:
        return FakeOpenAIModel(responses)

    return _factory


def _sanitize_test_id(test_id: str, max_length: int = 63) -> str:
    """Sanitize pytest node ID for use in PostgreSQL database name.

    Args:
        test_id: pytest node ID (e.g., 'tests/props/test_db.py::test_sync')
        max_length: Maximum length for PostgreSQL identifier (default 63)

    Returns:
        Sanitized database name safe for PostgreSQL
    """
    # Keep only alphanumeric and underscore; replace other chars with underscore
    sanitized = "".join(c if c.isalnum() or c == "_" else "_" for c in test_id)
    # Collapse consecutive underscores
    while "__" in sanitized:
        sanitized = sanitized.replace("__", "_")
    # Trim leading/trailing underscores
    sanitized = sanitized.strip("_")
    # Ensure it fits PostgreSQL's 63-character limit (including 'props_test_' prefix)
    # Reserve space for the prefix that will be added later
    prefix = "props_test_"
    available_length = max_length - len(prefix)
    if len(sanitized) > available_length:
        # Keep prefix and add hash suffix to ensure uniqueness
        hash_suffix = hashlib.sha256(test_id.encode()).hexdigest()[:8]
        prefix_length = available_length - len(hash_suffix) - 1
        sanitized = f"{sanitized[:prefix_length]}_{hash_suffix}"
    return sanitized


@pytest.fixture
def test_db(request, block_production_config_in_tests):
    """Create isolated database for each test.

    Creates a unique database per test, initializes schema, and drops it after.
    Safe for parallel pytest-xdist execution - each test gets its own database.

    Database name is derived from the test node ID for better debuggability.

    Yields:
        DatabaseConfig for the test database (with both admin and agent credentials)
    """
    # Generate database name from test node ID
    test_node_id = request.node.nodeid
    sanitized_id = _sanitize_test_id(test_node_id)
    db_name = f"props_test_{sanitized_id}"

    # Get base config (uses the original function, bypassing the mock)
    get_database_config_original = block_production_config_in_tests
    base_config = get_database_config_original()  # Uses env vars set by devenv

    # Create test database (idempotent - drops existing if present)
    ensure_database_exists(base_config, db_name, drop_existing=True)

    # Build config for the new test database
    test_config = base_config.with_database(db_name)

    # Keep postgres engine for teardown
    postgres_config = base_config.with_database("postgres")
    postgres_engine = create_engine(postgres_config.admin_url(), isolation_level="AUTOCOMMIT")

    # Dispose any existing connection (needed for per-test isolation in parallel tests)

    dispose_db()

    # Initialize schema in the new database
    init_db(test_config)
    recreate_database()

    yield test_config  # Test runs here with access to config

    # Cleanup: drop the test database
    with postgres_engine.connect() as conn:
        # Terminate connections to the test database
        conn.execute(
            text(
                f"""
            SELECT pg_terminate_backend(pg_stat_activity.pid)
            FROM pg_stat_activity
            WHERE pg_stat_activity.datname = '{db_name}'
              AND pid <> pg_backend_pid()
        """
            )
        )
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))

    postgres_engine.dispose()


@pytest.fixture
def synced_test_db(test_db):
    """Test database with production specimens synced."""

    specimens_dir = get_specimens_base_path()
    with get_session() as session:
        sync_snapshots_to_db(session, specimens_dir)
        sync_issues_to_db(session, specimens_dir)
        sync_examples_to_db(session, specimens_dir)
    return test_db
