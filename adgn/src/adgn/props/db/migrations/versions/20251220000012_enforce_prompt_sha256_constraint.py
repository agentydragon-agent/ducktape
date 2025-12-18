"""Enforce prompt_sha256 matches SHA256 of prompt_text.

Revision ID: 20251220000012
Revises: 20251220000011
Create Date: 2025-12-20

This migration adds a CHECK constraint to ensure that prompt_sha256
always matches the actual SHA256 hash of prompt_text. This prevents
data integrity issues where the hash doesn't match the content.

The constraint uses PostgreSQL's digest() function from the pgcrypto extension.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20251220000012"
down_revision = "20251220000011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add CHECK constraint to enforce prompt_sha256 = sha256(prompt_text)."""
    # Ensure pgcrypto extension is available (for digest function)
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # Add CHECK constraint
    # encode(digest(..., 'sha256'), 'hex') returns lowercase hex string (64 chars)
    op.create_check_constraint(
        "prompt_sha256_matches_content", "prompts", "prompt_sha256 = encode(digest(prompt_text, 'sha256'), 'hex')"
    )


def downgrade() -> None:
    """Remove the CHECK constraint."""
    op.drop_constraint("prompt_sha256_matches_content", "prompts", type_="check")
