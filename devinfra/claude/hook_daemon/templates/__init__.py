"""Mako templates for hook daemon output formatting."""

from pathlib import Path

from mako.template import Template

_DIR = Path(__file__).resolve().parent

session_context = Template((_DIR / "session_context.mako").read_text(), imports=["import logging"])
