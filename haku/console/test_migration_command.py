"""The Console image exposes a minimal migration-only process mode."""

from __future__ import annotations

import pytest
import pytest_bazel

from haku.console import app, database_migrate


def test_migration_command_reads_only_the_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = "postgresql+asyncpg://approval_store:secret@db.example/approval_store"
    monkeypatch.setenv("HAKU_CONSOLE_DATABASE_URL", database_url)
    called: list[str] = []
    monkeypatch.setattr(database_migrate, "apply_migrations", called.append)

    database_migrate.main()

    assert called == [database_url]


def test_migration_command_rejects_an_absent_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HAKU_CONSOLE_DATABASE_URL", raising=False)

    with pytest.raises(SystemExit, match="HAKU_CONSOLE_DATABASE_URL"):
        database_migrate.main()


def test_image_command_dispatches_migration_without_starting_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []
    monkeypatch.setattr(app, "migration_main", lambda: called.append("migrate"))
    monkeypatch.setattr(app, "main", lambda: called.append("serve"))

    app.run_command(["migrate"])

    assert called == ["migrate"]


def test_image_command_rejects_unknown_modes() -> None:
    with pytest.raises(SystemExit, match="usage"):
        app.run_command(["unknown"])


if __name__ == "__main__":
    pytest_bazel.main()
