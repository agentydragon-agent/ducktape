"""Normalize GitHub identities, repository grants, and subject associations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_github_entities"
down_revision = "0007_subscription_health"
branch_labels = None
depends_on = None


def refresh_columns() -> list[sa.Column]:
    return [
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("error_kind", sa.String()),
        sa.Column("error", sa.String()),
        sa.Column("error_since", sa.DateTime(timezone=True)),
        sa.Column("error_observed_at", sa.DateTime(timezone=True)),
        sa.Column("next_attempt", sa.DateTime(timezone=True)),
        sa.Column("claim", sa.Uuid()),
        sa.Column("claim_until", sa.DateTime(timezone=True)),
    ]


def upgrade() -> None:
    op.create_table(
        "github_installation",
        sa.Column("app_id", sa.BigInteger(), primary_key=True),
        sa.Column("installation_id", sa.BigInteger(), primary_key=True),
        sa.Column("generation", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "github_repository",
        sa.Column("repository_id", sa.BigInteger(), primary_key=True),
        sa.Column("full_name", sa.String(), nullable=False),
    )
    op.create_table(
        "github_repository_access",
        sa.Column("app_id", sa.BigInteger(), primary_key=True),
        sa.Column("installation_id", sa.BigInteger(), primary_key=True),
        sa.Column("repository_id", sa.BigInteger(), sa.ForeignKey("github_repository.repository_id"), primary_key=True),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("validated_installation_generation", sa.BigInteger()),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        *refresh_columns(),
        sa.ForeignKeyConstraint(["app_id", "installation_id"], ["github_installation.app_id", "github_installation.installation_id"]),
    )
    op.create_table(
        "github_subject",
        sa.Column("repository_id", sa.BigInteger(), sa.ForeignKey("github_repository.repository_id"), primary_key=True),
        sa.Column("kind", sa.String(), primary_key=True),
        sa.Column("subject_key", sa.String(), primary_key=True),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        *refresh_columns(),
        sa.CheckConstraint("kind IN ('pull_request', 'branch', 'commit')", name="github_subject_kind"),
    )
    op.create_table(
        "github_subject_revision",
        sa.Column("repository_id", sa.BigInteger(), primary_key=True),
        sa.Column("kind", sa.String(), primary_key=True),
        sa.Column("subject_key", sa.String(), primary_key=True),
        sa.Column("head_repository_id", sa.BigInteger(), sa.ForeignKey("github_repository.repository_id"), primary_key=True),
        sa.Column("sha", sa.String(), primary_key=True),
        sa.ForeignKeyConstraint(["repository_id", "kind", "subject_key"], ["github_subject.repository_id", "github_subject.kind", "github_subject.subject_key"]),
    )
    op.drop_constraint("subscription_source_state", "subscription", type_="check")
    for name in ("github_app_id", "github_installation_id", "github_repository_id"):
        op.add_column("subscription", sa.Column(name, sa.BigInteger()))
    for name in ("github_subject_kind", "github_subject_key"):
        op.add_column("subscription", sa.Column(name, sa.String()))
    op.execute("""
        UPDATE subscription SET
            github_app_id = (github_binding->>'app_id')::bigint,
            github_installation_id = (github_binding->>'installation_id')::bigint,
            github_repository_id = (github_binding->>'repository_id')::bigint,
            github_subject_kind = creation #>> '{source,subject,kind}',
            github_subject_key = coalesce(creation #>> '{source,subject,number}',
                creation #>> '{source,subject,name}', creation #>> '{source,subject,sha}')
        WHERE github_binding IS NOT NULL
    """)
    op.execute("INSERT INTO github_installation SELECT DISTINCT github_app_id, github_installation_id, 0 FROM subscription WHERE github_app_id IS NOT NULL")
    op.execute("INSERT INTO github_repository SELECT github_repository_id, min(creation #>> '{source,repository}') FROM subscription WHERE github_repository_id IS NOT NULL GROUP BY github_repository_id")
    op.execute("INSERT INTO github_repository_access (app_id, installation_id, repository_id, generation) SELECT DISTINCT github_app_id, github_installation_id, github_repository_id, 0 FROM subscription WHERE github_app_id IS NOT NULL")
    op.execute("INSERT INTO github_subject (repository_id, kind, subject_key, generation) SELECT DISTINCT github_repository_id, github_subject_kind, github_subject_key, 0 FROM subscription WHERE github_repository_id IS NOT NULL")
    op.drop_column("subscription", "github_binding")
    op.create_foreign_key("subscription_github_access", "subscription", "github_repository_access",
        ["github_app_id", "github_installation_id", "github_repository_id"], ["app_id", "installation_id", "repository_id"])
    op.create_foreign_key("subscription_github_subject", "subscription", "github_subject",
        ["github_repository_id", "github_subject_kind", "github_subject_key"], ["repository_id", "kind", "subject_key"])
    op.create_check_constraint("subscription_source_state", "subscription",
        "CASE creation #>> '{source,provider}' "
        "WHEN 'actions' THEN actions_after_sequence IS NOT NULL AND github_start_position IS NULL "
        "AND github_app_id IS NULL AND github_installation_id IS NULL AND github_repository_id IS NULL "
        "AND github_subject_kind IS NULL AND github_subject_key IS NULL "
        "WHEN 'github' THEN actions_after_sequence IS NULL AND github_start_position IS NOT NULL "
        "AND github_app_id IS NOT NULL AND github_installation_id IS NOT NULL AND github_repository_id IS NOT NULL "
        "AND github_subject_kind IS NOT NULL AND github_subject_key IS NOT NULL ELSE false END")


def downgrade() -> None:
    if op.get_bind().execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM github_subject_revision) OR "
        "EXISTS (SELECT 1 FROM github_repository_access WHERE checked_at IS NOT NULL OR error IS NOT NULL) OR "
        "EXISTS (SELECT 1 FROM github_subject WHERE last_success_at IS NOT NULL OR error IS NOT NULL)"
    )).scalar():
        raise RuntimeError("refusing data loss: shared GitHub observations require a reverse migration")
    op.drop_constraint("subscription_source_state", "subscription", type_="check")
    op.drop_constraint("subscription_github_subject", "subscription", type_="foreignkey")
    op.drop_constraint("subscription_github_access", "subscription", type_="foreignkey")
    op.add_column("subscription", sa.Column("github_binding", postgresql.JSONB(none_as_null=True)))
    op.execute("UPDATE subscription SET github_binding = jsonb_build_object('app_id', github_app_id, 'installation_id', github_installation_id, 'repository_id', github_repository_id) WHERE github_app_id IS NOT NULL")
    for column in ("github_app_id", "github_installation_id", "github_repository_id", "github_subject_kind", "github_subject_key"):
        op.drop_column("subscription", column)
    op.create_check_constraint("subscription_source_state", "subscription",
        "CASE creation #>> '{source,provider}' "
        "WHEN 'actions' THEN actions_after_sequence IS NOT NULL AND github_start_position IS NULL "
        "AND github_binding IS NULL "
        "WHEN 'github' THEN actions_after_sequence IS NULL AND github_start_position IS NOT NULL "
        "AND github_binding IS NOT NULL ELSE false END")
    for table in ("github_subject_revision", "github_subject", "github_repository_access", "github_repository", "github_installation"):
        op.drop_table(table)
