# EOB Payment Matching

Match 32 Anthem bank deposits to their constituent medical/pharmacy claims and providers.

## Layout

```
x/eob_matching/
├── BUILD.bazel
├── STATUS.md
├── shell.nix              # nix-shell with poppler-utils, tesseract, python deps
├── __init__.py
├── models.py              # Pydantic models: Claim, EOB, BankPayment, extraction schemas
├── loaders.py             # Data loaders for CSV, JSON, bank statement
├── matcher.py             # DP subset-sum matching
├── main.py                # Main binary: match payments → output CSVs
├── parse_eob_listing.py   # Parse EOB Center HTML → eob_listing.json
├── extract_summaries.py   # Vision model extraction from PDF page 1
└── output/                # Generated data (gitignored)
    ├── eob_listing.json
    ├── eob_summaries.json
    ├── payment_claims_detail.csv
    └── payment_summary.csv
```

## Bazel targets

| Target                               | What                                                                                |
| ------------------------------------ | ----------------------------------------------------------------------------------- |
| `//x/eob_matching:parse_eob_listing` | Parse HTML → `output/eob_listing.json`                                              |
| `//x/eob_matching:extract_summaries` | Vision model PDF extraction → `output/eob_summaries.json` (needs ollama + pdftoppm) |
| `//x/eob_matching:eob_matching`      | Match payments → `output/payment_*.csv`                                             |

## Data sources

| Source           | Location                                                                                                |
| ---------------- | ------------------------------------------------------------------------------------------------------- |
| Claims CSV       | `~/downloads/anthem-claims-2024-04-01-through-2026-04-01.csv` — 218 claims (112 medical + 106 pharmacy) |
| Bank statement   | `~/downloads/Bank of America statements 2024-10-01 through 2026-04-01.txt` — 32 Anthem EFT deposits     |
| EOB listing HTML | `~/downloads/anthem-eobs/EOB Center Medical.html` — 84 medical EOBs                                     |
| EOB PDFs         | `~/downloads/anthem-eobs/*.pdf` — 83 unique (deduped from 98)                                           |
| Ollama models    | `~/downloads/ollama-models/` — qwen2.5vl:7b                                                             |
| OCR cache        | `~/downloads/eob-cache/` — cached per-PDF extraction results                                            |

## Current results

- **20 of 32 payments matched** (62.5%, $83k) by DP subset-sum on Plan Paid amounts
- **12 unmatched** ($285k) — mostly large Numa Psychiatry payments and recurring pharmacy batches
- Vision model extraction running on all 83 PDFs (ollama-cuda, ~2.5s/page on RTX 5090)

## Next steps

1. Use vision model summaries to improve matching (cross-validate amounts)
2. Fix remaining 12 unmatched payments (raise DP cap, multi-pass strategy)
3. Extract claims detail pages for full per-service-line data
