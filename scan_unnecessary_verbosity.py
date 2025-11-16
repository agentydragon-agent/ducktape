#!/usr/bin/env python3
"""
Scan for unnecessary verbosity in Python code.
Finds patterns like single-assignment variables, verbose boolean returns, etc.
"""

import ast
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class Finding:
    """A single verbosity finding"""
    file_path: str
    line_number: int
    pattern: str
    code_snippet: str
    suggestion: str
    severity: str  # "recommend", "consider", "low-priority"


class VerbosityDetector(ast.NodeVisitor):
    """AST visitor to detect various verbosity patterns"""

    def __init__(self, file_path: str, source_lines: List[str]):
        self.file_path = file_path
        self.source_lines = source_lines
        self.findings: List[Finding] = []

        # Track variable assignments and usages
        self.assignments = defaultdict(list)  # name -> [(line, node)]
        self.usages = defaultdict(list)       # name -> [(line, node)]
        self.scope_stack = []  # Track current scope

    def get_line(self, lineno: int) -> str:
        """Get source line by line number (1-indexed)"""
        if 1 <= lineno <= len(self.source_lines):
            return self.source_lines[lineno - 1]
        return ""

    def get_lines(self, start: int, end: int) -> str:
        """Get multiple source lines"""
        lines = []
        for i in range(start, end + 1):
            lines.append(self.get_line(i))
        return "\n".join(lines)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Check for verbose boolean returns"""
        # Check for if-else returning True/False
        for i, stmt in enumerate(node.body):
            if isinstance(stmt, ast.If):
                # Check for pattern: if cond: return True else: return False
                if (isinstance(stmt.body, list) and len(stmt.body) == 1 and
                    isinstance(stmt.body[0], ast.Return) and
                    isinstance(stmt.orelse, list) and len(stmt.orelse) == 1):

                    return_true = (isinstance(stmt.body[0].value, ast.Constant) and
                                   stmt.body[0].value.value is True)

                    orelse_stmt = stmt.orelse[0]
                    return_false = False

                    if isinstance(orelse_stmt, ast.Return):
                        return_false = (isinstance(orelse_stmt.value, ast.Constant) and
                                       orelse_stmt.value.value is False)
                    elif isinstance(orelse_stmt, ast.If):
                        # Could be elif chain, skip for now
                        pass

                    if return_true and return_false:
                        snippet = self.get_lines(stmt.lineno, stmt.orelse[0].lineno)
                        self.findings.append(Finding(
                            file_path=self.file_path,
                            line_number=stmt.lineno,
                            pattern="Verbose boolean return",
                            code_snippet=snippet,
                            suggestion="Return the boolean expression directly instead of if-else",
                            severity="recommend"
                        ))

                # Check for: if cond: return True\nreturn False
                if (isinstance(stmt.body, list) and len(stmt.body) == 1 and
                    isinstance(stmt.body[0], ast.Return) and
                    isinstance(stmt.body[0].value, ast.Constant) and
                    stmt.body[0].value.value is True and
                    not stmt.orelse and
                    i + 1 < len(node.body)):

                    next_stmt = node.body[i + 1]
                    if (isinstance(next_stmt, ast.Return) and
                        isinstance(next_stmt.value, ast.Constant) and
                        next_stmt.value.value is False):

                        snippet = self.get_lines(stmt.lineno, next_stmt.lineno)
                        self.findings.append(Finding(
                            file_path=self.file_path,
                            line_number=stmt.lineno,
                            pattern="Verbose boolean return (if-return pattern)",
                            code_snippet=snippet,
                            suggestion="Return the boolean expression directly",
                            severity="recommend"
                        ))

                # Check for else-after-return (Pattern 3)
                if (isinstance(stmt.body, list) and len(stmt.body) >= 1 and
                    isinstance(stmt.body[-1], ast.Return) and
                    stmt.orelse and len(stmt.orelse) == 1 and
                    isinstance(stmt.orelse[0], ast.Return)):

                    snippet = self.get_lines(stmt.lineno, stmt.orelse[0].lineno)
                    self.findings.append(Finding(
                        file_path=self.file_path,
                        line_number=stmt.lineno,
                        pattern="Redundant else after return",
                        code_snippet=snippet,
                        suggestion="Remove 'else' since the if-block returns",
                        severity="consider"
                    ))

        self.generic_visit(node)

    def visit_Try(self, node: ast.Try):
        """Check for verbose exception handling"""
        # Pattern: try-except-raise (just re-raising without context)
        for handler in node.handlers:
            if (len(handler.body) == 1 and
                isinstance(handler.body[0], ast.Raise) and
                handler.body[0].exc is None):  # bare raise

                snippet = self.get_lines(node.lineno, handler.body[0].lineno)
                self.findings.append(Finding(
                    file_path=self.file_path,
                    line_number=node.lineno,
                    pattern="Pointless try-except-raise",
                    code_snippet=snippet,
                    suggestion="Remove the try-except if only re-raising without adding context",
                    severity="recommend"
                ))

            # Pattern: catch to return None (could use .get() for dicts)
            if (len(handler.body) == 1 and
                isinstance(handler.body[0], ast.Return) and
                isinstance(handler.body[0].value, ast.Constant) and
                handler.body[0].value.value is None and
                handler.type and isinstance(handler.type, ast.Name) and
                handler.type.id == 'KeyError'):

                snippet = self.get_lines(node.lineno, handler.body[0].lineno)
                self.findings.append(Finding(
                    file_path=self.file_path,
                    line_number=node.lineno,
                    pattern="Verbose KeyError handling",
                    code_snippet=snippet,
                    suggestion="Consider using .get() method instead of try-except KeyError",
                    severity="consider"
                ))

        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign):
        """Track assignments for single-use detection"""
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.assignments[target.id].append((node.lineno, node))
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        """Track variable usages"""
        if isinstance(node.ctx, ast.Load):
            self.usages[node.id].append((node.lineno, node))
        self.generic_visit(node)

    def find_single_use_vars(self, tree: ast.AST):
        """Find variables assigned once and used once immediately after (Pattern 1)"""
        # First, collect all assignments and usages
        self.visit(tree)

        # Now analyze for single-use pattern
        for name, assign_list in self.assignments.items():
            # Skip common names that might be OK
            if name.startswith('_') or name in ('self', 'cls'):
                continue

            if len(assign_list) == 1 and name in self.usages:
                assign_line, assign_node = assign_list[0]
                use_list = self.usages[name]

                # Check if used exactly once on the next line
                next_line_uses = [line for line, _ in use_list if line == assign_line + 1]

                if len(use_list) == 1 and next_line_uses:
                    # Get the assignment line
                    assign_line_text = self.get_line(assign_line)
                    use_line_text = self.get_line(assign_line + 1)

                    # Skip if it's for debugging/logging
                    if 'log' in use_line_text.lower() or 'print' in use_line_text.lower():
                        continue

                    # Skip if the variable name adds semantic meaning
                    # (not generic like 'result', 'temp', 'value', 'data')
                    generic_names = {'result', 'temp', 'value', 'data', 'ret', 'res',
                                    'output', 'response', 'obj', 'item'}

                    # Check line length - if inlining would make it too long, skip
                    combined_length = len(use_line_text) + len(assign_line_text.split('=', 1)[1])
                    if combined_length > 88:  # PEP 8 line length
                        continue

                    severity = "recommend" if name in generic_names else "consider"

                    snippet = f"{assign_line_text}\n{use_line_text}"
                    self.findings.append(Finding(
                        file_path=self.file_path,
                        line_number=assign_line,
                        pattern="Single-assignment variable",
                        code_snippet=snippet,
                        suggestion=f"Variable '{name}' is only used once on the next line. Consider inlining if it doesn't reduce readability.",
                        severity=severity
                    ))


def scan_file(file_path: str) -> List[Finding]:
    """Scan a single Python file for verbosity patterns"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
            source_lines = source.splitlines()

        tree = ast.parse(source, filename=file_path)
        detector = VerbosityDetector(file_path, source_lines)

        # Run all detection passes
        detector.find_single_use_vars(tree)

        return detector.findings

    except SyntaxError:
        # Skip files with syntax errors
        return []
    except Exception as e:
        print(f"Error scanning {file_path}: {e}")
        return []


def is_test_file(path: str) -> bool:
    """Check if a file is a test file"""
    path_lower = path.lower()
    return (
        '/test/' in path_lower or
        '/tests/' in path_lower or
        'test_' in os.path.basename(path_lower) or
        '_test.py' in path_lower or
        'conftest.py' in path_lower
    )


def scan_directory(root_dir: str, exclude_dirs: set = None) -> List[Finding]:
    """Scan all Python files in a directory tree"""
    if exclude_dirs is None:
        exclude_dirs = {
            'venv', '.venv', 'env', '.env',
            '__pycache__', '.git', '.tox',
            'build', 'dist', '.eggs',
            'node_modules'
        }

    all_findings = []

    for root, dirs, files in os.walk(root_dir):
        # Remove excluded directories from traversal
        dirs[:] = [d for d in dirs if d not in exclude_dirs]

        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)

                # Skip test files
                if is_test_file(file_path):
                    continue

                findings = scan_file(file_path)
                all_findings.extend(findings)

    return all_findings


def format_findings(findings: List[Finding]) -> str:
    """Format findings as markdown"""
    if not findings:
        return "No verbosity issues found!\n"

    # Group by pattern type
    by_pattern = defaultdict(list)
    for finding in findings:
        by_pattern[finding.pattern].append(finding)

    output = []
    output.append("# Unnecessary Verbosity Scan Results\n")
    output.append(f"**Total findings:** {len(findings)}\n")
    output.append(f"**Scanned:** {len(set(f.file_path for f in findings))} files\n")

    for pattern, pattern_findings in sorted(by_pattern.items()):
        output.append(f"\n## {pattern} ({len(pattern_findings)} occurrences)\n")

        for finding in sorted(pattern_findings, key=lambda f: (f.file_path, f.line_number)):
            output.append(f"\n### {finding.file_path}:{finding.line_number}")
            output.append(f"\n**Severity:** {finding.severity}")
            output.append(f"\n**Suggestion:** {finding.suggestion}\n")
            output.append("```python")
            output.append(finding.code_snippet)
            output.append("```\n")

    return "\n".join(output)


if __name__ == "__main__":
    import sys

    root_dir = sys.argv[1] if len(sys.argv) > 1 else "/home/user/ducktape"

    print(f"Scanning {root_dir}...")
    findings = scan_directory(root_dir)

    print(f"\nFound {len(findings)} potential verbosity issues")

    # Write to output file
    output_path = "/home/user/ducktape/scan-results/unnecessary-verbosity.md"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, 'w') as f:
        f.write(format_findings(findings))

    print(f"Results written to {output_path}")
