"""Enhanced predicate evaluator that supports multiline function definitions."""

import logging

from .context import PredicateContext
from .evaluator import PredicateEvaluator

logger = logging.getLogger(__name__)


class EnhancedPredicateEvaluator(PredicateEvaluator):
    """Extended evaluator that supports multiline function definitions."""

    def evaluate(self, predicate: str, context: PredicateContext) -> bool:
        """
        Evaluate a predicate expression or function definition.

        Supports both:
        1. Simple expressions: "ctx.tool == 'Bash'"
        2. Multiline functions:
           ```
           def check(ctx):
               # Complex logic here
               return result
           check(ctx)
           ```
        """
        # Check if this looks like a function definition
        if "\n" in predicate or "def " in predicate:
            return self._evaluate_function(predicate, context)
        else:
            # Use parent's expression evaluation
            return super().evaluate(predicate, context)

    def _evaluate_function(self, predicate: str, context: PredicateContext) -> bool:
        """Evaluate a multiline function definition."""
        try:
            # Create evaluation namespace
            namespace = {
                **self.globals,
                "ctx": context,
                "shlex": __import__("shlex"),  # Allow imports
                "re": __import__("re"),
                "pathlib": __import__("pathlib"),
            }

            # Execute the function definition
            exec(predicate, namespace)

            # The predicate should define a function and call it
            # For example:
            # def check(ctx):
            #     return True
            # result = check(ctx)

            # Or it should set a 'result' variable
            if "result" in namespace:
                return bool(namespace["result"])

            # Or look for the last expression's value
            # Try to evaluate just the last line as an expression
            lines = predicate.strip().split("\n")
            if lines:
                last_line = lines[-1].strip()
                if last_line and not last_line.startswith(("def", "class", "if", "for", "while")):
                    result = eval(last_line, namespace)
                    if callable(result):
                        result = result(context)
                    return bool(result)

            raise ValueError("Predicate must set 'result' variable or end with an expression")

        except Exception as e:
            logger.error(f"Failed to evaluate function predicate: {e}")
            raise ValueError(f"Invalid predicate: {e}") from e
