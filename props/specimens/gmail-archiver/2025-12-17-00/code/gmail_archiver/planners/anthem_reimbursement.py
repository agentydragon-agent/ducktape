"""Planner for archiving old Anthem reimbursement emails."""

import contextlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import re

from bs4 import BeautifulSoup
from pydantic import BaseModel

from gmail_archiver.core import LABEL_AUTO_CLEANED, Plan
from gmail_archiver.gmail_api_models import SystemLabel
from gmail_archiver.inbox import GmailInbox
from gmail_archiver.models import GmailMessage


class AnthemReimbursement(BaseModel):
    patient_name: str | None = None
    care_date: datetime | None = None
    amount_you_pay: Decimal | None = None
    amount_deposited: Decimal | None = None
    claim_number_suffix: str | None = None
    email_date: datetime | None = None


def parse_anthem_reimbursement(email: GmailMessage) -> AnthemReimbursement:
    # Parse email date
    try:
        email_dt = datetime.strptime(email.date, "%a, %d %b %Y %H:%M:%S %z")
        email_dt = email_dt.replace(tzinfo=None)
    except (ValueError, AttributeError):
        email_dt = None

    # Extract text from HTML body
    soup = BeautifulSoup(email.body, "html.parser")
    for script in soup(["script", "style"]):
        script.decompose()
    text = soup.get_text()

    # Clean up whitespace
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = " ".join(chunk for chunk in chunks if chunk)

    # Extract structured data using regex
    patient = re.search(r"Patient name:\s*([A-Z]+)", text)
    care_date_match = re.search(r"Date of care:\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{2})", text)
    amount_pay = re.search(r"Amount you pay:\s*\$([0-9,]+\.[0-9]{2})", text)
    deposited = re.search(r"Amount we deposited:\s*\$([0-9,]+\.[0-9]{2})", text)
    claim_num = re.search(r"Claim number:\s*Ending in\s*(\d+)", text)

    # Parse care date (MM/DD/YY format)
    care_dt = None
    if care_date_match:
        with contextlib.suppress(ValueError):
            care_dt = datetime.strptime(care_date_match.group(1), "%m/%d/%y")

    # Parse amounts (remove commas from numbers like "8,676.65")
    amount_you_pay_decimal = None
    if amount_pay:
        with contextlib.suppress(ValueError, TypeError):
            amount_you_pay_decimal = Decimal(amount_pay.group(1).replace(",", ""))

    amount_deposited_decimal = None
    if deposited:
        with contextlib.suppress(ValueError, TypeError):
            amount_deposited_decimal = Decimal(deposited.group(1).replace(",", ""))

    return AnthemReimbursement(
        patient_name=patient.group(1) if patient else None,
        care_date=care_dt,
        amount_you_pay=amount_you_pay_decimal,
        amount_deposited=amount_deposited_decimal,
        claim_number_suffix=claim_num.group(1) if claim_num else None,
        email_date=email_dt,
    )


class AnthemReimbursementPlanner:
    """Archives Anthem reimbursements older than 30 days."""

    name = "Anthem reimbursements"
    DAYS_THRESHOLD = 30

    def plan(self, inbox: GmailInbox) -> Plan:
        plan = Plan(planner=self)

        # Fetch messages with insurance/anthem/reimbursement label that are in inbox
        messages = inbox.fetch_messages("label:insurance/anthem/reimbursement label:INBOX")

        cutoff_date = datetime.now(UTC) - timedelta(days=self.DAYS_THRESHOLD)

        for message in messages:
            parsed = parse_anthem_reimbursement(message)

            if not parsed.email_date:
                plan.add_action(message=message, labels_to_add=[], labels_to_remove=[], reason="No email date found")
                continue

            # Make date timezone-aware for comparison
            email_date = parsed.email_date
            if email_date.tzinfo is None:
                email_date = email_date.replace(tzinfo=UTC)

            if email_date >= cutoff_date:
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
        plan.add_message(f"Archiving {archive_count} old reimbursements (> {self.DAYS_THRESHOLD} days)")
        return plan
