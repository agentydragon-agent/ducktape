#!/usr/bin/env python3
"""Scan Python codebase for manual dict construction and Pydantic model design issues.

This script performs two main analyses:
1. Finds dict literals with string-literal keys (candidates for Pydantic __init__)
2. Analyzes BaseModel classes for design issues (overlapping fields, single-field models)

Usage:
    python scan_manual_serde.py [directory]

Output:
    JSON with dict_literals and pydantic_models sections
"""

import ast
import json
import sys
from pathlib import Path
from typing import Any


class DictLiteralFinder(ast.NodeVisitor):
    """Find dict literals with string-literal keys."""

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.dict_literals: list[dict[str, Any]] = []
        self.current_function: str | None = None
        self.current_class: str | None = None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        old_func = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = old_func

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        old_func = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = old_func

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        old_class = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = old_class

    def visit_Dict(self, node: ast.Dict) -> None:
        # Check if any keys are string literals
        string_keys = []
        for key in node.keys:
            if key is None:  # **dict unpacking
                continue
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                string_keys.append(key.value)

        if string_keys:
            context = []
            if self.current_class:
                context.append(f"class {self.current_class}")
            if self.current_function:
                context.append(f"function {self.current_function}")

            self.dict_literals.append({
                "file": str(self.filepath),
                "line": node.lineno,
                "col": node.col_offset,
                "keys": string_keys,
                "num_keys": len(node.keys),
                "context": " > ".join(context) if context else "module-level",
            })

        self.generic_visit(node)


class PydanticModelAnalyzer(ast.NodeVisitor):
    """Analyze Pydantic BaseModel classes."""

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.models: list[dict[str, Any]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        # Check if inherits from BaseModel
        inherits_basemodel = False
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id == "BaseModel":
                inherits_basemodel = True
                break
            # Check for qualified names like pydantic.BaseModel
            if isinstance(base, ast.Attribute) and base.attr == "BaseModel":
                inherits_basemodel = True
                break

        if inherits_basemodel:
            fields = self._extract_fields(node)
            self.models.append({
                "file": str(self.filepath),
                "line": node.lineno,
                "name": node.name,
                "fields": fields,
                "num_fields": len(fields),
            })

        self.generic_visit(node)

    def _extract_fields(self, class_node: ast.ClassDef) -> dict[str, str]:
        """Extract field names and type annotations from class body."""
        fields = {}
        for stmt in class_node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                field_name = stmt.target.id
                # Get type annotation as string
                type_str = ast.unparse(stmt.annotation) if stmt.annotation else "Any"
                fields[field_name] = type_str
        return fields


def scan_file(filepath: Path) -> tuple[list[dict], list[dict]]:
    """Scan a single Python file for dict literals and Pydantic models."""
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))

        dict_finder = DictLiteralFinder(filepath)
        dict_finder.visit(tree)

        model_analyzer = PydanticModelAnalyzer(filepath)
        model_analyzer.visit(tree)

        return dict_finder.dict_literals, model_analyzer.models
    except (SyntaxError, UnicodeDecodeError):
        # Skip files with syntax errors or encoding issues
        return [], []


def scan_directory(root: Path) -> dict[str, Any]:
    """Scan all Python files in directory tree."""
    all_dict_literals = []
    all_models = []

    for py_file in root.rglob("*.py"):
        # Skip common non-source directories
        if any(
            part in py_file.parts
            for part in ["venv", "__pycache__", ".git", "node_modules", ".tox"]
        ):
            continue

        dict_literals, models = scan_file(py_file)
        all_dict_literals.extend(dict_literals)
        all_models.extend(models)

    return {
        "summary": {
            "total_dict_literals": len(all_dict_literals),
            "total_models": len(all_models),
        },
        "dict_literals": all_dict_literals,
        "pydantic_models": all_models,
    }


def main() -> None:
    """Main entry point."""
    if len(sys.argv) > 1:
        root = Path(sys.argv[1])
    else:
        root = Path.cwd()

    if not root.is_dir():
        print(f"Error: {root} is not a directory", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning {root}...", file=sys.stderr)
    results = scan_directory(root)

    # Output JSON
    print(json.dumps(results, indent=2))

    # Print summary to stderr
    print("\n=== Summary ===", file=sys.stderr)
    print(f"Dict literals with string keys: {results['summary']['total_dict_literals']}", file=sys.stderr)
    print(f"Pydantic models found: {results['summary']['total_models']}", file=sys.stderr)


if __name__ == "__main__":
    main()
