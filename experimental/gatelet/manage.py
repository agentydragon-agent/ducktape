from __future__ import annotations

"""Command line utilities for Gatelet management."""

import argparse
import getpass
from typing import Iterable

from sqlalchemy import func, select, update

from server.config import settings
from server.models import AdminUser, Base, get_engine, get_session_maker
from server.security import hash_password


def _confirm(prompt: str) -> bool:
    """Prompt user to confirm an action."""
    resp = input(f"{prompt} [y/N]: ").strip().lower()
    return resp == "y"


def _entity_counts(session) -> Iterable[tuple[str, int]]:
    """Return row counts for all tables."""
    counts = []
    for table in Base.metadata.sorted_tables:
        cnt = session.execute(select(func.count()).select_from(table)).scalar()  # pylint: disable=not-callable
        counts.append((table.name, cnt))
    return counts


def reset_db() -> None:
    """Drop and recreate tables, set default admin password."""
    engine = get_engine(str(settings.database.dsn))
    Session = get_session_maker(engine)
    with Session() as session:
        counts = _entity_counts(session)
        if any(cnt > 0 for _, cnt in counts):
            print("Current entity counts:")
            for name, cnt in counts:
                print(f"  {name}: {cnt}")
            if not _confirm("Drop and recreate the database?"):
                print("Aborted.")
                return
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with Session() as session:
        admin = AdminUser(password_hash=hash_password("gatelet"))
        session.add(admin)
        session.commit()
    print("Database initialized with default admin password 'gatelet'.")


def change_password(password: str | None) -> None:
    """Change admin password."""
    engine = get_engine(str(settings.database.dsn))
    Session = get_session_maker(engine)
    pwd = password or getpass.getpass("New admin password: ")
    with Session.begin() as session:  # pylint: disable=no-member
        admin = session.execute(select(AdminUser)).scalar_one_or_none()
        hashed = hash_password(pwd)
        if admin:
            session.execute(update(AdminUser).values(password_hash=hashed))
        else:
            session.add(AdminUser(password_hash=hashed))
    print("Admin password updated.")


def main() -> None:
    """Entry point for command line interface."""
    parser = argparse.ArgumentParser(description="Gatelet management utility")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("reset-db", help="Initialize a fresh database")
    pw = sub.add_parser("change-password", help="Change admin password")
    pw.add_argument("password", nargs="?", help="New password")

    args = parser.parse_args()
    if args.cmd == "reset-db":
        reset_db()
    elif args.cmd == "change-password":
        change_password(args.password)


if __name__ == "__main__":
    main()
