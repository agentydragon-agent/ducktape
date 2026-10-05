"""Executable entry point for the pytest-main aspect action."""

import sys

from devinfra.lint.pytest_main_check import main


if __name__ == "__main__":
    sys.exit(main())
