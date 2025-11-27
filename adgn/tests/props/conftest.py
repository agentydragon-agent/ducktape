"""Shared test fixtures for props tests."""

from pydantic import BaseModel
import pytest
import pytest_asyncio

from adgn.props.ids import BaseIssueID
from adgn.props.paths import SpecimenRelativePath
from adgn.props.rationale import Rationale
from adgn.props.specimens.registry import SpecimenRegistry
from adgn.props.validation_context import GradedCritiqueContext, SpecimenContext


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

    def _make(tp_ids=(), fp_ids=(), known_files=None):
        return SpecimenContext(
            specimen_slug="test/specimen",
            known_files=known_files or {},
            allowed_tp_ids=frozenset(tp_ids),
            allowed_fp_ids=frozenset(fp_ids),
        )

    return _make


@pytest.fixture
def specimen_ctx_multiple_tp(make_specimen_ctx):
    """Specimen context with multiple TP IDs (for testing hashability/sets)."""
    return make_specimen_ctx(tp_ids=["issue-001", "issue-002"])


@pytest.fixture
def specimen_ctx_tp_fp(make_specimen_ctx):
    """Specimen context with same ID in both TP and FP (for namespace discrimination)."""
    return make_specimen_ctx(tp_ids=["issue-001"], fp_ids=["issue-001"])


@pytest.fixture
def critique_ctx_single():
    """Critique context with one allowed input ID."""
    return GradedCritiqueContext(allowed_input_ids=frozenset(["critique-001"]))


@pytest_asyncio.fixture
async def loaded_specimen():
    """Load a real specimen with validation using load_and_hydrate.

    Yields (record, hydrated_root) tuple for tests that need both
    the validated specimen data and access to the hydrated files.

    Uses ducktape/2025-11-22-02 as the canonical test specimen.
    """
    async with SpecimenRegistry.load_and_hydrate("ducktape/2025-11-22-02") as (rec, hydrated_root):
        yield rec, hydrated_root


@pytest_asyncio.fixture
async def loaded_specimen_record():
    """Load a real specimen (async fixture for tests that only need the record).

    Uses ducktape/2025-11-22-02 as the canonical test specimen.
    """
    return await SpecimenRegistry.load_strict("ducktape/2025-11-22-02")
