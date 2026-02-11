"""CLI entry point for gmail-archiver."""

import asyncio
import base64
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
import re
from typing import Annotated

from bs4 import BeautifulSoup
from googleapiclient.errors import HttpError
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table
import typer

from .cli.common import GMAIL_TOKEN_FILE, DryRunDefaultTrueOption, TokenFileOption
from .cli.filters import filters_app
from .cli.labels import labels_app
from .core import Action, Plan, display_plan, summarize_plan
from .event_classifier import EmailTemplateExtractor
from .gmail_client import GmailClient
from .inbox import GmailInbox
from .planners import (
    AliExpressPlanner,
    AnthemEobPlanner,
    AnthemReimbursementPlanner,
    AnthropicReceiptPlanner,
    DbsaEventPlanner,
    OneMedicalPlanner,
    SquarePlanner,
    UspsPlanner,
)

app = typer.Typer(help="Archive old Gmail emails based on extracted dates")
app.add_typer(filters_app, name="filters")
app.add_typer(labels_app, name="labels")
console = Console()


def resolve_token_path(token_file: Path | None) -> Path:
    return token_file or GMAIL_TOKEN_FILE


def get_gmail_client(token_file: Path | None) -> GmailClient:
    return GmailClient(resolve_token_path(token_file))


def print_error(message: str) -> None:
    console.print(f"[bold red]Error:[/bold red] {message}")


@app.command()
def autoclean_inbox(dry_run: DryRunDefaultTrueOption = True, token_file: TokenFileOption = None):
    """Automatically clean up old emails from inbox.

    Adds 'gmail-archiver/inbox-auto-cleaned' label and removes from inbox.
    Only processes emails that are currently in the inbox.
    """
    token_path = resolve_token_path(token_file)
    client = GmailClient(token_path)

    console.print("[bold]Gmail Email Archiver[/bold] - Inbox Auto-Cleaner")
    console.print(f"Dry run: {dry_run}, Archive label: gmail-archiver/inbox-auto-cleaned\n")

    # Create inbox interface with caching
    inbox = GmailInbox(client)

    # Initialize all planners
    planners = [
        AliExpressPlanner(),
        AnthropicReceiptPlanner(),
        UspsPlanner(),
        DbsaEventPlanner(),
        AnthemEobPlanner(),
        AnthemReimbursementPlanner(),
        SquarePlanner(),
        OneMedicalPlanner(),
    ]

    # Collect plans from all planners
    plans = []
    for planner in planners:
        try:
            plan = planner.plan(inbox)
            plans.append(plan)
        except Exception as e:
            console.print(f"[bold red]Error in {planner.name}:[/bold red] {e}")
            continue

    # Merge all plans
    try:
        combined = Plan.merge(plans)
    except ValueError as e:
        console.print(f"[bold red]Error merging plans:[/bold red] {e}")
        return

    # Display category messages
    for msg in combined.messages:
        console.print(msg)
    console.print()

    # Display unified table
    display_plan(combined, dry_run=dry_run, group_by_category=True)

    # Execute all Gmail API operations
    def execute_action(message_id: str, action: Action):
        if action.labels_to_add:
            for label in action.labels_to_add:
                client.add_label(message_id, label)
        if action.labels_to_remove:
            for label in action.labels_to_remove:
                if label == "INBOX":
                    client.remove_from_inbox(message_id)
                # TODO: Handle other label removals

    combined.execute(dry_run=dry_run, execute_fn=execute_action)

    # Show summary
    console.print(f"\n{summarize_plan(combined)}")


@app.command()
def download_matching(
    query: Annotated[str, typer.Argument(help="Gmail search query (e.g., 'label:inbox', 'from:example.com')")],
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o", help="Directory to save downloaded emails")] = Path(
        "emails"
    ),
    max_results: Annotated[
        int | None, typer.Option("--max-results", "-n", help="Maximum number of emails to download")
    ] = None,
    batch_size: Annotated[
        int,
        typer.Option("--batch-size", "-b", help="Number of emails to fetch per batch (reduce if hitting rate limits)"),
    ] = 10,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation prompt")] = False,
    token_file: TokenFileOption = None,
):
    """Download all emails matching a Gmail search query.

    Examples:
        gmail-archiver download-matching "label:inbox"
        gmail-archiver download-matching "from:example.com" -o ./example_emails
        gmail-archiver download-matching "is:unread" --max-results 10
    """
    console.print(f"[bold]Searching for emails:[/bold] {query}\n")

    # Connect to Gmail
    client = get_gmail_client(token_file)

    # Search for matching emails
    console.print("Searching Gmail...")

    # Build search with pagination
    all_message_ids = []
    page_token = None

    while True:
        search_params = {"userId": "me", "q": query, "maxResults": 500}
        if page_token:
            search_params["pageToken"] = page_token

        results = client.service.users().messages().list(**search_params).execute()
        messages = results.get("messages", [])
        all_message_ids.extend([msg["id"] for msg in messages])

        if max_results and len(all_message_ids) >= max_results:
            all_message_ids = all_message_ids[:max_results]
            break

        page_token = results.get("nextPageToken")
        if not page_token:
            break

    if not all_message_ids:
        console.print("[yellow]No matching emails found.[/yellow]")
        return

    console.print(f"Found {len(all_message_ids)} matching emails.\n")

    # Check for existing downloads not in current search results
    if output_dir.exists():
        existing_files = list(output_dir.glob("*.eml"))
        existing_ids = {f.stem for f in existing_files}
        search_result_ids = set(all_message_ids)

        orphaned_ids = existing_ids - search_result_ids

        if orphaned_ids:
            console.print(f"[yellow]Found {len(orphaned_ids)} downloaded emails no longer in search results:[/yellow]")

            # Show sample of orphaned emails
            orphaned_list = sorted(orphaned_ids)[:10]
            for msg_id in orphaned_list:
                console.print(f"  - {msg_id}.eml")
            if len(orphaned_ids) > 10:
                console.print(f"  ... and {len(orphaned_ids) - 10} more")

            console.print()
            delete_confirm = typer.confirm("Delete these orphaned files?", default=False)

            if delete_confirm:
                for msg_id in orphaned_ids:
                    file_path = output_dir / f"{msg_id}.eml"
                    if file_path.exists():
                        file_path.unlink()
                console.print(f"[green]✓[/green] Deleted {len(orphaned_ids)} orphaned files.\n")
            else:
                console.print("[yellow]Skipped deletion.[/yellow]\n")

    # Show sample of what will be downloaded (using efficient metadata batch fetch)
    console.print("[bold]Sample of emails to download:[/bold]")
    sample_table = Table()
    sample_table.add_column("#", style="cyan", width=4)
    sample_table.add_column("From", style="green", width=30)
    sample_table.add_column("Subject", style="yellow", width=50)
    sample_table.add_column("Date", style="magenta", width=20)

    sample_size = min(10, len(all_message_ids))
    sample_metadata = client.get_messages_metadata_batch(all_message_ids[:sample_size], batch_size=sample_size)

    for idx, msg in enumerate(sample_metadata, start=1):
        sample_table.add_row(str(idx), msg["from"][:30], msg["subject"][:50], msg["date"][:20])

    console.print(sample_table)
    if len(all_message_ids) > sample_size:
        console.print(f"... and {len(all_message_ids) - sample_size} more emails\n")

    # Check how many are already downloaded before confirmation
    existing_preview = {f.stem for f in output_dir.glob("*.eml")} if output_dir.exists() else set()
    to_download_count = len([msg_id for msg_id in all_message_ids if msg_id not in existing_preview])

    # Confirm before downloading
    if not yes:
        if to_download_count < len(all_message_ids):
            confirm = typer.confirm(
                f"\nDownload {to_download_count} new emails to {output_dir}? ({len(all_message_ids) - to_download_count} already exist)"
            )
        else:
            confirm = typer.confirm(f"\nDownload {len(all_message_ids)} emails to {output_dir}?")

        if not confirm:
            console.print("[yellow]Download cancelled.[/yellow]")
            return

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Filter out already downloaded emails
    existing_files = {f.stem for f in output_dir.glob("*.eml")}
    to_download = [msg_id for msg_id in all_message_ids if msg_id not in existing_files]

    if len(to_download) < len(all_message_ids):
        console.print(f"[dim]Skipping {len(all_message_ids) - len(to_download)} already downloaded emails.[/dim]")

    if not to_download:
        console.print("[green]✓[/green] All emails already downloaded!")
        return

    # Download emails using efficient batch requests (50 at a time with retry)
    console.print(f"\n[bold]Downloading {len(to_download)} emails to {output_dir}...[/bold]\n")

    all_successful = []
    all_failed = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Downloading emails...", total=len(to_download))

        # Process in batches
        for i in range(0, len(to_download), batch_size):
            batch_ids = to_download[i : i + batch_size]

            # Fetch batch of raw emails (with automatic retry)
            raw_messages, errors = client.get_messages_raw_batch(batch_ids, batch_size=batch_size, retry_failures=True)

            # Track results
            all_successful.extend(raw_messages)
            all_failed.extend(errors)

            # Save each email to file
            for message_id, raw_bytes in raw_messages:
                output_file = output_dir / f"{message_id}.eml"
                output_file.write_bytes(raw_bytes)
                progress.update(task, advance=1)

            # Update progress for failed messages too (so count is correct)
            for _msg_id, _error in errors:
                progress.update(task, advance=1)

    # Summary
    console.print(f"\n[bold green]✓[/bold green] Downloaded {len(all_successful)} emails to {output_dir}")

    if all_failed:
        console.print(f"\n[bold red]✗[/bold red] Failed to download {len(all_failed)} emails:")
        for msg_id, error in all_failed[:10]:  # Show first 10
            console.print(f"  - {msg_id}: {error[:80]}")
        if len(all_failed) > 10:
            console.print(f"  ... and {len(all_failed) - 10} more failures")


@app.command()
def download_email(
    id_or_link: Annotated[str, typer.Argument(help="Gmail message ID, thread ID, or Gmail web link")],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output .eml file path (default: <id>.eml in current directory)"),
    ] = None,
    token_file: TokenFileOption = None,
):
    """Download an email as .eml file by message ID, thread ID, or Gmail link.

    Supports various Gmail link formats:
        - https://mail.google.com/mail/u/0/#inbox/19b1c55967d81057 (message ID)
        - https://mail.google.com/mail/u/0/#inbox/FMfcgzQcqtXwNDFwNDZXFhFgVnXRzQjw (thread ID)
        - https://mail.google.com/mail/#all/19b1c55967d81057

    Examples:
        gmail-archiver download-email 19b1c55967d81057
        gmail-archiver download-email FMfcgzQcqtXwNDFwNDZXFhFgVnXRzQjw
        gmail-archiver download-email https://mail.google.com/mail/u/0/#inbox/FMfcgzQcqtXwNDFwNDZXFhFgVnXRzQjw
        gmail-archiver download-email 19b1c55967d81057 -o my_email.eml
    """
    # Extract ID from link if needed
    extracted_id = id_or_link
    if id_or_link.startswith("http"):
        # Extract ID from Gmail link
        # Match hex IDs: /inbox/19b1c55967d81057
        match = re.search(r"/#[^/]+/([a-f0-9]{16})", id_or_link)
        if not match:
            print_error(f"Could not extract message ID from link: {id_or_link}")
            console.print(
                "\nNote: Gmail web URLs use encoded IDs that don't work with the Gmail API. "
                "To download an email, find its message ID by searching Gmail with the download-matching command."
            )
            raise typer.Exit(code=1)
        extracted_id = match.group(1)
        console.print(f"Extracted message ID: {extracted_id}")

    # Connect to Gmail
    client = get_gmail_client(token_file)

    # Try fetching as message ID first (most common case)
    message_id = extracted_id
    console.print(f"Downloading message {message_id}...")

    try:
        msg = client.service.users().messages().get(userId="me", id=message_id, format="raw").execute()
    except HttpError as e:
        if e.resp.status == 404:
            # Not found as message, try as thread
            console.print("Message not found, trying as thread ID...")
            try:
                thread = client.service.users().threads().get(userId="me", id=extracted_id, format="minimal").execute()
                messages = thread.get("messages", [])

                if not messages:
                    print_error(f"Thread {extracted_id} has no messages")
                    raise typer.Exit(code=1)

                message_id = messages[0]["id"]
                console.print(f"Found thread with {len(messages)} message(s), downloading first: {message_id}")

                # Fetch the message
                msg = client.service.users().messages().get(userId="me", id=message_id, format="raw").execute()
            except HttpError as thread_error:
                print_error(f"Failed to fetch as message or thread: {thread_error}")
                raise typer.Exit(code=1)
        else:
            print_error(f"Failed to download message {message_id}: {e}")
            raise typer.Exit(code=1)

    # Determine output file
    if output is None:
        output = Path(f"{message_id}.eml")

    # Decode and parse email once
    raw_bytes = base64.urlsafe_b64decode(msg["raw"])
    parsed = BytesParser(policy=default).parsebytes(raw_bytes)

    # Write raw email to file
    output.write_bytes(raw_bytes)

    console.print(f"[bold green]✓[/bold green] Downloaded email to {output}")

    # Show brief preview using already-parsed email
    console.print("\n[bold]Email details:[/bold]")
    console.print(f"  From: {parsed.get('From', '')}")
    console.print(f"  To: {parsed.get('To', '')}")
    console.print(f"  Subject: {parsed.get('Subject', '')}")
    console.print(f"  Date: {parsed.get('Date', '')}")


@app.command()
def classify_event(
    eml_file: Annotated[Path, typer.Argument(help="Path to .eml file to classify")],
    no_cache: Annotated[bool, typer.Option("--no-cache", help="Skip cache and re-classify")] = False,
):
    """Recognize email template and extract structured data using OpenAI.

    This command is for debugging the template extractor. It reads an .eml file,
    extracts the subject/body/date, and uses OpenAI to determine which template
    (if any) the email matches and extracts structured data accordingly.

    Example:
        gmail-archiver classify-event inbox/19b18706c1c9ae8f.eml
    """
    if not eml_file.exists():
        print_error(f"File not found: {eml_file}")
        raise typer.Exit(code=1)

    # Parse .eml file
    console.print(f"Reading {eml_file}...")
    with eml_file.open("rb") as f:
        msg = BytesParser(policy=default).parse(f)

    # Extract message ID from filename (assumes format: <message_id>.eml)
    message_id = eml_file.stem

    subject = msg.get("Subject", "")
    date = msg.get("Date", "")

    # Get body (prefer plain text, fall back to HTML)
    body = ""
    html_body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain" and not body:
                body = part.get_content()
            elif content_type == "text/html" and not html_body:
                html_body = part.get_content()
    else:
        content_type = msg.get_content_type()
        if content_type == "text/plain":
            body = msg.get_content()
        elif content_type == "text/html":
            html_body = msg.get_content()

    # Fall back to HTML if no plain text
    if not body and html_body:
        body = BeautifulSoup(html_body, "html.parser").get_text(separator="\n", strip=True)

    console.print("\n[bold]Email Details:[/bold]")
    console.print(f"  Message ID: {message_id}")
    console.print(f"  Subject: {subject}")
    console.print(f"  Date: {date}")
    console.print(f"  Body length: {len(body)} chars\n")

    # Run async extractor
    async def extract():
        extractor = EmailTemplateExtractor()
        return await extractor.extract(
            message_id=message_id, subject=subject, body=body, received_date=date, use_cache=not no_cache
        )

    console.print("[bold]Extracting with OpenAI...[/bold]")
    result = asyncio.run(extract())

    # Display results
    console.print("\n[bold]Template Recognition Result:[/bold]")
    console.print_json(data=result.model_dump(mode="json"))

    # Show cache status
    cache_status = "skipped" if no_cache else "used/saved"
    console.print(f"\n[dim]Cache: {cache_status}[/dim]")


if __name__ == "__main__":
    app()
