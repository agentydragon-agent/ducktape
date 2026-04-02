"""Match Anthem bank payments to EOBs and claims.

Outputs JSON: list of PaymentResult (the domain model directly).
"""

import json
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
from x.eob_matching.models import Matched, NotMatched

DOWNLOADS = Path.home() / "downloads"
EOB_OUTPUT = Path.home() / "code" / "ducktape" / "x" / "eob_matching" / "output"

CLAIMS_CSV = DOWNLOADS / "anthem-claims-2024-04-01-through-2026-04-01.csv"
EOB_LISTING = EOB_OUTPUT / "eob_listing.json"
BANK_STMT = DOWNLOADS / "Bank of America statements 2024-10-01 through 2026-04-01.txt"

OUTPUT_PATH = EOB_OUTPUT / "payment_results.json"


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

    # Write JSON
    EOB_OUTPUT.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps([r.model_dump(mode="json") for r in results], indent=2))

    # Summary stats
    matched_results = [r for r in results if isinstance(r.result, Matched)]
    unmatched_results = [r for r in results if isinstance(r.result, NotMatched)]
    print(file=sys.stderr)
    print(f"Wrote {len(results)} results to {OUTPUT_PATH}", file=sys.stderr)
    print(f"Matched: {len(matched_results)} (${sum(r.payment.amount for r in matched_results):,.2f})", file=sys.stderr)
    print(
        f"Unmatched: {len(unmatched_results)} (${sum(r.payment.amount for r in unmatched_results):,.2f})",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
