"""tana2md.py — structured Tana JSON → Markdown

Example:

  python -m tana2md ~/downloads/tana-export-2025-05-12.json ~/tana-export-2025-05-12

Highlights
-----------
* skips system/view/workspace shells
* a node becomes a *root file* when it:
    – has super‑tag #day, #page, #issue or #event, or
    – it has *no parents*
* definition shells titled *Default* or *Calendar* are ignored
* leftovers go to `zzz_misc.md`
* buckets: files are written to `out/issue/`, `out/day/`, … automatically
* each file starts with `<!-- id: NODE_ID -->`
* SHOW_ID=1 shows ‹id› inline, DEBUG_NODE=<ID> dumps decisions for one node

Environment flags
-----------------
STRICT_ROOTS env var (legacy).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import re
from dataclasses import dataclass
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Rendering configuration (view-level)
# ---------------------------------------------------------------------------


@dataclass
class RenderCfg:
    show_id: bool = False
    debug_node: str | None = None


MAX_DEPTH = 100
TAG_RE = re.compile(r"<[^>]*>")
INLINE_REF_RE = re.compile(r'<span[^>]+data-inlineref-node="([^"]+)"[^>]*></span>')
SYSTEM_TYPES = {
    "tagDef",
    "attributeDef",
    "field-definition",
    "workspace",
    "view",
    "viewDef",  # observed in real exports
}

# Super-tags that mark Markdown roots / buckets
ROOT_TAGS: tuple[str, ...] = ("day", "page", "issue", "event")


# ─── Node / Graph ────────────────────────────────────────────────────
@dataclass
class Node:
    id: str
    raw: Dict[str, Any]
    graph: "Graph"

    @property
    def props(self) -> Dict[str, Any]:
        return self.raw.get("props", {})

    @property
    def doc_type(self) -> str | None:
        return self.props.get("_docType")

    @property
    def children_ids(self) -> List[str]:
        return self.raw.get("children", [])

    @property
    def children(self) -> List["Node"]:
        return [self.graph[c] for c in self.children_ids if c in self.graph]

    def title(self, *, show_id: bool = False) -> str:
        raw = (
            self.props.get("name")
            or self.raw.get("name")
            or self.props.get("text")
            or self.props.get("description")
            or ""
        )

        def repl(m):
            rid = m.group(1)
            return f"[[{self.graph[rid].title(show_id=show_id) or rid}|{rid}]]"

        txt = INLINE_REF_RE.sub(repl, raw)
        txt = TAG_RE.sub("", txt).replace("\\n", " ").strip()
        return f"{txt} ‹{self.id}›" if show_id and txt else txt

    def debug(self, msg: str, *, debug_node: str | None = None):
        if debug_node and self.id == debug_node:
            logging.debug(f"[{self.id}] {msg}")

    @property
    def is_system(self) -> bool:
        return self.id.startswith("SYS_") or self.doc_type in SYSTEM_TYPES

    # ------------------------------------------------------------------
    # Tag helpers placed into Node for easier use
    # ------------------------------------------------------------------

    def _tuple_has_tag(self, t: "Node", tag_set: set[str]) -> bool:
        """Return True if *t* (tuple) references any tag in *tag_set* and is
        connected to the *Node supertags(s)* attribute."""

        if t.doc_type != "tuple":
            return False

        if not any(cid in tag_set for cid in t.children_ids):
            return False

        attr_ids = self.graph.super_attr_ids
        if t.props.get("_sourceId") in attr_ids:
            return True
        return any(cid in attr_ids for cid in t.children_ids)

    def has_tag(self, tag_set: set[str]) -> bool:
        """Return True when the node is marked with one of *tag_set*."""

        # direct tuple children
        for t in self.children:
            if self._tuple_has_tag(t, tag_set):
                return True

        # meta tuples
        mid = self.props.get("_metaNodeId")
        if mid and mid in self.graph:
            meta = self.graph[mid]
            for t in meta.children:
                if self._tuple_has_tag(t, tag_set):
                    return True
        return False

    # ------------------------------------------------------------------
    def super_tags(self) -> List[str]:
        """Return list of *all* tag names applied as super-tags on this node."""

        tag_names: list[str] = []
        for name, tid in self.graph.tag_ids.items():
            if self.has_tag({tid}):
                tag_names.append(name)
        return tag_names

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    def tuple_line(self, *, show_id: bool = False) -> str:
        src = self.props.get("_sourceId")
        tag_name = next((k for k, v in self.graph.tag_ids.items() if v == src), "tuple")
        vals = [c.title() for c in self.children if c.title()]
        txt = f"{tag_name}: {', '.join(vals)}" if vals else tag_name
        return f"{txt} ‹{self.id}›" if show_id else txt

    def meta_lines(self, *, show_id: bool = False) -> List[str]:
        mid = self.props.get("_metaNodeId")
        if not mid or mid not in self.graph:
            return []

        meta = self.graph[mid]
        all_tag_ids = set(self.graph.tag_ids.values())
        out: list[str] = []
        for c in meta.children:
            if c.doc_type == "tuple":
                # skip tuples that merely assign super-tags (they’ll be shown inline)
                if self._tuple_has_tag(c, all_tag_ids):
                    continue
                out.append(c.tuple_line(show_id=show_id))
            else:
                t = c.title()
                if t:
                    out.append(t)
        return out


class Graph(dict):
    """Graph mapping node id → Node with extra lookup helpers."""

    def __init__(self, mapping: Dict[str, Any]):
        super().__init__({k: Node(k, v, self) for k, v in mapping.items()})

        # Discover helper sets/maps eagerly so downstream helpers stay simple.
        self.super_attr_ids: set[str] = self._discover_super_attr_ids()
        self.tag_ids: Dict[str, str] = self._discover_tag_defs()

    # ------------------------------------------------------------------
    def _discover_super_attr_ids(self) -> set[str]:
        ids = {
            n.id
            for n in self.values()
            if n.doc_type == "attributeDef"
            and str(n.props.get("name", "")).lower().startswith("node supertags")
        }
        return ids or {"SYS_A13"}

    # ------------------------------------------------------------------
    def _discover_tag_defs(self) -> Dict[str, str]:
        tag_map = {
            str(n.props.get("name", "")).lower(): n.id
            for n in self.values()
            if n.doc_type == "tagDef"
        }
        self.tag_name_by_id = {v: k for k, v in tag_map.items()}
        return tag_map


# ─── load helpers ────────────────────────────────────────────────────
def detect_nodes(data: Any) -> Dict[str, Any]:
    return {n["id"]: n for n in data["docs"]}


def load_graph(path: str) -> Graph:
    return Graph(detect_nodes(json.loads(path.read_text())))


# ─── root detection ─────────────────────────────────────────────────
# ─── tagging helpers ---------------------------------------------------------
# A node can be marked with a super-tag (#day, #page, …) in two slightly
# different ways that appear in real-world Tana exports:
#
# 1. A *direct* tuple is placed under the node itself. Example hierarchy:
#        - My Page
#          - tuple (#page)
#
# 2. A tuple lives inside the node’s *meta* shell referenced via the
#    `_metaNodeId` field. This is the structure produced by the current Tana
#    export pipeline when you tag an existing node with a super-tag from the
#    UI.

# We only consider tuples that explicitly modify the *Node supertags(s)*
# attribute. In real exports that attribute is materialised with id
# `SYS_A13`.  We check for the id either in the children list *or* (less
# frequently) in the `_sourceId` property.


def find_roots(
    g: Graph,
    tag_ids: Dict[str, str],
    *,
    strict_roots: bool = False,
    debug_node: str | None = None,
) -> List[Node]:
    parents = {cid for n in g.values() for cid in n.children_ids}
    tag_set = {tag_ids[name] for name in ROOT_TAGS if name in tag_ids}
    roots = []
    for n in g.values():
        title = n.title()
        if n.is_system or n.doc_type == "search":
            continue
        if not title or title.lower() in {"default", "calendar"}:
            continue
        tagged = n.has_tag(tag_set)
        orphan = n.id not in parents
        root = (strict_roots and tagged) or ((not strict_roots) and (orphan or tagged))
        if root and tagged:
            roots.append(n)
            n.debug(f"ROOT {orphan=} {tagged=}", debug_node=debug_node)
        else:
            n.debug(f"skip {orphan=} {tagged=}", debug_node=debug_node)
    return roots


# ─── outline ----------------------------------------------------------------
def outline(
    node: Node,
    emitted: set[str],
    *,
    depth: int = 0,
    root_ids: set[str] | None = None,
    cfg: RenderCfg | None = None,
) -> List[str]:
    """Render *node* (recursively) to a Markdown bullet list.

    *emitted* keeps track of nodes that have already been expanded so we do not
    duplicate content in different files.  *root_ids* is the set of nodes that
    will be rendered as **separate** Markdown roots.  When we encounter a child
    that is in *root_ids* (and is *not* the current node) we include a single
    bullet with its title but do **not** descend any further. This prevents the
    situation where a future root gets consumed by an earlier, higher-level
    outline (which previously happened for page-tagged nodes nested under a
    “Calendar” page).
    """

    if depth > MAX_DEPTH:
        raise RuntimeError(
            f"outline depth {depth} exceeds MAX_DEPTH={MAX_DEPTH} at node {node.id}"
        )

    if node.id in emitted:
        return []

    emitted.add(node.id)
    indent = "  " * depth
    lines: List[str] = []

    # ── tuple ────────────────────────────────────────────────────────────
    if node.doc_type == "tuple":
        lines.append(indent + "- " + node.tuple_line(show_id=cfg.show_id))
        return lines

    # ── regular node ─────────────────────────────────────────────────────
    cfg = cfg or RenderCfg()
    title_text = node.title(show_id=cfg.show_id)
    if title_text:
        tags_inline = "".join(f" #{name}" for name in node.super_tags())
        lines.append(indent + "- " + title_text + tags_inline)

    # meta-information lines (tuples etc.)
    for ml in node.meta_lines(show_id=cfg.show_id):
        lines.append(indent + "  - " + ml)

    for c in node.children:
        # Skip descending into children that are scheduled to become their own
        # Markdown roots. Still include the reference bullet so the link is
        # visible from the parent context.
        if root_ids and c.id in root_ids and c.id != node.id:
            t = c.title(show_id=cfg.show_id)
            if t:
                lines.append(indent + "  - " + t)
            continue

        if c.doc_type == "tuple" and node._tuple_has_tag(
            c, set(node.graph.tag_ids.values())
        ):
            # skip rendering separate bullet for super-tag tuples (they are inline)
            continue

        lines.extend(outline(c, emitted, depth=depth + 1, root_ids=root_ids, cfg=cfg))

    return lines


def slugify(t: str, L: int = 50) -> str:
    return (re.sub(r"[^A-Za-z0-9\-]+", "-", t).strip("-") or "untitled")[:L]


# ─── main ──────────────────────────────────────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=pathlib.Path)
    ap.add_argument("dst", type=pathlib.Path)
    ap.add_argument("--top", type=int, help="only export the first N roots")
    ap.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="override LOG env (default INFO, DEBUG for verbose output)",
    )
    # replicate other env-flags as CLI overrides for convenience
    ap.add_argument("--show-id", action="store_true", help="include node ids inline")
    ap.add_argument(
        "--strict-roots", action="store_true", help="only tagged nodes are roots"
    )
    ap.add_argument("--debug-node", help="log decisions for a single node id")

    args = ap.parse_args(argv)

    # ---- configuration overrides ------------------------------------
    if args.log_level:
        logging.getLogger().setLevel(args.log_level.upper())

    strict_roots_flag = args.strict_roots or bool(int(os.getenv("STRICT_ROOTS", "0")))
    cfg = RenderCfg(show_id=args.show_id, debug_node=args.debug_node)

    g = load_graph(args.src)
    roots = find_roots(
        g, g.tag_ids, strict_roots=strict_roots_flag, debug_node=cfg.debug_node
    )
    if args.top:
        roots = roots[: args.top]

    emitted: set[str] = set()
    root_ids = {r.id for r in roots}
    misc = []
    for idx, r in enumerate(roots, 1):
        lines = outline(r, emitted, root_ids=root_ids, cfg=cfg)
        if not lines:
            continue
        # --- determine bucket (issue/day/page/event) --------------------------------
        bucket = None
        for name in ROOT_TAGS:
            tid = g.tag_ids.get(name)
            if tid and r.has_tag({tid}):
                bucket = name
                break
        target = args.dst / (bucket if bucket else "")
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{idx:03d}-{slugify(r.title())}.md"
        path.write_text(
            f"<!-- id: {r.id} -->\n" + "\n".join(lines) + "\n", encoding="utf-8"
        )

    for n in g.values():
        if n.id not in emitted and not n.is_system and n.children_ids:
            misc.extend(outline(n, emitted, root_ids=root_ids, cfg=cfg))
    if misc:
        (args.dst / "zzz_misc.md").write_text("\n".join(misc) + "\n", encoding="utf-8")

    logging.info("wrote %d root files%s", len(roots), " + misc" if misc else "")


if __name__ == "__main__":
    main()
