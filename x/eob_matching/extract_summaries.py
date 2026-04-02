"""Extract summary info from EOB PDFs using Qwen2.5-VL via ollama.

Renders page 1 of each unique PDF, sends to vision model with structured
JSON schema enforcement. Caches results by PDF content hash.

Requires:
- ollama running with qwen2.5vl:7b loaded (with CUDA)
- poppler-utils (pdftoppm) on PATH
"""

import base64
import json
import sys
import tempfile
from pathlib import Path

import httpx
from pydantic import BaseModel

from x.eob_matching.models import EOBSummaryExtraction
from x.eob_matching.pdf_utils import file_hash, render_pdf_page

EOB_DIR = Path.home() / "downloads" / "anthem-eobs"
CACHE_DIR = Path.home() / "downloads" / "eob-cache"
OUTPUT_PATH = Path.home() / "code" / "ducktape" / "x" / "eob_matching" / "output" / "eob_summaries.json"

OLLAMA_URL = "http://localhost:11434"
MODEL = "qwen2.5vl:7b"

SUMMARY_PROMPT = "Extract the financial summary from this insurance EOB summary page."

CLAIMS_PROMPT = (
    "Extract ALL claims and their service lines from this insurance EOB claims detail page. "
    "Each claim block starts with a claim number and received date."
)


def query_ollama[T: BaseModel](image_path: Path, prompt: str, response_model: type[T]) -> T:
    """Send image to ollama vision model with structured JSON output.

    The JSON schema is both:
    1. Passed to ollama's `format` param for grammar-based structural enforcement
    2. Included in the prompt text so the model sees field names, descriptions, and constraints
    """
    b64 = base64.b64encode(image_path.read_bytes()).decode()
    schema = response_model.model_json_schema()

    full_prompt = f"{prompt}\n\nOutput JSON matching this schema:\n{json.dumps(schema, indent=2)}"

    resp = httpx.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": MODEL,
            "prompt": full_prompt,
            "images": [b64],
            "format": schema,
            "stream": False,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return response_model.model_validate_json(resp.json()["response"])


def process_pdf(pdf_path: Path) -> tuple[str, EOBSummaryExtraction | None, str]:
    """Process one PDF. Returns (pdf_name, extraction, status)."""
    pdf_name = pdf_path.name
    h = file_hash(pdf_path)
    cache_path = CACHE_DIR / f"{h}.json"

    if cache_path.exists():
        data = json.loads(cache_path.read_text())
        return pdf_name, EOBSummaryExtraction.model_validate(data), "cached"

    with tempfile.TemporaryDirectory() as tmpdir:
        img = render_pdf_page(pdf_path, page=1, tmpdir=Path(tmpdir))
        try:
            extraction = query_ollama(img, SUMMARY_PROMPT, EOBSummaryExtraction)
        except Exception as e:
            return pdf_name, None, f"error: {e}"

    cache_path.write_text(extraction.model_dump_json(indent=2))
    return pdf_name, extraction, "extracted"


def main() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(EOB_DIR.glob("*.pdf"))
    print(f"Found {len(pdfs)} PDFs", file=sys.stderr)

    # Deduplicate by content hash
    seen: set[str] = set()
    unique: list[Path] = []
    for p in pdfs:
        h = file_hash(p)
        if h not in seen:
            seen.add(h)
            unique.append(p)
    print(f"Unique: {len(unique)}", file=sys.stderr)

    results: list[dict] = []
    cached = extracted = errors = 0

    for i, pdf_path in enumerate(unique):
        name, extraction, status = process_pdf(pdf_path)
        if status == "cached":
            cached += 1
        elif extraction is not None:
            extracted += 1
        else:
            errors += 1

        if extraction is not None:
            result_dict = extraction.model_dump()
            result_dict["pdf"] = name
            results.append(result_dict)
            print(
                f"[{i + 1}/{len(unique)}] {name[:35]:>35}  "
                f"paid={extraction.anthem_blue_cross_paid:>12,.2f}  "
                f"you_pay={extraction.what_you_pay:>10,.2f}  [{status}]",
                file=sys.stderr,
            )
        else:
            print(f"[{i + 1}/{len(unique)}] {name[:35]:>35}  FAILED: {status}", file=sys.stderr)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(results, indent=2))
    print(f"\nDone: {cached} cached, {extracted} extracted, {errors} errors", file=sys.stderr)
    print(f"Wrote {len(results)} to {OUTPUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
