"""DP subset-sum matcher for EOB payment matching."""

from x.eob_matching.models import EOB, BankPayment, Matched, MatchedItem, NotMatched, PaymentResult


def dp_subset_sum(items: list[EOB], target_cents: int) -> list[EOB] | None:
    """Find a subset of items whose plan_paid_cents sum to target_cents.

    Uses 0-1 knapsack DP. Returns the subset or None if no solution.
    Bails out for targets > $500k to avoid memory issues.
    """
    if target_cents > 50_000_000 or not items:
        return None

    unreachable = -2
    dp = [unreachable] * (target_cents + 1)
    dp[0] = -1

    for i, item in enumerate(items):
        c = item.plan_paid_cents
        if c <= 0 or c > target_cents:
            continue
        for j in range(target_cents, c - 1, -1):
            if dp[j] == unreachable and dp[j - c] != unreachable:
                dp[j] = i

    if dp[target_cents] == unreachable:
        return None

    result: list[EOB] = []
    j = target_cents
    while j > 0:
        i = dp[j]
        result.append(items[i])
        j -= items[i].plan_paid_cents
    return result


def match_payments(payments: list[BankPayment], eobs: list[EOB], pharmacy_orphans: list[EOB]) -> list[PaymentResult]:
    """Match each bank payment to a subset of EOBs + pharmacy claims by amount.

    Processes payments chronologically. For each payment, only considers
    items whose claims were processed on or before the payment date.
    Matched items are removed from the candidate pool.
    """
    all_items = eobs + pharmacy_orphans
    used_ids: set[int] = set()
    results: list[PaymentResult] = []

    for payment in payments:
        candidates = [
            item
            for item in all_items
            if id(item) not in used_ids
            and item.plan_paid_cents > 0
            and item.plan_paid_cents <= payment.cents
            and (item.latest_proc_date is None or item.latest_proc_date <= payment.date_dt)
        ]

        result = dp_subset_sum(candidates, payment.cents)

        if result is not None:
            for item in result:
                used_ids.add(id(item))

            matched_items = [
                MatchedItem(
                    claim_nums=item.claim_nums,
                    provider=item.provider,
                    plan_paid_total=item.plan_paid_total,
                    is_pharmacy_orphan=(item.statement_date == ""),
                )
                for item in result
            ]

            results.append(
                PaymentResult(
                    payment=payment,
                    result=Matched(items=matched_items, total_claims=sum(len(mi.claim_nums) for mi in matched_items)),
                )
            )
        else:
            results.append(PaymentResult(payment=payment, result=NotMatched(candidate_count=len(candidates))))

    return results
