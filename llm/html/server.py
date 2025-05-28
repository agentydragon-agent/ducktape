#!/usr/bin/env python3
"""FastAPI server for LLM instructions with token generation."""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import markdown
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from jinja2 import Environment, FileSystemLoader

from token_scheme import TokenScheme

# Configure logging to output to stdout
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Global configuration
TOKEN_SECRET = os.environ.get("TOKEN_SECRET", "hunter2").encode()

# FastAPI setup
app = FastAPI(title="LLM Instructions Server")

# Jinja2 setup
env = Environment(loader=FileSystemLoader("."), trim_blocks=True, lstrip_blocks=True)


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main page with rendered markdown."""
    try:
        text = Path("index.md").read_text()
        ts = TokenScheme(TOKEN_SECRET, text)

        # Use San Francisco timezone (America/Los_Angeles)
        sf_time = datetime.now(ZoneInfo("America/Los_Angeles"))
        prefix, bits = ts.make_token(sf_time)

        # Render template
        tpl = env.get_template("index.md")
        text = tpl.render(prefix=prefix, bits=bits)

        # Convert to HTML
        content = markdown.markdown(text, extensions=["tables", "fenced_code"])

        # Wrap in HTML structure
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>LLM Instructions</title>
    <link rel="stylesheet" href="/style.css">
</head>
<body>
{content}
</body>
</html>"""

        return HTMLResponse(
            content=html,
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'",
            },
        )
    except FileNotFoundError:
        logger.error("index.md not found")
        raise HTTPException(status_code=404, detail="Document not found")
    except Exception as e:
        logger.error(f"Error rendering page: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/style.css")
async def style_css():
    """Serve the CSS file."""
    file_path = Path(__file__).parent / "style.css"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="style.css not found")

    return FileResponse(
        file_path,
        media_type="text/css",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.post("/verify")
async def verify_token(token: str):
    """Verify a token against the current document."""
    doc = Path("index.html").read_text()
    ts = TokenScheme(TOKEN_SECRET, doc)

    try:
        ts.verify_token(token)
        return {
            "status": "success",
            "message": "Token verification succeeded – all checks passed ✅",
        }
    except TokenScheme.VerificationError as exc:
        issues_str = " | ".join(f"✗ {issue}" for issue in exc.issues)
        logger.error(f"Token verification FAILED: {issues_str}")
        return {"status": "failed", "errors": exc.issues}


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "9000"))

    logger.info(f"Starting FastAPI server on http://{host}:{port}")
    uvicorn.run(
        app, host=host, port=port, log_config=None
    )  # None to use our logging config
