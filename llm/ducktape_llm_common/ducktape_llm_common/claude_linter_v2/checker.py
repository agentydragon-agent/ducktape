"""Direct file checking for cl2 check command."""

import logging
from pathlib import Path

from .config import AutofixCategory, ConfigLoader, Violation
from .linters.python_ast import PythonASTAnalyzer
from .linters.python_formatter import PythonFormatter
from .linters.python_ruff import PythonRuffLinter

logger = logging.getLogger(__name__)


class FileChecker:
    """Checks files for violations and optionally fixes them."""

    def __init__(
        self,
        fix: bool = False,
        categories: list[AutofixCategory] | None = None,
        verbose: bool = False,
    ) -> None:
        """
        Initialize the file checker.

        Args:
            fix: Whether to fix issues
            categories: Autofix categories to apply (empty = all)
            verbose: Enable verbose output
        """
        self.fix = fix
        self.categories = categories or []
        self.verbose = verbose

        # Load config
        self.config_loader = ConfigLoader()
        self.config = self.config_loader.config

    def check_file(self, file_path: Path) -> list[Violation]:
        """
        Check a single file for violations.

        Args:
            file_path: Path to the file to check

        Returns:
            List of violations found
        """
        violations: list[Violation] = []

        # Only check Python files for now
        if not str(file_path).endswith(".py"):
            return violations

        try:
            content = file_path.read_text()
        except Exception as e:
            logger.error(f"Failed to read {file_path}: {e}")
            return violations

        # Run AST checks
        analyzer = PythonASTAnalyzer(
            bare_except=self.config.python_bare_except.enabled,
            getattr_setattr=(
                self.config.python_hasattr.enabled
                or self.config.python_getattr.enabled
                or self.config.python_setattr.enabled
            ),
            barrel_init=str(file_path).endswith("__init__.py") and self.config.python_barrel_init.enabled,
        )
        ast_violations = analyzer.analyze_code(content, str(file_path))
        violations.extend(ast_violations)

        # Run ruff checks
        ruff_linter = PythonRuffLinter(force_select=self.config.get_ruff_force_select())
        ruff_violations = ruff_linter.check_code(content, str(file_path), critical_only=False)
        violations.extend(ruff_violations)

        # Apply fixes if requested
        if self.fix and self.categories:
            formatter = PythonFormatter(self.config.python_tools)
            formatted_content, changes = formatter.format_code(content, str(file_path), self.categories)

            if changes and formatted_content != content:
                try:
                    file_path.write_text(formatted_content)
                    if self.verbose:
                        logger.info(f"Applied fixes to {file_path}: {', '.join(changes)}")

                    # Re-check after fixing to get updated violations
                    violations = self.check_file(file_path)
                except Exception as e:
                    logger.error(f"Failed to write fixes to {file_path}: {e}")

        return violations
