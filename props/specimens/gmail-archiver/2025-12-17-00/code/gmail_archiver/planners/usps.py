"""Planner for archiving old USPS Informed Delivery emails."""

from datetime import UTC, datetime, timedelta
import re

from pydantic import BaseModel

from gmail_archiver.core import LABEL_AUTO_CLEANED, Plan
from gmail_archiver.date_patterns import DAYS_OF_WEEK, MONTHS
from gmail_archiver.gmail_api_models import SystemLabel
from gmail_archiver.inbox import GmailInbox
from gmail_archiver.models import GmailMessage


class USPSDelivery(BaseModel):
    expected_delivery_date: datetime | None = None


# Subject patterns:
#   - "USPS® Expected Delivery by Thursday, December 18, 2025 arriving by 9:00pm"
#   - "USPS® Expected Delivery on Monday, December 15, 2025 arriving by 7:20pm"
_DATE_PATTERN = re.compile(rf"(?:by|on)\s+({DAYS_OF_WEEK},\s+{MONTHS}\s+\d+,\s+\d{{4}})", re.IGNORECASE)


def can_parse_usps(email: GmailMessage) -> bool:
    if not email.subject:
        return False
    return bool(_DATE_PATTERN.search(email.subject))


def parse_usps(email: GmailMessage) -> USPSDelivery:
    """Extract expected delivery date from subject. Raises ValueError if unparseable."""
    if not email.subject:
        raise ValueError("Email has no subject")

    match = _DATE_PATTERN.search(email.subject)
    if not match:
        raise ValueError(f"Could not extract delivery date from subject: {email.subject}")

    date_str = match.group(1)  # e.g., "Thursday, December 18, 2025"

    try:
        expected_delivery_date = datetime.strptime(date_str, "%A, %B %d, %Y")
    except ValueError as e:
        raise ValueError(f"Failed to parse date '{date_str}': {e}")

    return USPSDelivery(expected_delivery_date=expected_delivery_date)


class UspsPlanner:
    """Archives USPS Informed Delivery emails older than 7 days."""

    name = "USPS Informed Delivery"
    DAYS_THRESHOLD = 7

    def plan(self, inbox: GmailInbox) -> Plan:
        plan = Plan(planner=self)

        # Fetch messages with batch/usps-informed-delivery label that are in inbox
        messages = inbox.fetch_messages("label:batch/usps-informed-delivery label:INBOX")

        cutoff_date = datetime.now(UTC) - timedelta(days=self.DAYS_THRESHOLD)

        for message in messages:
            if not can_parse_usps(message):
                plan.add_action(message=message, labels_to_add=[], labels_to_remove=[], reason="Parser cannot handle")
                continue

            parsed = parse_usps(message)

            if not parsed.expected_delivery_date:
                plan.add_action(
                    message=message, labels_to_add=[], labels_to_remove=[], reason="No expected delivery date found"
                )
                continue

            # Make date timezone-aware for comparison
            delivery_date = parsed.expected_delivery_date
            if delivery_date.tzinfo is None:
                delivery_date = delivery_date.replace(tzinfo=UTC)

            if delivery_date >= cutoff_date:
                plan.add_action(
                    message=message,
                    labels_to_add=[],
                    labels_to_remove=[],
                    reason=f"Too recent (within {self.DAYS_THRESHOLD} days)",
                )
            else:
                plan.add_action(
                    message=message,
                    labels_to_add=[LABEL_AUTO_CLEANED],
                    labels_to_remove=[SystemLabel.INBOX],
                    reason=f"Old enough (> {self.DAYS_THRESHOLD} days)",
                )

        # Count actual archive operations
        archive_count = sum(1 for pa in plan.actions.values() if SystemLabel.INBOX in pa.action.labels_to_remove)
        plan.add_message(f"Archiving {archive_count} old deliveries (> {self.DAYS_THRESHOLD} days)")
        return plan
