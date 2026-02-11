from __future__ import annotations

import ast
from pathlib import Path

import pytest


def _python_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return [p for p in root.rglob("*.py") if p.is_file()]


def _find_openai_imports(py_path: Path) -> list[tuple[int, str]]:
    offenders: list[tuple[int, str]] = []
    source = py_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(py_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "openai" or alias.name.startswith("openai."):
                    offenders.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "openai" or mod.startswith("openai."):
                offenders.append((node.lineno, f"from {mod} import ..."))
    return offenders


def _assert_no_openai_imports(root: Path) -> None:
    assert root.exists(), f"Path not found: {root}"
    offenders_all: list[tuple[Path, int, str]] = []
    for py in _python_files(root):
        for lineno, what in _find_openai_imports(py):
            offenders_all.append((py, lineno, what))
    if offenders_all:
        details = "\n".join(f"{p}:{lineno}: {what}" for p, lineno, what in offenders_all)
        raise AssertionError(
            (
                "Layering violation: OpenAI SDK must not be imported directly in this layer.\n"
                "Intended design: SDK usage is confined to adapter/translation points\n"
                "(e.g., adgn.openai_utils.*) which expose Pydantic models and a small\n"
                "protocol (OpenAIModelProto). All higher layers (MiniCodex, git_commit_ai)\n"
                "must depend only on adapter types and protocols.\n\n"
                "Offending imports:\n"
            )
            + details
        )


@pytest.mark.parametrize(
    "rel_path",
    ["adgn/src/adgn/agent", "adgn/src/adgn/git_commit_ai", "adgn/src/adgn/llm/llm_edit.py", "adgn/src/adgn/props"],
)
def test_no_direct_openai_imports(rel_path: str) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    root = repo_root / rel_path
    _assert_no_openai_imports(root)
