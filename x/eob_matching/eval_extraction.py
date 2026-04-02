"""Mini-eval for EOB PDF extraction quality.

Extracts specified PDFs multiple times, checks consistency and accuracy
against manually verified ground truth (both summary and claims detail pages).

Consistency is measured as average pairwise agreement across N runs.
Accuracy is measured against human-verified ground truth values.
Extraction failures (validation errors, timeouts) are counted, not swallowed.

Requires: ollama running with qwen2.5vl:7b, pdftoppm on PATH.
"""

import sys
import tempfile
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from x.eob_matching.extract_summaries import CLAIMS_PROMPT, SUMMARY_PROMPT, query_ollama
from x.eob_matching.models import (
    EOBClaimsPageExtraction,
    EOBSummaryExtraction,
    ExtractedDate,
)
from x.eob_matching.pdf_utils import render_pdf_page

EOB_DIR = Path.home() / "downloads" / "anthem-eobs"
EXTRACTIONS_PER_PDF = 3
TOLERANCE_DOLLARS = 0.02


# --- Ground truth: summaries ---


class SummaryGroundTruth(BaseModel):
    pdf_stem: str
    statement_date: date
    doctor_facility_charges: float = Field(ge=0)
    your_discounts: float = Field(le=0)
    allowed_amount: float = Field(ge=0)
    anthem_blue_cross_paid: float = Field(le=0)
    what_you_pay: float = Field(ge=0)


SUMMARY_GROUND_TRUTHS = [
    SummaryGroundTruth(
        pdf_stem="4de141d0",
        statement_date=date(2025, 12, 19),
        doctor_facility_charges=8090.88,
        your_discounts=0.0,
        allowed_amount=4777.89,
        anthem_blue_cross_paid=-4757.89,
        what_you_pay=3332.99,
    ),
    SummaryGroundTruth(
        pdf_stem="2259ae70",
        statement_date=date(2025, 4, 27),
        doctor_facility_charges=4401.54,
        your_discounts=-2373.67,
        allowed_amount=2027.87,
        anthem_blue_cross_paid=-2007.87,
        what_you_pay=20.00,
    ),
    SummaryGroundTruth(
        pdf_stem="e9ea0273",
        statement_date=date(2025, 8, 14),
        doctor_facility_charges=1200.00,
        your_discounts=0.0,
        allowed_amount=1200.00,
        anthem_blue_cross_paid=-840.00,
        what_you_pay=360.00,
    ),
    SummaryGroundTruth(
        pdf_stem="274ddb79",
        statement_date=date(2026, 3, 19),
        doctor_facility_charges=71580.50,
        your_discounts=0.0,
        allowed_amount=71580.50,
        anthem_blue_cross_paid=-71580.50,
        what_you_pay=0.00,
    ),
]


# --- Ground truth: claims detail pages ---


class ClaimLineGroundTruth(BaseModel):
    service_date: date
    service_description: str
    doctor_charges: float
    anthem_blue_cross_paid: float
    your_total_cost: float
    reason_code: str = ""


class ClaimGroundTruth(BaseModel):
    claim_number: str
    received_date: date
    doctor_name: str
    in_network: bool
    you_pay_total: float
    lines: list[ClaimLineGroundTruth]


class DetailPageGroundTruth(BaseModel):
    pdf_stem: str
    page: int
    claims: list[ClaimGroundTruth]


DETAIL_GROUND_TRUTHS = [
    DetailPageGroundTruth(
        pdf_stem="e9ea0273",
        page=3,
        claims=[
            ClaimGroundTruth(
                claim_number="2025221RM1565",
                received_date=date(2025, 8, 9),
                doctor_name="LESNE",
                in_network=False,
                you_pay_total=360.00,
                lines=[
                    ClaimLineGroundTruth(service_date=date(2025, 6, d), service_description="Therapeutic Services", doctor_charges=200.00, anthem_blue_cross_paid=140.00, your_total_cost=60.00)
                    for d in [6, 9, 13, 20, 23, 27]
                ],
            ),
        ],
    ),
    DetailPageGroundTruth(
        pdf_stem="2259ae70",
        page=3,
        claims=[
            ClaimGroundTruth(
                claim_number="2025114EQ6363",
                received_date=date(2025, 4, 24),
                doctor_name="MCINNES, LYNNE A",
                in_network=True,
                you_pay_total=20.00,
                lines=[
                    ClaimLineGroundTruth(service_date=date(2025, 3, 27), service_description="Medical Service", doctor_charges=4401.54, anthem_blue_cross_paid=2007.87, your_total_cost=20.00, reason_code="066"),
                ],
            ),
        ],
    ),
    DetailPageGroundTruth(
        pdf_stem="274ddb79",
        page=3,
        claims=[
            ClaimGroundTruth(
                claim_number="2025217BP9584",
                received_date=date(2025, 8, 5),
                doctor_name="NUMA PSYCHIATRY & PSYCHED",
                in_network=False,
                you_pay_total=0.00,
                lines=[
                    ClaimLineGroundTruth(service_date=date(2025, 7, 31), service_description="Drug Non-Oral", doctor_charges=14316.10, anthem_blue_cross_paid=14316.10, your_total_cost=0.00),
                ],
            ),
            ClaimGroundTruth(
                claim_number="2025224BA6430",
                received_date=date(2025, 8, 12),
                doctor_name="NUMA PSYCHIATRY & PSYCHED",
                in_network=False,
                you_pay_total=0.00,
                lines=[
                    ClaimLineGroundTruth(service_date=date(2025, 8, 7), service_description="Drug Non-Oral", doctor_charges=14316.10, anthem_blue_cross_paid=14316.10, your_total_cost=0.00),
                ],
            ),
        ],
    ),
]


# --- Eval logic ---


class EvalResults:
    def __init__(self) -> None:
        self.total = 0
        self.passed = 0
        self.sign_errors = 0
        self.extraction_failures = 0
        self.consistency_mismatches = 0
        self.consistency_checks = 0

    def check_value(self, name: str, expected: float, actual: float) -> None:
        self.total += 1
        if abs(expected - actual) <= TOLERANCE_DOLLARS:
            self.passed += 1
            return
        if abs(expected - (-actual)) <= TOLERANCE_DOLLARS:
            self.sign_errors += 1
            print(f"    {name}: SIGN ERROR — expected {expected}, got {actual}", file=sys.stderr)
            return
        print(f"    {name}: WRONG — expected {expected}, got {actual}", file=sys.stderr)

    def check_date(self, name: str, expected: date, actual: ExtractedDate) -> None:
        self.total += 1
        if actual.to_date() == expected:
            self.passed += 1
            return
        print(f"    {name}: WRONG — expected {expected}, got {actual.to_date()}", file=sys.stderr)

    def check_str(self, name: str, expected: str, actual: str) -> None:
        self.total += 1
        if expected.lower() in actual.lower():
            self.passed += 1
            return
        print(f"    {name}: WRONG — expected '{expected}' in '{actual}'", file=sys.stderr)

    def check_bool(self, name: str, expected: bool, actual: bool) -> None:
        self.total += 1
        if expected == actual:
            self.passed += 1
            return
        print(f"    {name}: WRONG — expected {expected}, got {actual}", file=sys.stderr)

    def check_int(self, name: str, expected: int, actual: int) -> None:
        self.total += 1
        if expected == actual:
            self.passed += 1
            return
        print(f"    {name}: WRONG — expected {expected}, got {actual}", file=sys.stderr)

    def record_consistency(self, field_name: str, values: list[float]) -> None:
        """Record whether N extraction runs agree on a value."""
        self.consistency_checks += 1
        if max(values) - min(values) > TOLERANCE_DOLLARS:
            self.consistency_mismatches += 1
            print(f"    INCONSISTENT {field_name}: {values}", file=sys.stderr)


def find_pdf(stem: str) -> Path:
    matches = list(EOB_DIR.glob(f"{stem}*.pdf"))
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected 1 PDF matching '{stem}*', found {len(matches)}")
    return matches[0]


def extract_n_times[T: BaseModel](
    pdf_path: Path,
    page: int,
    prompt: str,
    response_model: type[T],
    n: int,
    results: EvalResults,
) -> list[T]:
    """Run extraction N times, logging results. Returns successful extractions."""
    extractions: list[T] = []
    for run in range(n):
        with tempfile.TemporaryDirectory() as tmpdir:
            img = render_pdf_page(pdf_path, page=page, tmpdir=Path(tmpdir))
            try:
                extraction = query_ollama(img, prompt, response_model)
                extractions.append(extraction)
                print(f"    Run {run + 1}: OK", file=sys.stderr)
            except ValidationError as e:
                results.extraction_failures += 1
                print(f"    Run {run + 1}: VALIDATION ERROR — {e.error_count()} errors", file=sys.stderr)
                for err in e.errors():
                    print(f"      {err['loc']}: {err['msg']} (input={err.get('input')})", file=sys.stderr)
            except Exception as e:
                results.extraction_failures += 1
                print(f"    Run {run + 1}: ERROR — {type(e).__name__}: {e}", file=sys.stderr)
    return extractions


def eval_summaries(results: EvalResults) -> None:
    print("\n" + "=" * 60, file=sys.stderr)
    print("SUMMARY EXTRACTION EVAL", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    for gt in SUMMARY_GROUND_TRUTHS:
        pdf_path = find_pdf(gt.pdf_stem)
        print(f"\n  PDF: {pdf_path.name}", file=sys.stderr)

        extractions = extract_n_times(pdf_path, page=1, prompt=SUMMARY_PROMPT, response_model=EOBSummaryExtraction, n=EXTRACTIONS_PER_PDF, results=results)

        if not extractions:
            print("    No successful extractions!", file=sys.stderr)
            continue

        # Consistency across runs
        for field_name in ["anthem_blue_cross_paid", "what_you_pay", "doctor_facility_charges"]:
            values = [getattr(e, field_name) for e in extractions]
            results.record_consistency(field_name, values)

        # Accuracy (first successful extraction)
        e = extractions[0]
        print("    Accuracy:", file=sys.stderr)
        results.check_date("statement_date", gt.statement_date, e.statement_date)
        results.check_value("doctor_facility_charges", gt.doctor_facility_charges, e.doctor_facility_charges)
        results.check_value("your_discounts", gt.your_discounts, e.your_discounts)
        results.check_value("allowed_amount", gt.allowed_amount, e.allowed_amount)
        results.check_value("anthem_blue_cross_paid", gt.anthem_blue_cross_paid, e.anthem_blue_cross_paid)
        results.check_value("what_you_pay", gt.what_you_pay, e.what_you_pay)


def eval_details(results: EvalResults) -> None:
    print("\n" + "=" * 60, file=sys.stderr)
    print("CLAIMS DETAIL EXTRACTION EVAL", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    for gt in DETAIL_GROUND_TRUTHS:
        pdf_path = find_pdf(gt.pdf_stem)
        print(f"\n  PDF: {pdf_path.name} page {gt.page}", file=sys.stderr)

        extractions = extract_n_times(pdf_path, page=gt.page, prompt=CLAIMS_PROMPT, response_model=EOBClaimsPageExtraction, n=EXTRACTIONS_PER_PDF, results=results)

        if not extractions:
            print("    No successful extractions!", file=sys.stderr)
            continue

        # Consistency: claim count across runs
        claim_counts = [len(e.claims) for e in extractions]
        results.record_consistency("claim_count", [float(c) for c in claim_counts])

        # Accuracy (first successful extraction)
        e = extractions[0]
        print("    Accuracy:", file=sys.stderr)
        results.check_int("claim_count", len(gt.claims), len(e.claims))

        for gt_claim, ext_claim in zip(gt.claims, e.claims, strict=False):
            results.check_str("claim_number", gt_claim.claim_number, ext_claim.claim_number)
            results.check_date("received_date", gt_claim.received_date, ext_claim.received_date)
            results.check_str("doctor_name", gt_claim.doctor_name, ext_claim.doctor_name)
            results.check_bool("in_network", gt_claim.in_network, ext_claim.in_network)
            results.check_value("you_pay_total", gt_claim.you_pay_total, ext_claim.you_pay_total)
            results.check_int("line_count", len(gt_claim.lines), len(ext_claim.lines))

            for gt_line, ext_line in zip(gt_claim.lines, ext_claim.lines, strict=False):
                results.check_date("service_date", gt_line.service_date, ext_line.service_date)
                results.check_value("doctor_charges", gt_line.doctor_charges, ext_line.doctor_charges)
                results.check_value("anthem_paid", gt_line.anthem_blue_cross_paid, ext_line.anthem_blue_cross_paid)
                results.check_value("your_total_cost", gt_line.your_total_cost, ext_line.your_total_cost)


def main() -> None:
    results = EvalResults()

    eval_summaries(results)
    eval_details(results)

    accuracy = results.passed / results.total if results.total else 0
    consistency = 1 - (results.consistency_mismatches / results.consistency_checks) if results.consistency_checks else 0

    print(f"\n{'=' * 60}", file=sys.stderr)
    print("RESULTS", file=sys.stderr)
    print(f"  Accuracy:      {results.passed}/{results.total} ({accuracy:.0%})", file=sys.stderr)
    print(f"  Sign errors:   {results.sign_errors}", file=sys.stderr)
    print(f"  Extraction failures: {results.extraction_failures}", file=sys.stderr)
    print(f"  Consistency:   {results.consistency_checks - results.consistency_mismatches}/{results.consistency_checks} ({consistency:.0%})", file=sys.stderr)

    if results.extraction_failures > 0:
        print(f"\nFAIL: {results.extraction_failures} extraction failures", file=sys.stderr)
        sys.exit(1)
    elif accuracy < 0.9:
        print(f"\nFAIL: accuracy {accuracy:.0%} < 90%", file=sys.stderr)
        sys.exit(1)
    else:
        print("\nPASS", file=sys.stderr)


if __name__ == "__main__":
    main()
