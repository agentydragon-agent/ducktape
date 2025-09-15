"""Simple CLI entrypoint to run rspcache (SQLite-backed Responses proxy).

Provides `rspcache` console script that boots the FastAPI app with uvicorn.
"""

from __future__ import annotations
import uvicorn
from typing import Optional
from pathlib import Path
import os
import typer


app = typer.Typer(help="adgn-llm utilities CLI")


@app.command()
def main(
    host: str = "127.0.0.1",
    port: int = 8000,
    db_path: Optional[Path] = None,
    reload: bool = False,
):
    """Run the responses proxy (rspcache) locally.

    Example:
      rspcache --host 127.0.0.1 --port 8000 --db-path /tmp/rsp.db
    """
    # Allow env override
    if db_path:
        os.environ["ADGN_RESP_DB"] = str(db_path)

    uvicorn.run("adgn_llm.openai_responses_proxy:APP", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
