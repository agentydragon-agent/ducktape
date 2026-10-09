"""Allow ordinary GitHub issues as independently followed subjects."""

from alembic import op

revision = "0009_github_issue_subject"
down_revision = "0008_github_entities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("github_subject_kind", "github_subject", type_="check")
    op.create_check_constraint(
        "github_subject_kind", "github_subject", "kind IN ('pull_request', 'issue', 'branch', 'commit')"
    )


def downgrade() -> None:
    # Refuse a downgrade while issue subjects exist rather than discard their subscriptions/receipts.
    op.drop_constraint("github_subject_kind", "github_subject", type_="check")
    op.create_check_constraint("github_subject_kind", "github_subject", "kind IN ('pull_request', 'branch', 'commit')")
