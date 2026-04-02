"""Extract summary info from EOB PDFs using Qwen2.5-VL via ollama.

Renders page 1 of each unique PDF, sends to vision model with structured
JSON schema enforcement. Caches results by PDF content hash.

Requires:
- ollama running with qwen2.5vl:7b loaded (with CUDA)
- poppler-utils (pdftoppm) on PATH
"""

import base64
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx
from more_itertools import one
from pydantic import BaseModel

from x.eob_matching.models import EOBSummaryExtraction

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


def file_hash(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def render_page1(pdf_path: Path, tmpdir: Path) -> Path:
    """Render page 1 of a PDF to PNG. Returns the single output path."""
    prefix = tmpdir / "page"
    subprocess.run(
        ["pdftoppm", "-png", "-r", "150", "-f", "1", "-l", "1", str(pdf_path), str(prefix)],
        check=True,
        capture_output=True,
    )
    return one(tmpdir.glob("page-*.png"))


def query_ollama[T: BaseModel](image_path: Path, prompt: str, response_model: type[T]) -> T:
    """Send image to ollama vision model with structured JSON output."""
    b64 = base64.b64encode(image_path.read_bytes()).decode()

    resp = httpx.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": MODEL,
            "prompt": prompt,
            "images": [b64],
            "format": response_model.model_json_schema(),
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
        img = render_page1(pdf_path, Path(tmpdir))
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
