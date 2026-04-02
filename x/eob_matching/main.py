"""Match Anthem bank payments to EOBs and claims.

Outputs two CSVs:
- payment_claims_detail.csv: one row per claim
- payment_summary.csv: one row per bank payment
"""

import csv
import sys
from pathlib import Path

from x.eob_matching.loaders import (
    deduplicate_eobs,
    enrich_eobs,
    find_pharmacy_orphans,
    load_bank_payments,
    load_claims,
    load_eob_listing,
)
from x.eob_matching.matcher import match_payments
from x.eob_matching.models import DetailRow, Matched, NotMatched, SummaryRow

DOWNLOADS = Path.home() / "downloads"
EOB_OUTPUT = Path.home() / "code" / "ducktape" / "x" / "eob_matching" / "output"

CLAIMS_CSV = DOWNLOADS / "anthem-claims-2024-04-01-through-2026-04-01.csv"
EOB_LISTING = EOB_OUTPUT / "eob_listing.json"
BANK_STMT = DOWNLOADS / "Bank of America statements 2024-10-01 through 2026-04-01.txt"

OUTPUT_DETAIL = EOB_OUTPUT / "payment_claims_detail.csv"
OUTPUT_SUMMARY = EOB_OUTPUT / "payment_summary.csv"


def main() -> None:
    print("Loading data...", file=sys.stderr)
    claims = load_claims(CLAIMS_CSV)
    eobs_raw = load_eob_listing(EOB_LISTING)
    payments = load_bank_payments(BANK_STMT)

    eobs = deduplicate_eobs(eobs_raw)
    eobs = enrich_eobs(eobs, claims)

    eob_claim_nums = {cn for eob in eobs for cn in eob.claim_nums}
    pharmacy_orphans = find_pharmacy_orphans(claims, eob_claim_nums)

    print(f"Claims: {len(claims)}", file=sys.stderr)
    print(f"EOBs (deduplicated): {len(eobs)}", file=sys.stderr)
    print(f"Pharmacy orphans: {len(pharmacy_orphans)}", file=sys.stderr)
    print(f"Bank payments: {len(payments)}", file=sys.stderr)
    print(file=sys.stderr)

    results = match_payments(payments, eobs, pharmacy_orphans)

    # Build output rows
    detail_rows: list[DetailRow] = []
    summary_rows: list[SummaryRow] = []

    for pr in results:
        p = pr.payment
        match pr.result:
            case Matched(items=items, total_claims=total_claims):
                all_providers: set[str] = set()
                all_claim_nums: list[str] = []

                for item in items:
                    all_providers.add(item.provider)
                    for cn in item.claim_nums:
                        claim = claims.get(cn)
                        if claim:
                            all_providers.add(claim.provider)
                        detail_rows.append(
                            DetailRow(
                                payment_date=p.date,
                                payment_amount=p.amount,
                                payment_id=p.payment_id,
                                claim_num=cn,
                                provider=claim.provider if claim else item.provider,
                                service_date=claim.service_date if claim else "",
                                plan_paid=claim.plan_paid if claim else None,
                                your_cost=claim.your_cost if claim else None,
                            )
                        )
                        all_claim_nums.append(cn)

                summary_rows.append(
                    SummaryRow(
                        payment_date=p.date,
                        payment_amount=p.amount,
                        payment_id=p.payment_id,
                        providers=sorted(all_providers),
                        claim_count=len(all_claim_nums),
                        claim_nums=all_claim_nums,
                        matched=True,
                    )
                )

                print(
                    f"  {p.date}  ${p.amount:>12,.2f}  {p.payment_id}  "
                    f"MATCHED ({total_claims} claims)  "
                    f"{'; '.join(sorted(all_providers))}",
                    file=sys.stderr,
                )

            case NotMatched(candidate_count=n):
                summary_rows.append(
                    SummaryRow(
                        payment_date=p.date,
                        payment_amount=p.amount,
                        payment_id=p.payment_id,
                        providers=[],
                        claim_count=0,
                        claim_nums=[],
                        matched=False,
                    )
                )
                print(f"  {p.date}  ${p.amount:>12,.2f}  {p.payment_id}  UNMATCHED ({n} candidates)", file=sys.stderr)

    # Write CSVs
    _write_detail_csv(OUTPUT_DETAIL, detail_rows)
    _write_summary_csv(OUTPUT_SUMMARY, summary_rows)

    # Summary stats
    matched_results = [r for r in results if isinstance(r.result, Matched)]
    unmatched_results = [r for r in results if isinstance(r.result, NotMatched)]
    print(file=sys.stderr)
    print(f"Wrote {len(detail_rows)} detail rows to {OUTPUT_DETAIL}", file=sys.stderr)
    print(f"Wrote {len(summary_rows)} summary rows to {OUTPUT_SUMMARY}", file=sys.stderr)
    print(f"Matched: {len(matched_results)} (${sum(r.payment.amount for r in matched_results):,.2f})", file=sys.stderr)
    print(
        f"Unmatched: {len(unmatched_results)} (${sum(r.payment.amount for r in unmatched_results):,.2f})",
        file=sys.stderr,
    )


def _format_dollar(v: float | None) -> str:
    if v is None:
        return ""
    return f"${v:,.2f}"


def _write_detail_csv(path: Path, rows: list[DetailRow]) -> None:
    fieldnames = [
        "payment_date",
        "payment_amount",
        "payment_id",
        "claim_num",
        "provider",
        "service_date",
        "plan_paid",
        "your_cost",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "payment_date": row.payment_date,
                    "payment_amount": _format_dollar(row.payment_amount),
                    "payment_id": row.payment_id,
                    "claim_num": row.claim_num,
                    "provider": row.provider,
                    "service_date": row.service_date,
                    "plan_paid": _format_dollar(row.plan_paid),
                    "your_cost": _format_dollar(row.your_cost),
                }
            )


def _write_summary_csv(path: Path, rows: list[SummaryRow]) -> None:
    fieldnames = ["payment_date", "payment_amount", "payment_id", "matched", "providers", "claim_count", "claim_nums"]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "payment_date": row.payment_date,
                    "payment_amount": _format_dollar(row.payment_amount),
                    "payment_id": row.payment_id,
                    "matched": row.matched,
                    "providers": "; ".join(row.providers),
                    "claim_count": row.claim_count,
                    "claim_nums": "; ".join(row.claim_nums[:10]) + ("..." if len(row.claim_nums) > 10 else ""),
                }
            )


if __name__ == "__main__":
    main()
