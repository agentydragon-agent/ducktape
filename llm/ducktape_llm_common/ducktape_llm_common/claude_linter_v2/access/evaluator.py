"""Predicate evaluation engine for access control."""

import logging
from typing import Any

from .context import PredicateContext
from .predicates import BUILTIN_PREDICATES, create_tool_predicate

logger = logging.getLogger(__name__)


class PredicateEvaluator:
    """Evaluates Python predicate expressions safely."""

    def __init__(self) -> None:
        """Initialize the evaluator with built-in predicates."""
        self.globals: dict[str, Any] = {
            # Built-in predicates
            **BUILTIN_PREDICATES,
            # Tool predicates
            "Edit": lambda pattern=None: create_tool_predicate("Edit", pattern),
            "Write": lambda pattern=None: create_tool_predicate("Write", pattern),
            "MultiEdit": lambda pattern=None: create_tool_predicate("MultiEdit", pattern),
            "Read": lambda pattern=None: create_tool_predicate("Read", pattern),
            "Bash": lambda pattern=None: create_tool_predicate("Bash", pattern),
            # Constants
            "True": True,
            "False": False,
            "None": None,
        }

    def evaluate(self, predicate: str, context: PredicateContext) -> bool:
        """
        Evaluate a predicate expression or function in the given context.

        Supports both:
        1. Simple expressions: "ctx.tool == 'Bash' and safe_git_commands(ctx)"
        2. Multiline functions with arbitrary Python code

        Args:
            predicate: Python expression or multiline function to evaluate
            context: Context for evaluation

        Returns:
            Boolean result of evaluation

        Raises:
            ValueError: If predicate is invalid
        """
        # Check if this is a multiline predicate (function definition)
        if "\n" in predicate or predicate.strip().startswith("def "):
            return self._evaluate_multiline(predicate, context)

        try:
            # Create evaluation namespace
            namespace = {
                **self.globals,
                "ctx": context,
            }

            # Evaluate with standard builtins (allows import, etc)
            result = eval(predicate, namespace)

            # Handle callable results (from tool predicates)
            if callable(result):
                result = result(context)

            return bool(result)

        except Exception as e:
            logger.error(f"Failed to evaluate predicate '{predicate}': {e}")
            raise ValueError(f"Invalid predicate: {e}") from e

    def _evaluate_multiline(self, predicate: str, context: PredicateContext) -> bool:
        """
        Evaluate a multiline predicate with function definitions.

        The predicate can:
        1. Define functions and call them
        2. Import modules
        3. Use complex logic
        4. Must either:
           - Set a 'result' variable
           - Have a final expression that evaluates to bool
        """
        try:
            # Create evaluation namespace with useful imports available
            namespace = {
                **self.globals,
                "ctx": context,
                # Common imports for predicates
                "re": __import__("re"),
                "os": __import__("os"),
                "pathlib": __import__("pathlib"),
                "shlex": __import__("shlex"),
                "datetime": __import__("datetime"),
                "json": __import__("json"),
                # Allow importing more if needed
                "__import__": __import__,
            }

            # Execute the multiline code
            exec(predicate.strip(), namespace)

            # Check if 'result' was set
            if "result" in namespace:
                return bool(namespace["result"])

            # Otherwise, try to evaluate the last line as an expression
            lines = predicate.strip().split("\n")
            last_line = lines[-1].strip() if lines else ""

            # Skip if last line is a statement (not an expression)
            if last_line and not any(
                last_line.startswith(kw)
                for kw in ["def", "class", "if", "for", "while", "with", "try", "import", "from"]
            ):
                try:
                    result = eval(last_line, namespace)
                    if callable(result):
                        result = result(context)
                    return bool(result)
                except Exception:
                    pass

            # If we get here, no result was found
            raise ValueError(
                "Multiline predicate must either set 'result' variable or end with an expression. "
                "Example:\n"
                "def check(ctx):\n"
                "    return ctx.tool == 'Bash'\n"
                "result = check(ctx)\n"
                "# OR just end with: check(ctx)"
            )

        except Exception as e:
            logger.error(f"Failed to evaluate multiline predicate: {e}")
            # Include first line of predicate for context
            first_line = predicate.strip().split("\n")[0][:50]
            raise ValueError(f"Invalid multiline predicate starting with '{first_line}...': {e}") from e

    def validate_predicate(self, predicate: str) -> str | None:
        """
        Validate a predicate without evaluating it.

        Args:
            predicate: Predicate expression to validate

        Returns:
            Error message if invalid, None if valid
        """
        try:
            # Just try to compile it
            compile(predicate, "<predicate>", "eval")
            return None
        except Exception as e:
            return str(e)
