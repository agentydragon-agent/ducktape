"""Test that database layer is properly isolated from MCP I/O layer.

The database persistence layer should not depend on MCP I/O models to avoid
coupling database migrations to protocol changes.
"""

import ast
from pathlib import Path


def test_db_does_not_import_grader_models():
    """Verify that db/ modules do not import from grader.models.

    The database layer uses db.snapshots (DBTruePositiveIssue, DBKnownFalsePositive)
    while the grader layer uses grader.models (TruePositiveIssue, KnownFalsePositive).

    Conversion between these layers happens in grader.persistence.
    """
    # Get all Python files in src/adgn/props/db/
    db_dir = Path(__file__).parent.parent.parent.parent / "src" / "adgn" / "props" / "db"
    db_files = list(db_dir.glob("*.py"))

    violations = []

    for file_path in db_files:
        if file_path.name.startswith("_"):
            continue  # Skip private modules

        content = file_path.read_text()
        tree = ast.parse(content, filename=str(file_path))

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and "grader.models" in node.module:
                    violations.append(f"{file_path.name}: imports from {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if "grader.models" in alias.name:
                        violations.append(f"{file_path.name}: imports {alias.name}")

    if violations:
        msg = (
            "Database layer must not import from grader.models.\n"
            "Use db.snapshots models instead (DBTruePositiveIssue, DBKnownFalsePositive).\n"
            "Conversions should live in grader.persistence.\n\n"
            "Violations found:\n" + "\n".join(f"  - {v}" for v in violations)
        )
        raise AssertionError(msg)
