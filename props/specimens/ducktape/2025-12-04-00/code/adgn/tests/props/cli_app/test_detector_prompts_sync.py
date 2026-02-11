"""Test detector prompt discovery and sync to database."""

from __future__ import annotations

import pytest

from adgn.props.db import get_session
from adgn.props.db.models import Prompt
from adgn.props.db.prompts import discover_detector_prompts, load_and_upsert_detector_prompt

pytestmark = [pytest.mark.integration, pytest.mark.requires_postgres]


def test_discover_detector_prompts():
    """Test that detector prompts are discovered from prompts/system/."""
    prompts = discover_detector_prompts()
    assert isinstance(prompts, list)
    assert len(prompts) >= 3  # At minimum: dead_code, flag_propagation, contract_truthfulness
    assert all(p.endswith(".md") for p in prompts)
    # Check specific expected prompts exist
    assert "dead_code.md" in prompts
    assert "flag_propagation.md" in prompts
    assert "contract_truthfulness.md" in prompts
    # Verify sorted order
    assert prompts == sorted(prompts)


def test_load_and_upsert_detector_prompt(test_db):
    """Test loading detector prompt from file and upserting to database."""
    # Load and upsert a detector prompt
    prompt_hash = load_and_upsert_detector_prompt("dead_code.md")

    # Verify hash format (SHA256 is 64 hex chars)
    assert len(prompt_hash) == 64
    assert all(c in "0123456789abcdef" for c in prompt_hash)

    # Verify prompt was written to DB
    with get_session() as session:
        prompt_obj = session.get(Prompt, prompt_hash)
        assert prompt_obj is not None
        assert prompt_obj.prompt_sha256 == prompt_hash
        assert prompt_obj.template_file_path == "dead_code.md"
        assert "Dead Code & Unreachability Detector" in prompt_obj.prompt_text
        assert len(prompt_obj.prompt_text) > 100  # Non-trivial content


def test_sync_all_detector_prompts(test_db):
    """Test syncing all detector prompts from git to database."""
    # Discover all prompts
    prompts = discover_detector_prompts()
    assert len(prompts) >= 3

    # Sync all prompts to DB
    hashes = []
    for filename in prompts:
        prompt_hash = load_and_upsert_detector_prompt(filename)
        hashes.append((filename, prompt_hash))

    # Verify all prompts are in DB with correct metadata
    with get_session() as session:
        for filename, prompt_hash in hashes:
            prompt_obj = session.get(Prompt, prompt_hash)
            assert prompt_obj is not None
            assert prompt_obj.template_file_path == filename
            assert len(prompt_obj.prompt_text) > 0


def test_upsert_idempotency(test_db):
    """Test that re-upserting the same prompt is idempotent."""
    # First upsert
    hash1 = load_and_upsert_detector_prompt("dead_code.md")

    # Second upsert (same content)
    hash2 = load_and_upsert_detector_prompt("dead_code.md")

    # Hashes should match (same content)
    assert hash1 == hash2

    # Only one record should exist
    with get_session() as session:
        prompt_obj = session.get(Prompt, hash1)
        assert prompt_obj is not None
        assert prompt_obj.template_file_path == "dead_code.md"
