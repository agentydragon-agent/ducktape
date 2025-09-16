"""Simple CLI entrypoint to run rspcache (SQLite-backed Responses proxy).

Provides `rspcache` console script that boots the FastAPI app with uvicorn.
"""

from __future__ import annotations

import os
from pathlib import Path

import typer
import uvicorn

app = typer.Typer(help="adgn-llm utilities CLI")


@app.command()
def main(
    host: str = "127.0.0.1",
    port: int = 8000,
    db_path: Path | None = None,
    reload: bool = False,
):
    """Run the responses proxy (rspcache) locally.

    Example:
      rspcache --host 127.0.0.1 --port 8000 --db-path /tmp/rsp.db
    """
    # Allow env override
    if db_path:
        os.environ["ADGN_RESP_DB"] = str(db_path)

    uvicorn.run("adgn.rspcache:APP", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
