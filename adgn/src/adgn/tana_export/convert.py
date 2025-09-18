#!/usr/bin/env python3
"""
convert.py - Convert Tana JSON dump to

* Markdown  →  <dump>.converted.md
* Tana-paste → <dump>.converted.tanapaste.txt
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
import html
from pathlib import Path

from .tana_lib import (
    CHECKBOX_CHECKED_ID,
    CHECKBOX_KEY_ID,
    CHECKBOX_UNCHECKED_ID,
    SUPERTAG_KEY_ID,
    URL_KEY_ID,
    BaseNode,
    CodeBlockNode,
    NodeId,
    NodeStore,
    TupleNode,
    VisualNode,
    get_tuple_value,
)
from .tana_lib.html_utils import (
    DATE_SPAN_PATTERN,
    NODE_SPAN_PATTERN,
    find_inline_node_refs,
    html_to_markdown,
    parse_inline_date,
)

# Small constants to clarify tuple arity checks
MIN_TUPLE_CHILDREN = 2

# ──────────────────────────  Headline  ────────────────────────── #


def _journal_headline(name: str) -> str:
    # pattern: YYYY-MM-DD - Weekday
    try:
        date_str = name.split(" ")[0]  # "2025-05-06"
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        # TODO: detect day more robustly
        return dt.strftime("%a, %b %-d")  # "Tue, May 6"
    except Exception:
        return name


def _is_wrapper(node: BaseNode) -> bool:
    """Nodes that should *not* get their own bullet - just pass through."""
    return node.props.doc_type in {"workspace", "viewDef", "layout"}


def _is_supertag_tuple(t: TupleNode) -> bool:
    return len(t.children) > 0 and t.children[0] == SUPERTAG_KEY_ID


def _is_url_tuple(t: TupleNode) -> bool:
    return len(t.children) > 0 and t.children[0] == URL_KEY_ID


@dataclass
class RenderContext:
    """Context for rendering nodes, including indentation and style."""

    store: NodeStore
    style: str
    indent: str = ""
    visited: set[str] = field(default_factory=set)

    # ──────────────────────────────────────────────────────────────
    # Helper: return a scalar text representation of a node
    #         or None if the node is actually a container.
    # ──────────────────────────────────────────────────────────────
    def _scalar_text(self, node: BaseNode) -> str | None:
        # Check if the node itself is a checkbox value
        if node.id == CHECKBOX_CHECKED_ID:
            return "[X] "  # Note: trailing space for consistency with expected output
        if node.id == CHECKBOX_UNCHECKED_ID:
            return "[ ]"

        # regular leaf: has its own name and no children (except for special tuples)
        if node.name and not node.children:
            return self._inline_to_text(node.name)

        # special case: a checkbox tuple
        if val := get_tuple_value(node, CHECKBOX_KEY_ID):
            return self._scalar_text(val)

        return None  # container, not a scalar

    def _inline_to_text(self, raw: str) -> str:
        def node_sub(m):
            nid = m.group(1)
            tgt = self.store.get(nid)
            nm = html.unescape((tgt.name if tgt else nid) or nid)
            return f"[[{nm}^{nid}]]" if self.style == "tana" else nm

        def date_sub(m):
            iso = parse_inline_date(m.group(1))
            return f"[[date:{iso}]]" if self.style == "tana" else iso

        # keep verbatim code / image lines
        if raw.lstrip().startswith("```") or raw.lstrip().startswith("!"):
            return raw  # no substitutions

        txt = NODE_SPAN_PATTERN.sub(node_sub, raw)
        txt = DATE_SPAN_PATTERN.sub(date_sub, txt)

        # Convert HTML formatting to markdown for tana style
        if self.style == "tana":
            return str(html_to_markdown(txt))
        return str(html.unescape(txt))

    @contextmanager
    def add_indent(self):
        """Context manager to temporarily add 2 spaces of indentation."""
        old_indent = self.indent
        self.indent += "  "
        try:
            yield
        finally:
            self.indent = old_indent

    def _headline(self, node: BaseNode) -> str:
        raw = node.name or node.id
        if node.props.doc_type == "journalPart":
            raw = _journal_headline(raw)

        base = self._inline_to_text(raw)

        # Description suffix
        if node.props.description:
            base += " - " + self._inline_to_text(node.props.description)

        # supertags
        tags = list(self.store.get_supertags(node.id))
        if node.props.doc_type == "journalPart" and "day" not in tags:
            tags.append("day")
        if tags:
            # Format tags - wrap in [[...]] if they contain spaces
            formatted_tags = []
            for t in tags:
                v = f"[[{t}]]" if " " in t else t
                formatted_tags.append("#" + v)
            base += " " + ", ".join(formatted_tags)
        return base

    def render_tuple(self, t: TupleNode):
        """Render a tuple node with its key and value(s)."""
        # need at least key + value
        if len(t.children) < MIN_TUPLE_CHILDREN or not (
            key_node := self.store.get(t.children[0])
        ):
            return
        prefix = (
            f"{self.indent}- {self._inline_to_text(key_node.name or key_node.id)}:: "
        )

        # Handle multi-value tuples (more than 2 children)
        if len(t.children) > MIN_TUPLE_CHILDREN:
            # All children after the first are values
            yield prefix
            for val_node in t.child_nodes[1:]:
                # For tana style, render as reference if the value is not owned by this tuple
                # (i.e., it's a reference to an existing node)
                with self.add_indent():
                    if (
                        self.style == "tana"
                        and val_node.name
                        and val_node.props.owner_id != t.id
                    ):
                        yield f"{self.indent}- [[{self._inline_to_text(val_node.name)}^{val_node.id}]]"
                    else:
                        yield from self.render_node(val_node)
            return

        if len(t.child_nodes) < MIN_TUPLE_CHILDREN:
            return
        # Binary tuple (key + single value)
        val_node = t.child_nodes[1]

        # try to render value inline
        if (val_txt := self._scalar_text(val_node)) is not None:
            # Add trailing space for consistency with expected output
            yield prefix + val_txt
            # still render value-node children (e.g., URL, tags) one level deeper
            with self.add_indent():
                for child in val_node.child_nodes:
                    yield from self.render_node(child)
            return

        # ── non-scalar: fall back to nested layout ────────────────
        # Check if this is an empty value node (no name, no children)
        # Common for unset checkbox attributes
        yield prefix
        with self.add_indent():
            if val_node.name or val_node.children:
                yield from self.render_node(val_node)

    def render_node(self, n: BaseNode):
        if _is_wrapper(n):
            for child in n.child_nodes:
                yield from self.render_node(child)
            return

        # Special handling for visual (image) nodes
        if isinstance(n, VisualNode) and (url := n.get_image_url()):
            # Use the visual node's name as caption if it has one
            caption = self._inline_to_text(n.name) if n.name else ""
            yield f"{self.indent}-  ![{caption}]({url}) "
            return

        # Special handling for code blocks
        if isinstance(n, CodeBlockNode) and self.style == "tana":
            language = n.get_language()
            # Write code block with triple backticks
            yield f"```{language}"
            if n.name:
                yield from n.name.split("\n")
            yield "```"
            return

        if n.id in self.visited:
            txt = self._inline_to_text(n.name or n.id)
            txt = f"[[{txt}^{n.id}]]" if self.style == "tana" else txt
            yield f"{self.indent}- {txt}"
            return
        self.visited.add(n.id)
        yield f"{self.indent}- {self._headline(n)}"

        # URL tuples first (for link nodes)
        for c in n.child_nodes:
            if isinstance(c, TupleNode) and _is_url_tuple(c):
                with self.add_indent():
                    yield from self.render_tuple(c)

        # Check if this node has an associationMap - if so, render children as references with associated data
        with self.add_indent():
            for c in n.child_nodes:
                if n.association_map and self.style == "tana":
                    if isinstance(c, TupleNode):
                        continue
                    yield f"{self.indent}- [[{self._inline_to_text(c.name or c.id)}^{c.id}]]"
                    if not (
                        c.id in n.association_map
                        and (assoc_node := self.store.get(n.association_map[c.id]))
                    ):
                        continue
                    with self.add_indent():
                        # Render associated data if exists
                        yield f"{self.indent}- **Associated data**"
                        # Render tuples from the associated data node
                        with self.add_indent():
                            for assoc_child in assoc_node.child_nodes:
                                if isinstance(assoc_child, TupleNode):
                                    yield from self.render_tuple(assoc_child)
                # Render all children in their original order
                elif not isinstance(c, TupleNode):
                    # Render as reference if non-owned AND (already visited OR search node)
                    if c.props.owner_id != n.id and (
                        c.id in self.visited
                        or (n.props.doc_type == "search" and self.style == "tana")
                    ):
                        yield f"{self.indent}- [[{self._inline_to_text(c.name or c.id)}^{c.id}]]"
                    else:
                        yield from self.render_node(c)
                elif not (_is_url_tuple(c) or _is_supertag_tuple(c)):
                    # Skip rendered supertag assignment and URL tuples
                    yield from self.render_tuple(c)


# Root selection
def _collect_inline_refs(store: NodeStore) -> set[NodeId]:
    ids: set[NodeId] = set()
    for n in store.values():
        if n.name:
            ids.update(find_inline_node_refs(n.name))
    return ids


def _roots(store: NodeStore) -> list[BaseNode]:
    # nodes that *have* an owner (i.e. are children)
    owned_nodes = {n.id for n in store.values() if n.props.owner_id and not n.is_trash}

    childed = {cid for n in store.values() if not n.is_trash for cid in n.children}
    meta = {n.props.meta_node_id for n in store.values() if n.props.meta_node_id}
    inline = _collect_inline_refs(store)

    return sorted(
        [
            n
            for n in store.values()
            if (
                not n.is_trash
                and n.name  # ← NEW
                and n.children  # ← NEW
                and not _is_wrapper(n)  # ← NEW
                and not n.id.startswith("SYS_")  # drop system nodes
                and n.id not in owned_nodes  # exclude nodes that are owned
                and n.id not in childed  # referenced as child anywhere
                and n.id not in meta  # pure meta-nodes
                and n.id not in inline  # only inline-referenced
                and not isinstance(n, TupleNode)  # tuples never roots
            )
        ],
        key=lambda n: (n.props.created or 0),
    )


# ──────────────────────────  Exporters  ────────────────────────── #
def export_node_as_tanapaste(store: NodeStore, node: BaseNode) -> str:
    """Export a single node and its children as TanaPaste format."""
    lines: list[str] = []
    lines.append("%%tana%%")
    lines.extend(RenderContext(store, "tana").render_node(node))
    return "\n".join(lines).rstrip() + "\n"


def _export(store: NodeStore, style: str) -> str:
    lines: list[str] = []
    if style == "tana":
        lines.append("%%tana%%")
    ctx = RenderContext(store, style)
    for r in _roots(store):
        node_lines = list(ctx.render_node(r))

        if style == "md" and node_lines:
            # Transform first line from bullet to header
            hdr = node_lines[0]
            ttl: str = str(hdr.lstrip("- ").rstrip())
            lines.append(ttl)
            lines.append("=" * len(ttl))
            ctx.visited.remove(r.id)  # show owned children again
            for c in r.child_nodes:
                if not isinstance(c, TupleNode) and c.props.owner_id == r.id:
                    lines.extend(ctx.render_node(c))
        else:
            lines.extend(node_lines)

    return "\n".join(lines).rstrip() + "\n"


# ──────────────────────────  CLI  ────────────────────────── #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dump", help="Tana JSON dump")
    ap.add_argument(
        "-o",
        "--out-base",
        help="basename for outputs (default <dump>.converted)",
        default=None,
    )
    args = ap.parse_args()

    src = Path(args.dump)
    base = Path(args.out_base or src.with_suffix("").name + ".converted")

    store = NodeStore.from_file(src)

    for suffix, sty in ((".md", "md"), (".tanapaste.txt", "tana")):
        out_path = base.with_suffix(suffix)
        out_path.write_text(_export(store, sty), encoding="utf-8")
        print(f"✅ {sty} → {out_path}")


if __name__ == "__main__":
    main()
