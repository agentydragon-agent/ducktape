from __future__ import annotations

from adgn.props.cli_app.main import app


def main(argv: list[str] | None = None):
    """Legacy entrypoint delegating to the Typer app.

    This preserves the adgn-properties console script while using the new async-native Typer CLI.
    """
    if argv is None:
        app()
    else:
        app(args=argv)


if __name__ == "__main__":
    app()
