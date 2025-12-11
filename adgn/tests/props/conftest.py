"""Shared test fixtures for props tests."""

import hashlib
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel
import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text

from adgn.openai_utils.model import AssistantMessageOut, OutputText, ResponsesResult
from adgn.props.critic.models import CriticSubmitPayload, CriticSuccess
from adgn.props.db import init_db, recreate_database
from adgn.props.db.config import get_production_config
from adgn.props.db.prompts import hash_and_upsert_prompt
from adgn.props.db.snapshots import DBGraderOutput
from adgn.props.files_hash import hash_file_set
from adgn.props.grader.models import (
    CanonicalFPCoverage,
    CanonicalTPCoverage,
    FalsePositiveID,
    FPCoverageEntry,
    GraderInput,
    GradeSubmitInput,
    ReportedIssueRatios,
    TPCoverageEntry,
    TruePositiveID,
)
from adgn.props.grader.persistence import grade_submit_input_to_db
from adgn.props.hydration import SnapshotHydrator
from adgn.props.ids import SnapshotSlug
from adgn.props.rationale import Rationale
from adgn.props.runs_context import RunsContext
from tests.llm.support.openai_mock import FakeOpenAIModel

# Common test data for database fixtures
TEST_FILES_LIST = ["test.py"]
TEST_FILES = {Path(f) for f in TEST_FILES_LIST}
TEST_FILES_HASH = hash_file_set(TEST_FILES)


def make_grader_output(
    tp_count: int, fp_count: int, recall: float, tp_ratio: float, fp_ratio: float, summary: str
) -> DBGraderOutput:
    """Build GradeSubmitInput and convert to DB format for test storage.

    Uses actual Pydantic models to ensure test data matches the real schema.
    PydanticColumn accepts the model directly and handles serialization.

    Args:
        tp_count: Number of canonical TPs to create
        fp_count: Number of canonical FPs to create
        recall: Recall value (0-1)
        tp_ratio: TP ratio in reported_issue_ratios
        fp_ratio: FP ratio in reported_issue_ratios
        summary: Summary text
    """
    tp_coverage = [
        TPCoverageEntry(
            canonical_id=TruePositiveID(f"tp-{i:03d}"),
            coverage=CanonicalTPCoverage(
                covered_by=[], recall_credit=0.0, rationale="Test coverage - canonical TP not covered"
            ),
        )
        for i in range(1, tp_count + 1)
    ]
    fp_coverage = [
        FPCoverageEntry(
            canonical_id=FalsePositiveID(f"fp-{i:03d}"),
            coverage=CanonicalFPCoverage(covered_by=[], rationale="Test coverage - known FP not triggered"),
        )
        for i in range(1, fp_count + 1)
    ]
    unlabeled = round(1.0 - tp_ratio - fp_ratio, 2)
    grade = GradeSubmitInput(
        canonical_tp_coverage=tp_coverage,
        canonical_fp_coverage=fp_coverage,
        novel_critique_issues=[],
        reported_issue_ratios=ReportedIssueRatios(tp=tp_ratio, fp=fp_ratio, unlabeled=unlabeled),
        recall=recall,
        summary=summary,
    )
    # Convert to DB format (flat structure)
    return grade_submit_input_to_db(grade)


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
    from adgn.props.db import get_session
    from adgn.props.db.models import Snapshot
    from adgn.props.models.snapshot import LocalSource

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
def test_db(request):
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

    # Get base config (structured fields)
    base_config = get_production_config()  # Uses env vars set by devenv

    # Connect to postgres database to create test database
    postgres_config = base_config.with_database("postgres")
    postgres_engine = create_engine(postgres_config.admin_url(), isolation_level="AUTOCOMMIT")
    with postgres_engine.connect() as conn:
        # Drop database if it exists (idempotent - handles cleanup failures from previous runs)
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
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))

    # Build config for the new test database
    test_config = base_config.with_database(db_name)

    # Dispose any existing connection (needed for per-test isolation in parallel tests)
    from adgn.props.db import dispose_db

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
    from adgn.props.db import get_session
    from adgn.props.db.sync import (
        get_specimens_base_path,
        sync_critic_scopes_to_db,
        sync_issues_to_db,
        sync_snapshots_to_db,
    )

    specimens_dir = get_specimens_base_path()
    with get_session() as session:
        sync_snapshots_to_db(session, specimens_dir)
        sync_issues_to_db(session, specimens_dir)
        sync_critic_scopes_to_db(session, specimens_dir)
    return test_db
