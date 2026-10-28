"""Present typed reconciliation at API and terminal boundaries."""

from finance.plaid.spend.allowance import AllowanceCalculation, AllowanceView
from finance.plaid.spend.reconciliation import ReconciliationReport, ReversalIssueCode, ReversalRole
from finance.plaid.spend.sustainability import SustainabilityCalculation, SustainabilityView


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


def allowance_view(calculation: AllowanceCalculation) -> AllowanceView:
    """Preserve the existing strict terminal-client wire shape."""
    messages = describe_reconciliation(calculation.reconciliation)
    return calculation.view.model_copy(update={"note": "Provisional: " + " ".join(messages) if messages else None})


def sustainability_view(calculation: SustainabilityCalculation) -> SustainabilityView:
    return calculation.view.model_copy(
        update={
            "issues": [
                *calculation.view.issues,
                *describe_reconciliation(calculation.reconciliation),
                *(
                    "Historical chart: " + message
                    for message in describe_reconciliation(calculation.historical_reconciliation)
                ),
            ]
        }
    )
