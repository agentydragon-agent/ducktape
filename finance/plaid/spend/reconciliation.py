"""Typed reversal evidence and report relevance, independent of classification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class ReportStatus(StrEnum):
    READY = "ready"
    PROVISIONAL = "provisional"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


class ReversalRole(StrEnum):
    ORIGINAL = "original"
    REVERSAL = "reversal"


class ReversalIssueCode(StrEnum):
    MISSING_LEG = "missing_leg"
    AMBIGUOUS_MATCH = "ambiguous_match"
    PENDING_LEG = "pending_leg"
    OVERLAPPING_PAIR = "overlapping_pair"
    SAME_TRANSACTION = "same_transaction"
    AMOUNT_MISMATCH = "amount_mismatch"
    ACCOUNT_MISMATCH = "account_mismatch"
    CURRENCY_MISMATCH = "currency_mismatch"


@dataclass(frozen=True)
class ReversalIssue:
    code: ReversalIssueCode
    role: ReversalRole | None = None

    def __post_init__(self) -> None:
        selector_issue = self.code in (
            ReversalIssueCode.MISSING_LEG,
            ReversalIssueCode.AMBIGUOUS_MATCH,
            ReversalIssueCode.PENDING_LEG,
        )
        if selector_issue != (self.role is not None):
            raise ValueError("Only selector issues require a reversal leg role")


@dataclass(frozen=True)
class ReversalMatch:
    account_id: str
    transaction_id: str
    report_day: date


@dataclass(frozen=True)
class ReversalLeg:
    posting_start: date
    posting_end: date
    matches: tuple[ReversalMatch, ...]


@dataclass(frozen=True)
class ReversalPairResolution:
    """An unresolved assertion adjusts neither leg; matches retain their ordinary accounting."""

    pair_id: str
    original: ReversalLeg
    reversal: ReversalLeg
    issues: tuple[ReversalIssue, ...]

    def affects_period(self, *, start: date | None, end: date | None) -> bool:
        if not self.issues:
            return False
        # A missing row has no known purchase day. Posting selector bounds cannot
        # safely stand in for authorization dates/times used by spend reports.
        if not self.original.matches or not self.reversal.matches:
            return True
        return any(
            (start is None or match.report_day >= start) and (end is None or match.report_day <= end)
            for leg in (self.original, self.reversal)
            for match in leg.matches
        )


@dataclass(frozen=True)
class ReconciliationReport:
    resolutions: tuple[ReversalPairResolution, ...] = ()

    @property
    def status(self) -> ReportStatus:
        return ReportStatus.PROVISIONAL if any(r.issues for r in self.resolutions) else ReportStatus.READY

    def for_period(self, *, start: date | None, end: date | None) -> ReconciliationReport:
        if start is not None and end is not None and start > end:
            raise ValueError("Report period start must not follow its end")
        return ReconciliationReport(
            resolutions=tuple(r for r in self.resolutions if r.affects_period(start=start, end=end))
        )


def describe_reconciliation(report: ReconciliationReport) -> list[str]:
    """Render actionable messages without exposing account or transaction identifiers."""
    messages = []
    for resolution in report.resolutions:
        for issue in resolution.issues:
            leg = resolution.original if issue.role == ReversalRole.ORIGINAL else resolution.reversal
            match issue.code:
                case ReversalIssueCode.MISSING_LEG | ReversalIssueCode.AMBIGUOUS_MATCH:
                    assert issue.role is not None
                    detail = (
                        f"{issue.role.capitalize()} selector matched {len(leg.matches)} retained transactions; "
                        f"exactly one is required (posting dates {leg.posting_start} through {leg.posting_end})."
                    )
                    if issue.code == ReversalIssueCode.MISSING_LEG:
                        detail += " Its purchase-day scope is unknown."
                case ReversalIssueCode.PENDING_LEG:
                    assert issue.role is not None
                    detail = f"{issue.role.capitalize()} transaction is still pending."
                case ReversalIssueCode.OVERLAPPING_PAIR:
                    detail = "A transaction also matches another reversal pair."
                case ReversalIssueCode.SAME_TRANSACTION:
                    detail = "Original and reversal must be distinct transactions."
                case ReversalIssueCode.AMOUNT_MISMATCH:
                    detail = "Amounts must be equal and opposite, with a positive original and a negative reversal."
                case ReversalIssueCode.ACCOUNT_MISMATCH:
                    detail = "Transactions must belong to the same account."
                case ReversalIssueCode.CURRENCY_MISMATCH:
                    detail = "Both transactions must use the policy currency."
            messages.append(
                f"Reversal pair {resolution.pair_id}: {detail} "
                "Ordinary accounting retained; review the selectors and source transactions."
            )
    return messages
