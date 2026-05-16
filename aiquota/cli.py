import sys
from pathlib import Path

import typer

from aiquota.cache import QuotaService
from aiquota.config import DEFAULT_CONFIG_PATH, load as load_config
from aiquota.render import human as render_human, json_output, tmux as render_tmux

_CONFIG_OPTION = typer.Option(DEFAULT_CONFIG_PATH, "--config", "-c", help="Config file path")

app = typer.Typer(add_completion=False, invoke_without_command=True)


@app.callback()
def main(ctx: typer.Context, config: Path = _CONFIG_OPTION) -> None:
    """AI subscription quota tracker."""
    ctx.ensure_object(dict)
    ctx.obj["service"] = QuotaService(config=load_config(config))
    if ctx.invoked_subcommand is None:
        ctx.invoke(fetch, ctx=ctx)


def _service(ctx: typer.Context) -> QuotaService:
    return ctx.obj["service"]  # type: ignore[no-any-return]


@app.command()
def fetch(ctx: typer.Context) -> None:
    """Fetch and display quota status in human-readable form (same info as the GNOME popup)."""
    quotas = _service(ctx).fetch_fresh()
    print(render_human.render(quotas))


@app.command()
def tmux(ctx: typer.Context) -> None:
    """Render quota status as a tmux status line segment."""
    svc = _service(ctx)
    quotas = svc.fetch_all()
    sys.stdout.write(render_tmux.render(quotas.providers))


@app.command(name="json")
def json_cmd(ctx: typer.Context) -> None:
    """Render quota status as JSON (for GNOME extension consumption)."""
    svc = _service(ctx)
    quotas = svc.fetch_all()
    json_output.render(quotas)


if __name__ == "__main__":
    app()
