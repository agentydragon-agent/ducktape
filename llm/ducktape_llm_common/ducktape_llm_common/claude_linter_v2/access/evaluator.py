"""Predicate evaluation engine for access control."""

import ast
import logging
from typing import Any, Callable, Dict, Optional, Set

from .context import PredicateContext
from .predicates import BUILTIN_PREDICATES, create_tool_predicate

logger = logging.getLogger(__name__)


class PredicateEvaluator:
    """Evaluates Python predicate expressions safely."""
    
    def __init__(self) -> None:
        """Initialize the evaluator with built-in predicates."""
        self.globals: Dict[str, Any] = {
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
        Evaluate a predicate expression in the given context.
        
        Args:
            predicate: Python expression to evaluate
            context: Context for evaluation
            
        Returns:
            Boolean result of evaluation
            
        Raises:
            ValueError: If predicate is invalid
        """
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
    
    def validate_predicate(self, predicate: str) -> Optional[str]:
        """
        Validate a predicate without evaluating it.
        
        Args:
            predicate: Predicate expression to validate
            
        Returns:
            Error message if invalid, None if valid
        """
        try:
            # Just try to compile it
            compile(predicate, '<predicate>', 'eval')
            return None
        except Exception as e:
            return str(e)