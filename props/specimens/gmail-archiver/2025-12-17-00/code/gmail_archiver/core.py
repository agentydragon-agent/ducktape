"""Core abstractions for gmail-archiver planning and execution."""

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel
from rich.console import Console
from rich.table import Table

from gmail_archiver.models import GmailMessage

if TYPE_CHECKING:
    from gmail_archiver.inbox import GmailInbox

console = Console()

# Shared label constant for general inbox cleanup (used by multiple planners)
LABEL_AUTO_CLEANED = "gmail-archiver/inbox-auto-cleaned"


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


@dataclass
class Action:
    """Gmail API operations to perform on an email."""

    labels_to_add: set[str] = field(default_factory=set)
    labels_to_remove: set[str] = field(default_factory=set)
    reason: str = ""
    custom_data: BaseModel | None = None


@dataclass
class PlannedAction:
    """Pairs a planner's decision (Action) for a message."""

    planner: "Planner"
    action: Action


class Plan:
    """A mapping from message IDs to planned actions.

    Manages plan → display → execute pattern for email archival.
    Uses dict to ensure each message_id can only be claimed by one planner.
    """

    def __init__(self, planner: "Planner"):
        self.planner = planner
        self.actions: dict[str, PlannedAction] = {}
        self.messages_by_id: dict[str, GmailMessage] = {}
        self.messages: list[str] = []

    def add_message(self, message: str):
        self.messages.append(message)

    def add_action(
        self,
        message: GmailMessage,
        labels_to_add: Sequence[str] = (),
        labels_to_remove: Sequence[str] = (),
        reason: str = "",
        custom_data: BaseModel | None = None,
    ):
        # Store message for display lookup
        self.messages_by_id[message.id] = message

        # Filter out no-op label operations based on message's current labels
        current_labels = set(message.label_ids)

        # Only add labels not already present
        effective_add = {lbl for lbl in labels_to_add if lbl not in current_labels}

        # Only remove labels that are present
        effective_remove = {lbl for lbl in labels_to_remove if lbl in current_labels}

        # Create action with effective operations only
        action = Action(
            labels_to_add=effective_add, labels_to_remove=effective_remove, reason=reason, custom_data=custom_data
        )

        # Check for collision
        if message.id in self.actions:
            existing = self.actions[message.id]
            raise ValueError(
                f"Message {message.id} already claimed by {existing.planner.name}, "
                f"cannot also be claimed by {self.planner.name}"
            )

        # Add planned action
        self.actions[message.id] = PlannedAction(planner=self.planner, action=action)

    @staticmethod
    def merge(plans: list["Plan"]) -> "Plan":
        """Merge multiple plans into one. Raises ValueError on conflicts."""
        if not plans:
            raise ValueError("Cannot merge empty list of plans")

        # Create merged plan (no specific planner owner)
        merged = Plan.__new__(Plan)
        merged.planner = None
        merged.actions = {}
        merged.messages_by_id = {}
        merged.messages = []

        for plan in plans:
            # Check for collisions before merging
            for message_id, planned_action in plan.actions.items():
                if message_id in merged.actions:
                    existing = merged.actions[message_id]
                    raise ValueError(
                        f"Message {message_id} claimed by both "
                        f"{existing.planner.name} and {planned_action.planner.name}"
                    )
                merged.actions[message_id] = planned_action

            # Merge message lookup dicts
            merged.messages_by_id.update(plan.messages_by_id)

            # Merge planner-specific messages with headers
            if plan.messages:
                merged.messages.append(f"[{plan.planner.name}]")
                merged.messages.extend(plan.messages)

        return merged

    def get_label_delta(self) -> tuple[Counter[str], Counter[str]]:
        """Compute label operation counts across all actions.

        Returns:
            Tuple of (add_counts, remove_counts) Counters mapping label to count.
        """
        add_counts: Counter[str] = Counter()
        remove_counts: Counter[str] = Counter()
        for pa in self.actions.values():
            add_counts.update(pa.action.labels_to_add)
            remove_counts.update(pa.action.labels_to_remove)
        return add_counts, remove_counts

    def format_delta_summary(self, label_name_map: dict[str, str] | None = None) -> str:
        """Format label delta as a human-readable summary.

        Args:
            label_name_map: Optional mapping from label IDs to display names.

        Returns:
            String like "Label1 +5, INBOX -3" or empty string if no operations.
        """
        add_counts, remove_counts = self.get_label_delta()
        if not add_counts and not remove_counts:
            return ""

        # Collect all labels and their +/- counts
        all_labels = set(add_counts.keys()) | set(remove_counts.keys())
        parts = []
        for lbl in sorted(all_labels):
            display_name = label_name_map.get(lbl, lbl) if label_name_map else lbl
            add = add_counts.get(lbl, 0)
            remove = remove_counts.get(lbl, 0)
            delta_parts = []
            if add:
                delta_parts.append(f"+{add}")
            if remove:
                delta_parts.append(f"-{remove}")
            parts.append(f"{display_name} {' '.join(delta_parts)}")
        return ", ".join(parts)

    def count_operations(self) -> int:
        """Count actions that have actual label operations."""
        return sum(1 for pa in self.actions.values() if pa.action.labels_to_add or pa.action.labels_to_remove)

    def execute(self, dry_run: bool, execute_fn: Callable[[str, Action], None]):
        actions_with_ops = self.count_operations()

        if dry_run:
            console.print(f"[yellow]DRY RUN:[/yellow] Would perform {actions_with_ops} label operation(s)")
        else:
            console.print("Executing label operations...")
            executed = 0
            for message_id, planned_action in self.actions.items():
                if planned_action.action.labels_to_add or planned_action.action.labels_to_remove:
                    execute_fn(message_id, planned_action.action)
                    executed += 1
            console.print(f"[green]✓[/green] Executed {executed} label operation(s)")


def _collect_display_columns(plan: Plan) -> list[tuple[str, str]]:
    """Collect display columns from all Displayable custom_data in plan."""
    seen_keys: set[str] = set()
    columns: list[tuple[str, str]] = []
    for planned_action in plan.actions.values():
        data = planned_action.action.custom_data
        if isinstance(data, Displayable):
            for key, label in data.display_columns():
                if key not in seen_keys:
                    seen_keys.add(key)
                    columns.append((key, label))
    return columns


def display_plan(plan: Plan, dry_run: bool, group_by_category: bool = False):
    if not plan.actions:
        console.print("[yellow]No actions planned[/yellow]")
        return

    # Build table
    table = Table(title="Inbox Cleanup - Action Plan")
    table.add_column("Action", style="cyan")
    table.add_column("Gmail Link", style="blue", no_wrap=True)
    table.add_column("Date", style="magenta")
    table.add_column("Subject", style="green")

    # Collect custom columns from Displayable models
    custom_columns = _collect_display_columns(plan)

    # Add custom columns
    for _key, label in custom_columns:
        table.add_column(label, style="yellow")

    # Group by planner if requested
    if group_by_category and plan.planner is None:
        # Merged plan - group by planner
        by_planner: dict[str, list[tuple[str, PlannedAction]]] = {}
        for message_id, planned_action in plan.actions.items():
            planner_name = planned_action.planner.name
            if planner_name not in by_planner:
                by_planner[planner_name] = []
            by_planner[planner_name].append((message_id, planned_action))

        # Display grouped
        for planner_name, items in by_planner.items():
            # Add planner header row
            table.add_row(f"[bold]{planner_name}[/bold]", "", "", "", *[""] * len(custom_columns))

            # Add items for this planner
            for message_id, planned_action in items:
                _add_table_row(table, plan, message_id, planned_action, dry_run, custom_columns)

            # Add blank separator row
            table.add_row("", "", "", "", *[""] * len(custom_columns))
    else:
        # Single planner or no grouping - just list all
        for message_id, planned_action in plan.actions.items():
            _add_table_row(table, plan, message_id, planned_action, dry_run, custom_columns)

    console.print(table)


def _add_table_row(
    table,
    plan: Plan,
    message_id: str,
    planned_action: PlannedAction,
    dry_run: bool,
    custom_columns: list[tuple[str, str]],
):
    # Look up message
    message = plan.messages_by_id[message_id]

    # Compute action icon
    action = planned_action.action
    has_ops = action.labels_to_add or action.labels_to_remove
    removes_inbox = "INBOX" in action.labels_to_remove

    if not has_ops:
        action_icon = "📌 keep"
    elif removes_inbox:
        action_icon = "📦 would archive" if dry_run else "✓ archived"
    else:
        action_icon = "🏷️  label"

    # Format Gmail link (just show message ID)
    link = message_id[:16]

    # Format date (truncate to fit)
    date_str = message.date[:20] if message.date else ""

    # Format subject (truncate)
    subject = message.subject[:40] if message.subject else ""

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
    remove_inbox = sum(1 for p in plan.actions.values() if "INBOX" in p.action.labels_to_remove)
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


class Planner(Protocol):
    """Protocol for inbox cleanup categories."""

    name: str

    def plan(self, inbox: "GmailInbox") -> Plan: ...
