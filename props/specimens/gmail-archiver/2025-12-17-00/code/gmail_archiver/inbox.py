"""Inbox interface with caching for Gmail operations."""

import os
from pathlib import Path

from rich.console import Console

from gmail_archiver.gmail_client import GmailClient
from gmail_archiver.models import GmailMessage

console = Console()


class GmailInbox:
    """Cached inbox interface for Gmail operations.

    Wraps GmailClient and adds transparent local caching (XDG directory).
    Planners use this interface to fetch messages without worrying about caching.
    """

    def __init__(self, client: GmailClient, cache_dir: Path | None = None, show_progress: bool = True):
        self.client = client
        self.cache_dir = cache_dir or self._get_xdg_cache_dir()
        self._message_cache: dict[str, GmailMessage] = {}
        self.show_progress = show_progress

    def _get_xdg_cache_dir(self) -> Path:
        xdg_cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        cache_dir = xdg_cache / "gmail-archiver"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    def fetch_message(self, message_id: str) -> GmailMessage:
        if message_id in self._message_cache:
            return self._message_cache[message_id]

        # TODO: Add disk cache support
        # Check disk cache
        # cache_file = self.cache_dir / f"{message_id}.json"
        # if cache_file.exists():
        #     return GmailMessage.model_validate_json(cache_file.read_text())

        # Fetch from API
        message = self.client.get_message(message_id)

        # Cache it in memory
        self._message_cache[message_id] = message

        # TODO: Save to disk cache
        # cache_file.write_text(message.model_dump_json())

        return message

    def fetch_messages(self, query: str, batch_size: int = 50) -> list[GmailMessage]:
        # Get message IDs from query
        if self.show_progress:
            console.print(f"[dim]Searching: {query}[/dim]")
        message_ids = self.client.list_messages_by_query(query)

        if not message_ids:
            return []

        # Check which messages are already cached
        uncached_ids = [mid for mid in message_ids if mid not in self._message_cache]

        if self.show_progress and uncached_ids:
            console.print(f"[dim]Fetching {len(uncached_ids)} messages (batch size {batch_size})...[/dim]")

        # Batch fetch uncached messages
        if uncached_ids:
            fetched = self.client.get_messages_batch(uncached_ids, batch_size=batch_size)
            for msg in fetched:
                self._message_cache[msg.id] = msg

        # Return all messages in original order
        return [self._message_cache[mid] for mid in message_ids if mid in self._message_cache]

    def fetch_messages_minimal(self, query: str, batch_size: int = 100) -> list[GmailMessage]:
        """Fetch messages with minimal data (id, labels, snippet, date).

        More efficient than fetch_messages when you only need label info.
        """
        if self.show_progress:
            console.print(f"[dim]Searching: {query}[/dim]")
        message_ids = self.client.list_messages_by_query(query)

        if not message_ids:
            return []

        # Check which messages are already cached
        uncached_ids = [mid for mid in message_ids if mid not in self._message_cache]

        if self.show_progress and uncached_ids:
            console.print(f"[dim]Fetching {len(uncached_ids)} messages (minimal, batch size {batch_size})...[/dim]")

        # Batch fetch uncached messages with minimal format
        if uncached_ids:
            fetched = self.client.get_messages_minimal_batch(uncached_ids, batch_size=batch_size)
            for msg in fetched:
                self._message_cache[msg.id] = msg

        # Return all messages in original order
        return [self._message_cache[mid] for mid in message_ids if mid in self._message_cache]
