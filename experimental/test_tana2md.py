"""Unit tests for tana2md.py.

These tests validate the most important pieces of behaviour without touching
the full Markdown-generation pipeline.  They construct small in-memory graphs
that mimic the structure of real Tana exports and assert on:

* correct discovery of *Node supertags(s)* attributes and super-tag
  definitions,
* tag-detection logic (`Node.has_tag`),
* outline rendering,
* root detection (`find_roots`), and
* the end-to-end CLI that materialises Markdown files.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import tana2md as t2m

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _minimal_export(*, super_tag: str = "page") -> list[dict]:
    """Return a minimal Tana export payload as *list* of node dicts.

    The resulting structure contains:

    * `SYS_A13` – attributeDef *Node supertags(s)*
    * tagDef nodes for the four recognised super-tags
    * a root node titled *Root*, tagged with *super_tag*
    """

    attr_id = "SYS_A13"

    attr_node = {
        "id": attr_id,
        "props": {"_docType": "attributeDef", "name": "Node supertags(s)"},
        "children": [],
    }

    tags = ["day", "page", "issue", "event"]
    tag_nodes = [
        {
            "id": tag.upper(),
            "props": {"_docType": "tagDef", "name": tag},
            "children": [],
        }
        for tag in tags
    ]

    tuple_id = "TUP1"
    root_id = "ROOT"

    tuple_node = {
        "id": tuple_id,
        "props": {"_docType": "tuple", "_sourceId": attr_id},
        "children": [super_tag.upper()],
    }

    root_node = {
        "id": root_id,
        "props": {"name": "Root"},
        "children": [tuple_id],
    }

    return [attr_node] + tag_nodes + [tuple_node, root_node]


# ---------------------------------------------------------------------------
# unit tests
# ---------------------------------------------------------------------------


def test_graph_initialisation():
    g = t2m.Graph(t2m.detect_nodes(_minimal_export()))

    # super-tag attribute discovered eagerly
    assert "SYS_A13" in g.super_attr_ids

    # tagDef nodes recognised correctly
    assert g.tag_ids["page"] == "PAGE"


def test_node_has_tag():
    g = t2m.Graph(t2m.detect_nodes(_minimal_export(super_tag="day")))
    root = g["ROOT"]

    # root node is tagged with `day`
    assert root.has_tag({"DAY"}) is True
    # negative test – other tags not present
    assert root.has_tag({"PAGE"}) is False


def test_outline_rendering():
    g = t2m.Graph(t2m.detect_nodes(_minimal_export()))
    emitted: set[str] = set()
    lines = t2m.outline(g["ROOT"], emitted)

    # First line contains title and inline #page tag, no separate tuple bullet
    assert lines[0].startswith("- Root")
    assert "#page" in lines[0]
    assert not any("tuple:" in ln for ln in lines[1:])


def test_find_roots():
    g = t2m.Graph(t2m.detect_nodes(_minimal_export()))
    roots = t2m.find_roots(g, g.tag_ids)
    assert [n.id for n in roots] == ["ROOT"]


# ---------------------------------------------------------------------------
# integration test (CLI) ----------------------------------------------------
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_cli_generates_markdown(tmp_path: Path):
    """Run the full CLI against a minimal export and verify a file appears."""
    export = _minimal_export(super_tag="page")

    src = tmp_path / "export.json"
    dst = tmp_path / "out"
    src.write_text(json.dumps(export))

    # Execute the CLI as a subprocess so we exercise argument parsing too.
    result = subprocess.run(
        [sys.executable, str(Path(t2m.__file__).resolve()), str(src), str(dst)],
        capture_output=True,
        text=True,
        check=True,
    )

    # Should write exactly one Markdown file under `out/page/`.
    page_dir = dst / "page"
    files = list(page_dir.glob("*.md"))
    assert (
        len(files) == 1
    ), f"Expected 1 file, found {len(files)}; stderr: {result.stderr}"

    md = files[0].read_text()
    assert "<!-- id: ROOT -->" in md
    assert "#page" in md

