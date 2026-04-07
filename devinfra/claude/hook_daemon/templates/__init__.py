"""Mako templates for hook daemon output formatting."""

from pathlib import Path

from mako.template import Template

_DIR = Path(__file__).resolve().parent

post_tool_use = Template((_DIR / "post_tool_use.mako").read_text())
session_context = Template(
    (_DIR / "session_context.mako").read_text(),
    imports=[
        "import logging",
        "from devinfra.claude.hook_daemon.session_start.precommit import PrecommitInstallingHooks, PrecommitNotInstalled",
    ],
)
