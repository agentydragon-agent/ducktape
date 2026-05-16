import sys
from datetime import UTC, datetime
from pathlib import Path

import typer

from aiquota.cache import QuotaCache, _fetch_providers
from aiquota.config import load as load_config
from aiquota.models import AllQuotas
from aiquota.render import json_output, tmux as render_tmux

app = typer.Typer(add_completion=False)


@app.command()
def tmux(config: Path | None = typer.Option(None, "--config", "-c", help="Config file path")) -> None:
    """Render quota status as a tmux status line segment."""
    cfg = load_config(config)
    cache = QuotaCache()
    quotas = cache.fetch_all(cfg)
    sys.stdout.write(render_tmux.render(quotas.providers))


@app.command(name="json")
def json_cmd(config: Path | None = typer.Option(None, "--config", "-c", help="Config file path")) -> None:
    """Render quota status as JSON (for GNOME extension consumption)."""
    cfg = load_config(config)
    cache = QuotaCache()
    quotas = cache.fetch_all(cfg)
    json_output.render(quotas)


@app.command()
def fetch(config: Path | None = typer.Option(None, "--config", "-c", help="Config file path")) -> None:
    """Fetch and display quota status in human-readable form."""
    cfg = load_config(config)
    quotas = AllQuotas(providers=_fetch_providers(cfg), fetched_at=datetime.now(UTC))
    for pq in quotas.providers:
        if pq.error:
            print(f"{pq.provider}: error — {pq.error}")
            continue
        parts = []
        if pq.short_window:
            parts.append(f"5h:{round(pq.short_window.used_percent)}%")
        if pq.long_window:
            parts.append(f"7d:{round(pq.long_window.used_percent)}%")
        print(f"{pq.provider}: {' '.join(parts) if parts else 'no data'}")
