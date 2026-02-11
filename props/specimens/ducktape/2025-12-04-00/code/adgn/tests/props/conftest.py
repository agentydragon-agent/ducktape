"""Shared test fixtures for props tests."""

from pathlib import Path
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

from pydantic import BaseModel
import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text

from adgn.openai_utils.model import AssistantMessageOut, OutputText, ResponsesResult
from adgn.props.critic.models import CriticSubmitPayload, CriticSuccess
from adgn.props.db import get_session, init_db, recreate_database
from adgn.props.db.config import DatabaseConfig, get_test_config
from adgn.props.db.models import Prompt
from adgn.props.grader.models import GraderInput
from adgn.props.ids import BaseIssueID, SnapshotSlug
from adgn.props.paths import SpecimenRelativePath
from adgn.props.rationale import Rationale
from adgn.props.runs_context import RunsContext
from adgn.props.snapshot_registry import SnapshotRegistry
from adgn.props.validation_context import GradedCritiqueContext, SpecimenContext
from tests.llm.support.openai_mock import FakeOpenAIModel


@pytest.fixture
def base_issue_id_model():
    """Fixture providing a Pydantic model with BaseIssueID field."""

    class Model(BaseModel):
        id: BaseIssueID

    return Model


@pytest.fixture
def specimen_relative_path_model():
    """Fixture providing a Pydantic model with SpecimenRelativePath field."""

    class Model(BaseModel):
        path: SpecimenRelativePath

    return Model


@pytest.fixture
def rationale_model():
    """Fixture providing a Pydantic model with Rationale field."""

    class Model(BaseModel):
        rationale: Rationale

    return Model


@pytest.fixture
def make_specimen_ctx():
    """Factory for creating specimen contexts with custom allowed IDs."""

    def _make(tp_ids=(), fp_ids=(), all_discovered_files=None):
        return SpecimenContext(
            snapshot_slug=SnapshotSlug("test/specimen"),
            all_discovered_files=all_discovered_files or {},
            allowed_tp_ids=frozenset(tp_ids),
            allowed_fp_ids=frozenset(fp_ids),
        )

    return _make


@pytest.fixture
def specimen_ctx_multiple_tp(make_specimen_ctx):
    """Snapshot context with multiple TP IDs (for testing hashability/sets)."""
    return make_specimen_ctx(tp_ids=["issue-001", "issue-002"])


@pytest.fixture
def specimen_ctx_tp_fp(make_specimen_ctx):
    """Snapshot context with same ID in both TP and FP (for namespace discrimination)."""
    return make_specimen_ctx(tp_ids=["issue-001"], fp_ids=["issue-001"])


@pytest.fixture
def critique_ctx_single():
    """Critique context with one allowed input ID."""
    return GradedCritiqueContext(allowed_input_ids=frozenset(["critique-001"]))


# === Snapshot Registry Fixtures (DI Pattern) ===
# Two explicit registries:
# 1. production_specimens_registry - for real specimens (src/adgn/props/specimens/)
# 2. test_specimens_registry - for test fixtures (tests/props/fixtures/specimens/)


@pytest.fixture
def production_specimens_registry() -> SnapshotRegistry:
    """Production specimens registry from package resources.

    Uses installed package specimens (src/adgn/props/specimens/).
    """
    return SnapshotRegistry.from_package_resources()


@pytest.fixture
def test_specimens_base() -> Path:
    """Base directory for test-only fixture specimens.

    Returns path to tests/props/fixtures/specimens/ which contains
    minimal specimens for testing specific scenarios.
    """
    return Path(__file__).parent / "fixtures" / "specimens"


@pytest.fixture
def test_specimens_registry(test_specimens_base: Path) -> SnapshotRegistry:
    """Test fixtures specimens registry (DI pattern - no monkeypatching).

    Uses test fixtures from tests/props/fixtures/specimens/ which contains
    minimal test-only specimens like test-trivial.
    """
    return SnapshotRegistry.from_base_path(test_specimens_base)


@pytest_asyncio.fixture
async def loaded_specimen(production_specimens_registry):
    """Load a real specimen with validation using load_and_hydrate.

    Yields HydratedSnapshot object containing both the validated specimen data
    and the hydrated content root.

    Uses ducktape/2025-11-22-02 as the canonical test specimen.
    """
    async with production_specimens_registry.load_and_hydrate("ducktape/2025-11-22-02") as hydrated:
        yield hydrated


@pytest_asyncio.fixture
async def loaded_specimen_record(loaded_specimen):
    """Load a real specimen (async fixture for tests that only need the record).

    Uses ducktape/2025-11-22-02 as the canonical test specimen.
    """
    return loaded_specimen.record


@pytest_asyncio.fixture
async def test_trivial_specimen(test_specimens_registry):
    """Load test-trivial fixture specimen (clean Python code, zero issues).

    Test-only specimen for validating zero-issues case.
    Lives in tests/props/fixtures/specimens/test-fixtures/test-trivial/.
    Uses DI - no monkeypatching needed.
    """
    async with test_specimens_registry.load_and_hydrate("test-fixtures/test-trivial") as hydrated:
        yield hydrated


# =============================================================================
# Run managers fixtures
# =============================================================================


@pytest.fixture
def mock_prompt_sha256() -> str:
    """Mock SHA-256 hash for test prompts."""
    return "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"  # SHA256 of empty string


@pytest.fixture
def sample_critic_success() -> CriticSuccess:
    """Sample CriticSuccess with empty issues list."""
    return CriticSuccess(result=CriticSubmitPayload(issues=[]))


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


@pytest.fixture
def test_db(request):
    """Create isolated database for each test.

    Creates a unique database per test, initializes schema, and drops it after.
    Safe for parallel pytest-xdist execution - each test gets its own database.
    """
    # Generate unique database name for this test
    test_id = str(uuid4()).replace("-", "")[:16]
    db_name = f"props_test_{test_id}"

    # Get base config and parse admin URL
    base_config = get_test_config()
    # Parse admin URL to get connection params (connect to postgres db to create new db)
    parsed = urlparse(base_config.admin_url)
    postgres_url = urlunparse((parsed.scheme, parsed.netloc, "/postgres", "", "", ""))

    # Connect to postgres database to create test database
    postgres_engine = create_engine(postgres_url, isolation_level="AUTOCOMMIT")
    with postgres_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))

    # Build URLs for the new test database
    test_admin_url = urlunparse((parsed.scheme, parsed.netloc, f"/{db_name}", "", "", ""))
    test_agent_url = test_admin_url.replace("postgres:postgres", "agent_user:agent_password_changeme")
    test_config = DatabaseConfig(admin_url=test_admin_url, agent_url=test_agent_url)

    # Initialize schema in the new database
    init_db(test_config.admin_url)
    recreate_database()

    # Create default test prompts
    with get_session() as session:
        for prompt_sha256 in ["test123", "unknown", "test", "train-test"]:
            prompt = Prompt(prompt_sha256=prompt_sha256, prompt_text=f"Test prompt for {prompt_sha256}")
            session.add(prompt)
        session.commit()

    yield  # Test runs here

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
