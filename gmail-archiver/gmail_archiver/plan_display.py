"""Plan display and formatting functions."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from rich.console import Console
from rich.table import Table

from gmail_archiver.gmail_api_models import SystemLabel
from gmail_archiver.models import Email
from gmail_archiver.plan import Plan, PlannedAction

if TYPE_CHECKING:
    from gmail_archiver.inbox import GmailInbox


@runtime_checkable
class Displayable(Protocol):
    """Protocol for custom_data models that can display in plan tables."""

    @classmethod
    def display_columns(cls) -> list[tuple[str, str]]:
        """Return list of (key, header_label) for table columns."""
        ...

    def format_column(self, key: str) -> str:
        """Format the value for a given column key."""
        ...


def gmail_link(message_id: str) -> str:
    """Generate Rich markup hyperlink to Gmail web UI."""
    url = f"https://mail.google.com/mail/#all/{message_id}"
    return f"[link={url}]{message_id}[/link]"


def _collect_display_columns_for_actions(actions: list[PlannedAction]) -> list[tuple[str, str]]:
    """Collect display columns from Displayable custom_data in actions."""
    seen_keys: set[str] = set()
    columns: list[tuple[str, str]] = []
    for planned_action in actions:
        data = planned_action.action.custom_data
        if isinstance(data, Displayable):
            for key, label in data.display_columns():
                if key not in seen_keys:
                    seen_keys.add(key)
                    columns.append((key, label))
    return columns


def display_plan(plan: Plan, inbox: "GmailInbox", console: Console, dry_run: bool):
    if not plan.actions:
        console.print("[yellow]No actions planned[/yellow]")
        return

    # Ensure all messages are cached (batch-fetch any missing)
    inbox.ensure_metadata_cached(plan.actions.keys())

    # Group by planner
    by_planner: dict[str, list[tuple[str, PlannedAction]]] = {}
    for message_id, planned_action in plan.actions.items():
        planner_name = planned_action.planner_name or "Unknown"
        if planner_name not in by_planner:
            by_planner[planner_name] = []
        by_planner[planner_name].append((message_id, planned_action))

    # Display separate table per planner
    for planner_name, items in by_planner.items():
        # Collect custom columns for this planner's actions
        custom_columns = _collect_display_columns_for_actions([pa for _, pa in items])

        # Build table for this planner
        table = Table(title=planner_name)
        table.add_column("Action", style="cyan")
        table.add_column("Gmail Link", style="blue", no_wrap=True)
        table.add_column("Date", style="magenta")
        table.add_column("Subject", style="green")

        for _key, label in custom_columns:
            table.add_column(label, style="yellow")

        for message_id, planned_action in items:
            _add_table_row(table, inbox, message_id, planned_action, dry_run, custom_columns)

        console.print(table)
        console.print()


def _add_table_row(
    table: Table,
    inbox: "GmailInbox",
    message_id: str,
    planned_action: PlannedAction,
    dry_run: bool,
    custom_columns: list[tuple[str, str]],
):
    # Get message from inbox cache
    message = inbox.get_message(message_id)
    action = planned_action.action

    # Compute action icon
    has_ops = action.labels_to_add or action.labels_to_remove
    removes_inbox = SystemLabel.INBOX in action.labels_to_remove

    if not has_ops:
        action_icon = "📌 keep"
    elif removes_inbox:
        action_icon = "📦 would archive" if dry_run else "✓ archived"
    else:
        action_icon = "🏷️  label"

    # Format Gmail link (just show message ID)
    link = message_id[:16]

    # Format date and subject from message
    if isinstance(message, Email):
        date_str = (str(message.date) if message.date else "")[:20]
    else:
        date_str = (message.date_header or "")[:20]
    subject = (message.subject or "")[:40]

    # Format custom data values using protocol
    custom_values = []
    data = action.custom_data
    for key, _label in custom_columns:
        if isinstance(data, Displayable):
            custom_values.append(data.format_column(key))
        else:
            custom_values.append("")

    table.add_row(action_icon, link, date_str, subject, *custom_values)


def summarize_plan(plan: Plan) -> str:
    total = len(plan.actions)

    # Count actual operations
    remove_inbox = sum(1 for p in plan.actions.values() if SystemLabel.INBOX in p.action.labels_to_remove)
    add_labels = sum(len(p.action.labels_to_add) for p in plan.actions.values())
    remove_labels = sum(len(p.action.labels_to_remove) for p in plan.actions.values())
    no_op = sum(1 for p in plan.actions.values() if not p.action.labels_to_add and not p.action.labels_to_remove)

    parts = [f"Total: {total}"]
    if remove_inbox > 0:
        parts.append(f"Remove from inbox: {remove_inbox}")
    if add_labels > 0:
        parts.append(f"Add labels: {add_labels}")
    if remove_labels > 0:
        parts.append(f"Remove labels: {remove_labels}")
    if no_op > 0:
        parts.append(f"No-op: {no_op}")

    return ", ".join(parts)
