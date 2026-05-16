import sys
from datetime import UTC, datetime
from pathlib import Path

import typer

from aiquota.cache import get_or_fetch
from aiquota.config import ConfigFile, load as load_config
from aiquota.models import AllQuotas, ProviderQuota

app = typer.Typer(add_completion=False)


def _fetch_all(config: ConfigFile) -> AllQuotas:
    from aiquota.providers import claude, codex, zai

    providers: list[ProviderQuota] = []
    for name, fetch_fn in [("claude", claude.fetch), ("codex", codex.fetch)]:
        settings = config.providers.get(name)
        if settings is not None and not settings.enabled:
            continue
        providers.append(fetch_fn())

    zai_settings = config.providers.get("zai")
    if zai_settings is None or zai_settings.enabled:
        providers.append(zai.fetch(api_key_path=zai_settings.api_key_path if zai_settings else None))

    return AllQuotas(providers=providers, fetched_at=datetime.now(UTC))


@app.command()
def tmux(config: Path | None = typer.Option(None, "--config", "-c", help="Config file path")) -> None:
    """Render quota status as a tmux status line segment."""
    from aiquota.render import tmux as render_tmux

    cfg = load_config(config)
    quotas = get_or_fetch(lambda: _fetch_all(cfg))
    sys.stdout.write(render_tmux.render(quotas.providers))


@app.command(name="json")
def json_cmd(config: Path | None = typer.Option(None, "--config", "-c", help="Config file path")) -> None:
    """Render quota status as JSON (for GNOME extension consumption)."""
    from aiquota.render import json_output

    cfg = load_config(config)
    quotas = get_or_fetch(lambda: _fetch_all(cfg))
    json_output.render(quotas)


@app.command()
def fetch(config: Path | None = typer.Option(None, "--config", "-c", help="Config file path")) -> None:
    """Fetch and display quota status in human-readable form."""
    cfg = load_config(config)
    quotas = _fetch_all(cfg)
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
