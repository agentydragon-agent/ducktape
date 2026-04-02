"""Data loaders for EOB payment matching."""

import csv
import json
import re
from datetime import datetime
from pathlib import Path

from x.eob_matching.models import EOB, BankPayment, Claim, ClaimType, parse_dollar


def load_claims(path: Path) -> dict[str, Claim]:
    """Load claims from Anthem claims CSV. Returns dict keyed by claim number."""
    claims: dict[str, Claim] = {}
    with path.open() as f:
        for row in csv.DictReader(f):
            claim = Claim(
                claim_number=row["Claim Number"],
                claim_type=ClaimType(row["Claim Type"]),
                patient=row["Patient"].strip(),
                service_date=row["Service Date"].strip(),
                claim_received=row["Claim Received"].strip(),
                status=row["Status"].strip(),
                processed_date=row["Processed Date"].strip(),
                provider=row["Provided By"].strip(),
                billed=parse_dollar(row["Billed"]),
                plan_discount=parse_dollar(row["Plan Discount"]),
                allowed=parse_dollar(row["Allowed"]),
                plan_paid=parse_dollar(row["Plan Paid"]),
                additional_savings=parse_dollar(row["Additional Savings"]),
                deductible=parse_dollar(row["Deductible"]),
                coinsurance=parse_dollar(row["Coinsurance"]),
                copay=parse_dollar(row["Copay"]),
                not_covered=parse_dollar(row["Not Covered"]),
                your_cost=parse_dollar(row["Your Cost"]),
            )
            claims[claim.claim_number] = claim
    return claims


def load_eob_listing(path: Path) -> list[EOB]:
    """Load parsed EOB listing JSON."""
    return [EOB(**item) for item in json.loads(path.read_text())]


def load_bank_payments(path: Path) -> list[BankPayment]:
    """Parse Anthem EFT deposits from bank statement text file."""
    payments: list[BankPayment] = []
    pattern = re.compile(r"(\d{2}/\d{2}/\d{4})\s+.*?ID:(XXXXX\d+)\s.*?\s+([\d,]+\.\d{2})\s")
    with path.open() as f:
        for line in f:
            if "ANTHEM BLUE" not in line:
                continue
            m = pattern.match(line)
            if m:
                amount = float(m.group(3).replace(",", ""))
                payments.append(
                    BankPayment(
                        date=m.group(1),
                        date_dt=datetime.strptime(m.group(1), "%m/%d/%Y"),
                        payment_id=m.group(2),
                        amount=amount,
                        cents=round(amount * 100),
                    )
                )
    payments.sort(key=lambda p: p.date_dt)
    return payments


def enrich_eobs(eobs: list[EOB], claims: dict[str, Claim]) -> list[EOB]:
    """Compute plan_paid_total and latest_proc_date for each EOB from claims data."""
    for eob in eobs:
        total = 0.0
        latest_proc: datetime | None = None
        for cn in eob.claim_nums:
            claim = claims.get(cn)
            if claim is None:
                continue
            if claim.plan_paid is None:
                continue
            total += claim.plan_paid
            if claim.processed_date_dt is not None and (latest_proc is None or claim.processed_date_dt > latest_proc):
                latest_proc = claim.processed_date_dt
        eob.plan_paid_total = total
        eob.plan_paid_cents = round(total * 100)
        eob.latest_proc_date = latest_proc
    return eobs


def deduplicate_eobs(eobs: list[EOB]) -> list[EOB]:
    """Deduplicate EOBs by claim set, keeping the most recent statement date."""
    seen: dict[frozenset[str], EOB] = {}
    for eob in eobs:
        key = frozenset(eob.claim_nums)
        if key not in seen or eob.statement_date > seen[key].statement_date:
            seen[key] = eob
    return list(seen.values())


def find_pharmacy_orphans(claims: dict[str, Claim], eob_claim_nums: set[str]) -> list[EOB]:
    """Find pharmacy claims not in any EOB, wrapped as pseudo-EOBs."""
    orphans: list[EOB] = []
    for cn, claim in claims.items():
        if cn in eob_claim_nums or claim.plan_paid is None or claim.plan_paid <= 0:
            continue
        orphans.append(
            EOB(
                statement_date="",
                service_dates=claim.service_date,
                claim_nums=[cn],
                provider=claim.provider,
                your_costs=[],
                plan_paid_total=claim.plan_paid,
                plan_paid_cents=round(claim.plan_paid * 100),
                latest_proc_date=claim.processed_date_dt,
            )
        )
    return orphans
