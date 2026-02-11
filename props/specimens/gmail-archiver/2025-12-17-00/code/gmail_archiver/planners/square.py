"""Planner for archiving small Square receipt emails."""

import contextlib
from datetime import datetime
from decimal import Decimal
import re

from bs4 import BeautifulSoup
from pydantic import BaseModel

from gmail_archiver.core import LABEL_AUTO_CLEANED, Plan
from gmail_archiver.gmail_api_models import SystemLabel
from gmail_archiver.inbox import GmailInbox
from gmail_archiver.models import GmailMessage


class SquareReceipt(BaseModel):
    merchant_name: str | None = None
    amount: Decimal | None = None
    card_type: str | None = None
    card_last4: str | None = None
    transaction_datetime: datetime | None = None
    email_date: datetime | None = None

    @classmethod
    def display_columns(cls) -> list[tuple[str, str]]:
        return [("amount", "Amount"), ("merchant_name", "Merchant")]

    def format_column(self, key: str) -> str:
        if key == "amount":
            return f"${self.amount}" if self.amount else ""
        if key == "merchant_name":
            return self.merchant_name or ""
        return ""


def parse_square(email: GmailMessage) -> SquareReceipt:
    # Parse email date
    email_dt = None
    with contextlib.suppress(ValueError, AttributeError):
        email_dt = datetime.strptime(email.date, "%a, %d %b %Y %H:%M:%S %z")
        email_dt = email_dt.replace(tzinfo=None)

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
    # Pattern: "You paid $27.78 with your Visa ending in 6915 to Bean Scene Cafe on Mar 16 2023 at 10:26 AM."
    # Captures datetime up to period or end of string
    payment_pattern = re.search(
        r"You paid \$([0-9,]+\.[0-9]{2}) with your (\w+) ending in (\d{4}) to (.+?) on ([^.]+?)(?:\.|$)", text
    )

    amount_decimal = None
    card_type = None
    card_last4 = None
    merchant_name = None
    transaction_dt = None

    if payment_pattern:
        # Extract amount
        with contextlib.suppress(ValueError, TypeError):
            amount_decimal = Decimal(payment_pattern.group(1).replace(",", ""))

        # Extract card details
        card_type = payment_pattern.group(2)
        card_last4 = payment_pattern.group(3)

        # Extract merchant name
        merchant_name = payment_pattern.group(4)

        # Extract transaction datetime (try to parse, fail silently if format doesn't match)
        # Expected format: "Mar 16 2023 at 10:26 AM"
        datetime_str = payment_pattern.group(5).strip()
        with contextlib.suppress(ValueError):
            transaction_dt = datetime.strptime(datetime_str, "%b %d %Y at %I:%M %p")

    return SquareReceipt(
        merchant_name=merchant_name,
        amount=amount_decimal,
        card_type=card_type,
        card_last4=card_last4,
        transaction_datetime=transaction_dt,
        email_date=email_dt,
    )


class SquarePlanner:
    """Archives Square receipts under $30."""

    name = "Square receipts"
    THRESHOLD = Decimal("30.00")

    def plan(self, inbox: GmailInbox) -> Plan:
        plan = Plan(planner=self)

        # Fetch messages using inbox interface
        query = "from:receipts@messaging.squareup.com in:inbox"
        messages = inbox.fetch_messages(query)

        for message in messages:
            parsed = parse_square(message)

            if not parsed.amount:
                plan.add_action(
                    message=message, labels_to_add=[], labels_to_remove=[], reason="No amount found", custom_data=parsed
                )
                continue

            if parsed.amount < self.THRESHOLD:
                plan.add_action(
                    message=message,
                    labels_to_add=[LABEL_AUTO_CLEANED],
                    labels_to_remove=[SystemLabel.INBOX],
                    reason=f"Amount < ${self.THRESHOLD}",
                    custom_data=parsed,
                )
            else:
                plan.add_action(
                    message=message,
                    labels_to_add=[],
                    labels_to_remove=[],
                    reason=f"Amount >= ${self.THRESHOLD}",
                    custom_data=parsed,
                )

        return plan
