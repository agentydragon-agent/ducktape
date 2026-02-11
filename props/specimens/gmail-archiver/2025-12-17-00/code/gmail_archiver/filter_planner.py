"""FilterPlanner - integrates YAML filters with the Plan system."""

from gmail_archiver.core import Plan
from gmail_archiver.gmail_api_models import FilterCriteria, GmailFilter
from gmail_archiver.gmail_yaml_filters_models import FilterRule
from gmail_archiver.inbox import GmailInbox


def criteria_to_gmail_query(criteria: FilterCriteria) -> str:
    """Convert FilterCriteria to Gmail search query string."""
    parts = []
    if criteria.from_:
        parts.append(f"from:({criteria.from_})")
    if criteria.to:
        parts.append(f"to:({criteria.to})")
    if criteria.subject:
        parts.append(f"subject:({criteria.subject})")
    if criteria.query:
        parts.append(criteria.query)
    if criteria.negated_query:
        parts.append(f"-({criteria.negated_query})")
    return " ".join(parts)


def rule_to_gmail_query(rule: FilterRule) -> str:
    """Convert FilterRule to Gmail search query string."""
    parts = []

    if isinstance(rule.from_, str):
        parts.append(f"from:({rule.from_})")
    if isinstance(rule.to, str):
        parts.append(f"to:({rule.to})")
    if isinstance(rule.subject, str):
        parts.append(f"subject:({rule.subject})")
    if isinstance(rule.has, str):
        parts.append(rule.has)
    elif isinstance(rule.has, list):
        parts.extend(rule.has)
    if isinstance(rule.does_not_have, str):
        parts.append(f"-({rule.does_not_have})")
    elif isinstance(rule.does_not_have, list):
        for term in rule.does_not_have:
            parts.append(f"-({term})")

    # Additional search operators
    if isinstance(rule.bcc, str):
        parts.append(f"bcc:({rule.bcc})")
    if isinstance(rule.cc, str):
        parts.append(f"cc:({rule.cc})")
    if isinstance(rule.list, str):
        parts.append(f"list:({rule.list})")
    if isinstance(rule.filename, str):
        parts.append(f"filename:({rule.filename})")
    if rule.larger:
        parts.append(f"larger:{rule.larger}")
    if rule.smaller:
        parts.append(f"smaller:{rule.smaller}")

    return " ".join(parts)


class SingleFilterPlanner:
    """Planner that applies a single filter rule to matching emails."""

    def __init__(self, rule: FilterRule, additional_query: str | None = None):
        self.rule = rule
        self.additional_query = additional_query
        self.name = f"Filter: {rule.label or 'unnamed'}"

    def plan(self, inbox: GmailInbox) -> Plan:
        plan = Plan(planner=self)

        # Build query
        query = rule_to_gmail_query(self.rule)
        if not query:
            plan.add_message("No criteria specified, skipping")
            return plan

        # Add additional query constraint if provided
        if self.additional_query:
            query = f"({query}) ({self.additional_query})"

        # Fetch matching messages
        messages = inbox.fetch_messages(query)

        if not messages:
            plan.add_message(f"No messages match: {query[:50]}...")
            return plan

        plan.add_message(f"Found {len(messages)} matching messages")

        # Build actions
        labels_to_add = []
        if self.rule.label:
            labels_to_add.append(self.rule.label)
        if self.rule.star:
            labels_to_add.append("STARRED")
        if self.rule.important or self.rule.mark_as_important:
            labels_to_add.append("IMPORTANT")

        labels_to_remove = []
        if self.rule.archive:
            labels_to_remove.append("INBOX")
        if self.rule.read or self.rule.mark_as_read:
            labels_to_remove.append("UNREAD")

        # If no label operations, skip
        if not labels_to_add and not labels_to_remove:
            plan.add_message("No label actions defined for this filter")
            return plan

        for message in messages:
            plan.add_action(
                message=message,
                labels_to_add=labels_to_add,
                labels_to_remove=labels_to_remove,
                reason="Matches filter criteria",
            )

        return plan


def create_filter_planners(rules: list[FilterRule], additional_query: str | None = None) -> list[SingleFilterPlanner]:
    """Create planners for filter rules.

    Args:
        rules: List of FilterRule instances to create planners for
        additional_query: Additional Gmail query to add to all filters

    Returns:
        List of SingleFilterPlanner instances
    """
    planners = []

    for rule in rules:
        # Skip rules without any criteria
        query = rule_to_gmail_query(rule)
        if not query:
            continue

        planners.append(SingleFilterPlanner(rule, additional_query=additional_query))

    return planners


class GmailFilterPlanner:
    """Planner that applies a Gmail API filter to matching emails."""

    def __init__(self, gmail_filter: GmailFilter, labels_by_id: dict[str, str], additional_query: str | None = None):
        self.gmail_filter = gmail_filter
        self.labels_by_id = labels_by_id
        self.additional_query = additional_query

        # Build display name from filter criteria
        criteria = gmail_filter.criteria
        name_parts = []
        if criteria.from_:
            name_parts.append(f"from:{criteria.from_}")
        if criteria.subject:
            name_parts.append(f"subject:{criteria.subject}")
        if criteria.query:
            name_parts.append(criteria.query)
        suffix = " ".join(name_parts)[:50] if name_parts else "(unnamed)"
        self.name = f"Filter: {suffix}"

    def plan(self, inbox: GmailInbox) -> Plan:
        plan = Plan(planner=self)

        # Build query from filter criteria
        query = criteria_to_gmail_query(self.gmail_filter.criteria)
        if not query:
            plan.add_message("No search criteria")
            return plan

        if self.additional_query:
            query = f"({query}) ({self.additional_query})"

        # Fetch messages (minimal format for efficiency)
        messages = inbox.fetch_messages_minimal(query)

        if not messages:
            plan.add_message(f"No messages match: {query[:50]}...")
            return plan

        plan.add_message(f"Found {len(messages)} matching messages")

        # Get label operations (use IDs directly since Plan handles them)
        action = self.gmail_filter.action
        if not action.add_label_ids and not action.remove_label_ids:
            plan.add_message("No label actions defined")
            return plan

        for message in messages:
            plan.add_action(
                message=message,
                labels_to_add=action.add_label_ids,
                labels_to_remove=action.remove_label_ids,
                reason="Matches filter criteria",
            )

        return plan
