from __future__ import annotations

# Re-export CLI entry for backward compatibility:
# pyproject points `adgn-openai-probe` to `adgn.openai_utils.probe:main`.
from .main import main  # noqa: F401
