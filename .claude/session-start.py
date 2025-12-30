#!/usr/bin/env python3
"""Session start hook wrapper - adds package to path and runs the hook."""

from pathlib import Path
import sys

# Add claude_web_hooks package to path (runs before package installation)
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root / "claude_web_hooks" / "src"))

from claude_web_hooks.session_start import main

if __name__ == "__main__":
    sys.exit(main())
