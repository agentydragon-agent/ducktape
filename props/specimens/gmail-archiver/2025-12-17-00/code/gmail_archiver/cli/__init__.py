"""CLI subcommand modules for gmail-archiver."""

from gmail_archiver.cli.filters import filters_app
from gmail_archiver.cli.labels import labels_app

__all__ = ["filters_app", "labels_app"]
