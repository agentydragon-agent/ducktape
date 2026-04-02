"""Pydantic models for EOB payment matching."""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ClaimType(StrEnum):
    MEDICAL = "Medical"
    PHARMACY = "Pharmacy"


class Claim(BaseModel):
    """A single insurance claim from the Anthem claims CSV."""

    claim_number: str
    claim_type: ClaimType
    patient: str
    service_date: str
    claim_received: str
    status: str
    processed_date: str
    provider: str
    billed: float | None = Field(default=None, ge=0)
    plan_discount: float | None = None
    allowed: float | None = Field(default=None, ge=0)
    plan_paid: float | None = Field(default=None, ge=0)
    additional_savings: float | None = Field(default=None, ge=0)
    deductible: float | None = Field(default=None, ge=0)
    coinsurance: float | None = Field(default=None, ge=0)
    copay: float | None = Field(default=None, ge=0)
    not_covered: float | None = Field(default=None, ge=0)
    your_cost: float | None = Field(default=None, ge=0)

    # Computed
    plan_paid_cents: int | None = None
    processed_date_dt: datetime | None = None

    def model_post_init(self, _context: object) -> None:
        self.plan_paid_cents = round(self.plan_paid * 100) if self.plan_paid is not None else None
        self.processed_date_dt = parse_claims_csv_date(self.processed_date)


class EOB(BaseModel):
    """An Explanation of Benefits from the Anthem portal listing."""

    statement_date: str
    service_dates: str
    claim_nums: list[str]
    provider: str
    your_costs: list[str]

    # Computed after joining with claims
    plan_paid_total: float = 0.0
    plan_paid_cents: int = 0
    latest_proc_date: datetime | None = None


class BankPayment(BaseModel):
    """An Anthem EFT deposit from the bank statement."""

    date: str
    date_dt: datetime
    payment_id: str
    amount: float = Field(gt=0)
    cents: int = Field(gt=0)


class MatchedItem(BaseModel):
    """An EOB or orphan pharmacy claim matched to a payment."""

    claim_nums: list[str]
    provider: str
    plan_paid_total: float
    is_pharmacy_orphan: bool = False


class Matched(BaseModel):
    """Successfully matched to claims."""

    items: list[MatchedItem]
    total_claims: int


class NotMatched(BaseModel):
    """No matching claim subset found."""

    candidate_count: int = Field(description="Number of candidate items considered")


MatchingResult = Matched | NotMatched


class PaymentResult(BaseModel):
    """A bank payment with its matching result."""

    payment: BankPayment
    result: MatchingResult


class DetailRow(BaseModel):
    """One row in the detail output CSV."""

    payment_date: str
    payment_amount: float
    payment_id: str
    claim_num: str
    provider: str
    service_date: str
    plan_paid: float | None
    your_cost: float | None


class SummaryRow(BaseModel):
    """One row in the summary output CSV."""

    payment_date: str
    payment_amount: float
    payment_id: str
    providers: list[str]
    claim_count: int
    claim_nums: list[str]
    matched: bool


class ExtractedDate(BaseModel):
    """Date as integer components — more reliable than string format for LLM extraction."""

    year: int = Field(ge=2020, le=2030, description="4-digit year, e.g. 2025")
    month: int = Field(ge=1, le=12, description="Month number 1-12")
    day: int = Field(ge=1, le=31, description="Day of month 1-31")

    def to_date(self) -> date:
        return date(self.year, self.month, self.day)


class EOBSummaryExtraction(BaseModel):
    """Financial summary from EOB page 1."""

    statement_date: ExtractedDate = Field(description="Date shown next to 'Health Care Summary'")
    doctor_facility_charges: float = Field(ge=0, description="Positive dollar amount from 'Doctor/facility charges'")
    your_discounts: float = Field(le=0, description="Negative dollar amount from 'Your discounts' (0 or negative)")
    allowed_amount: float = Field(
        ge=0, description="Positive dollar amount from 'Due to your doctor/facility max allowed'"
    )
    anthem_blue_cross_paid: float = Field(
        le=0, description="Negative dollar amount from 'Anthem Blue Cross paid' (always negative, e.g. -4757.89)"
    )
    what_you_pay: float = Field(ge=0, description="Positive dollar amount from 'What you may pay' or 'What you pay'")


class EOBClaimLineExtraction(BaseModel):
    """A single service line row from a claims detail table."""

    service_date: ExtractedDate = Field(description="Date in the 'Service date' column")
    service_description: str = Field(description="Service type, e.g. 'Therapeutic Services', 'Drug Non-Oral'")
    doctor_charges: float = Field(ge=0, description="Positive dollar amount from 'Doctor charges' column")
    anthem_blue_cross_paid: float = Field(
        ge=0, description="Positive dollar amount from 'Anthem Blue Cross paid' column"
    )
    copay: float = Field(ge=0, description="Dollar amount from 'Copay' column, 0 if none")
    deductible: float = Field(ge=0, description="Dollar amount from 'Deductible' column, 0 if none")
    coinsurance: float = Field(
        ge=0, description="Dollar amount from 'Your share of the cost (coinsurance)' column, 0 if none"
    )
    services_not_covered: float = Field(ge=0, description="Dollar amount from 'Services not covered' column, 0 if none")
    your_total_cost: float = Field(
        le=0, description="Negative dollar amount from 'Your total cost' column (shown in pink, e.g. -0.00)"
    )


class EOBClaimExtraction(BaseModel):
    """A single claim block from an EOB claims detail page."""

    claim_number: str = Field(description="Claim Number value, e.g. '20253502A2522'")
    received_date: ExtractedDate = Field(description="Date after 'Received:'")
    doctor_name: str = Field(description="Doctor/provider name after 'Doctor:'")
    in_network: bool = Field(description="True if in-network, False if 'Not in your plan' or 'out-of-network'")
    you_pay_total: float = Field(description="Dollar amount from 'You pay $X.XX' header (positive)")
    lines: list[EOBClaimLineExtraction] = Field(description="All service line rows in this claim's table")


class EOBClaimsPageExtraction(BaseModel):
    """All claims on one EOB claims detail page."""

    claims: list[EOBClaimExtraction] = Field(description="All claim blocks on this page (usually 1-2 per page)")


CLAIMS_CSV_DATE_FORMAT = "%b %d, %Y"  # e.g. "Apr 1, 2025"


def parse_claims_csv_date(s: str) -> datetime | None:
    """Parse a date from the Anthem claims CSV ('Mon D, YYYY' format)."""
    s = s.strip()
    if not s or s == "Not Available":
        return None
    return datetime.strptime(s, CLAIMS_CSV_DATE_FORMAT)


def parse_dollar(s: str) -> float | None:
    """Parse a dollar amount string like '$ 1,234.56' into a float, or None if unavailable."""
    cleaned = s.replace("$", "").replace(",", "").strip()
    if not cleaned or cleaned == "Not Available":
        return None
    return float(cleaned)
