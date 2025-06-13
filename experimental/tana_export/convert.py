#!/usr/bin/env python3
"""
convert.py - Convert Tana JSON dump to

* Markdown  →  <dump>.converted.md
* Tana-paste → <dump>.converted.tanapaste.txt
"""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import defaultdict
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Props(BaseModel):
    created: int | None = None
    name: str | None = None
    doc_type: str | None = Field(alias="_docType", default=None)
    owner_id: str | None = Field(alias="_ownerId", default=None)
    meta_node_id: str | None = Field(alias="_metaNodeId", default=None)
    source_id: str | None = Field(alias="_sourceId", default=None)
    done: int | None = Field(alias="_done", default=None)
    description: str | None = None  # present in e.g. gc7H7gDG3Ce8
    flags: int | None = Field(alias="_flags", default=None)
    image_width: int | None = Field(alias="_imageWidth", default=None)
    image_height: int | None = Field(alias="_imageHeight", default=None)
    published: int | None = Field(alias="_published", default=None)

    # {
    #   "id": "oxIi6At72Q-R",
    #   "children": ["UcmDPW21ODoU"],
    #   "props": {
    #     "_docType": "viewDef",
    #     "_editMode": true,
    #     "_ownerId": "tucdPrxIajt5",
    #     "_view": "table",
    #     "created": 1701150010598,
    #     "name": "Default"
    #   },
    #   "modifiedTs": [1701150011150],
    #   "touchCounts": [9]
    # }
    view: str | None = Field(alias="_view", default=None)
    edit_mode: bool | None = Field(alias="_editMode", default=None)
    search_context_node: str | None = Field(alias="searchContextNode", default=None)

    model_config = ConfigDict(extra="forbid", frozen=True)

    @property
    def created_dt(self) -> datetime | None:
        if self.created is None:
            return None
        return datetime.fromtimestamp(self.created / 1_000, tz=timezone.utc)

    @property
    def is_trash(self) -> bool:
        return bool(self.owner_id and self.owner_id.endswith("_TRASH"))


class BaseNode(BaseModel):
    id: str
    props: Props
    children: list[str] = Field(default_factory=list)
    modified_ts: list[int] | None = Field(alias="modifiedTs", default=None)
    touch_counts: list[int] | None = Field(alias="touchCounts", default=None)
    association_map: dict[str, str] | None = Field(alias="associationMap", default=None)
    _store: NodeStore | None = None

    model_config = ConfigDict(extra="allow", frozen=True, arbitrary_types_allowed=True)

    @property
    def name(self) -> str | None:  # type: ignore[override]
        return self.props.name

    @property
    def is_trash(self) -> bool:
        return self.props.is_trash

    @property
    def child_nodes(self) -> list[BaseNode]:
        """Return children as node instances."""
        if not self._store:
            return []
        return [self._store[cid] for cid in self.children if cid in self._store]


class TupleNode(BaseNode): ...


class TagDefNode(BaseNode): ...


class UnknownNode(BaseNode): ...


_DOC_CLASS: Mapping[str | None, type[BaseNode]] = {
    "tuple": TupleNode,
    "tagDef": TagDefNode,
    None: UnknownNode,
}


class NodeStore(Mapping[str, BaseNode]):
    def __init__(self, mapping: Mapping[str, BaseNode]):
        self._m = dict(mapping)
        # Set store reference on each node
        for node in self._m.values():
            # Use object.__setattr__ to set on frozen model
            object.__setattr__(node, "_store", self)

    # mapping protocol (read-only)
    def __getitem__(self, k):
        return self._m[k]

    def __iter__(self):
        return iter(self._m)

    def __len__(self):
        return len(self._m)

    @classmethod
    def from_file(cls, path: Path):
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)

        def _make_node(raw: dict[str, Any]) -> BaseNode:
            # There are some nodes with no _docType, e.g. hN3mU6IQqe.
            return _DOC_CLASS.get(
                raw["props"].get("_docType"),
                UnknownNode,
            ).model_validate(raw)

        return cls({n.id: n for n in (_make_node(doc) for doc in data["docs"])})


# ──────────────────────────  Supertag view  ────────────────────────── #

_SUPERTAG_KEY_ID = "SYS_A13"  # “Node supertags(s)”
_URL_KEY_ID = "SYS_A78"  # “URL”


def attach_supertag_property(store: NodeStore) -> None:
    idx: defaultdict[str, list[str]] = defaultdict(list)

    def _add(id, tags):
        for tag in tags:
            if tag and tag not in idx[id]:
                idx[id].append(tag)

    for n in store.values():
        if not (
            isinstance(n, TupleNode)
            and len(n.children) >= 2
            and n.props.owner_id
            and (key_node := store.get(n.children[0]))
            and key_node.id == _SUPERTAG_KEY_ID
        ):
            continue
        # Handle multi-value tuples - all children after the key are tag values
        for v in n.child_nodes[1:]:
            if v.name:
                idx[n.props.owner_id].append(v.name)

    # NEW: propagate tags via meta-node link
    for n in store.values():
        if n.props.meta_node_id:
            _add(n.id, idx[n.props.meta_node_id])

    # propagate wrapper tags to visible children
    for w in store.values():
        if _is_wrapper(w):
            for cid in w.children:
                _add(cid, idx[w.id])

    BaseNode.supertags = property(lambda self: idx[self.id])  # type: ignore[attr-defined]


# ──────────────────────────  Inline refs  ────────────────────────── #

_NODE_SPAN = re.compile(r'<span data-inlineref-node="([^"]+)"></span>')
_DATE_SPAN = re.compile(r'<span data-inlineref-date="([^"]+)"></span>')


class HTMLToMarkdownParser(HTMLParser):
    """Convert HTML formatting to Markdown syntax."""

    def __init__(self):
        super().__init__()
        self.output = StringIO()
        self.tag_stack = []

    def handle_starttag(self, tag, attrs):
        self.tag_stack.append(tag)
        if tag in ("b", "strong"):
            self.output.write("**")
        elif tag in ("i", "em"):
            self.output.write("_")
        elif tag == "u":
            self.output.write("__")
        elif tag == "mark":
            self.output.write("<mark>")
        elif tag == "strike":
            self.output.write("<strike>")
        elif tag == "code":
            self.output.write("<code>")

    def handle_endtag(self, tag):
        if self.tag_stack and self.tag_stack[-1] == tag:
            self.tag_stack.pop()
        if tag in ("b", "strong"):
            self.output.write("**")
        elif tag in ("i", "em"):
            self.output.write("_")
        elif tag == "u":
            self.output.write("__")
        elif tag == "mark":
            self.output.write("</mark>")
        elif tag == "strike":
            self.output.write("</strike>")
        elif tag == "code":
            self.output.write("</code>")

    def handle_data(self, data):
        self.output.write(data)

    def get_markdown(self):
        return self.output.getvalue()


def _get_tuple_value(node: BaseNode, key_id: str) -> BaseNode | None:
    """Get the value node for a specific key from a node's tuple children."""
    for child in node.child_nodes:
        if isinstance(child, TupleNode) and len(child.child_nodes) >= 2:
            key_node, val_node = child.child_nodes[:2]
            if key_node.id == key_id:
                return val_node
    return None


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
    return len(t.children) > 0 and t.children[0] == _SUPERTAG_KEY_ID


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
        if node.id == "SYS_V03":
            return "[X] "  # Note: trailing space for consistency with expected output
        if node.id == "SYS_V04":
            return "[ ]"

        # regular leaf: has its own name and no children (except for special tuples)
        if node.name and not node.children:
            return self._inline_to_text(node.name)

        # special case: a checkbox tuple
        if val := _get_tuple_value(node, "SYS_A55"):
            return self._scalar_text(val)

        return None  # container, not a scalar

    def _get_image_url(self, node: BaseNode) -> str | None:
        """Extract image URL from a visual node's metadata."""
        if (
            node.props.doc_type != "visual"
            or not node.props.meta_node_id
            or not (metanode := self.store.get(node.props.meta_node_id))
        ):
            return None

        # Look for media tuple in metanode children
        if val_node := _get_tuple_value(metanode, "SYS_T15"):
            return val_node.name

        return None

    def _inline_to_text(self, raw: str) -> str:
        def node_sub(m):
            nid = m.group(1)
            tgt = self.store.get(nid)
            nm = html.unescape((tgt.name if tgt else nid) or nid)
            return f"[[{nm}^{nid}]]" if self.style == "tana" else nm

        def date_sub(m):
            data = json.loads(html.unescape(m.group(1)))
            date_str = data["dateTimeString"]
            timezone = data.get("timezone", "")

            # Check if it's a date-only value (no time component)
            # Date-only formats: YYYY, YYYY-MM, YYYY-MM-DD, YYYY-Www
            if "T" not in date_str and "/" not in date_str:
                # Date-only values don't include timezone
                iso = date_str
            elif "/" in date_str and timezone:
                # Date range - need to add timezone to each date
                dates = date_str.split("/")
                iso = f"{dates[0]}[{timezone}]/{dates[1]}[{timezone}]"
            else:
                # Single DateTime value
                iso = f"{date_str}[{timezone}]" if timezone else date_str

            return f"[[date:{iso}]]" if self.style == "tana" else iso

        # keep verbatim code / image lines
        if raw.lstrip().startswith("```") or raw.lstrip().startswith("!"):
            return raw  # no substitutions

        txt = _NODE_SPAN.sub(node_sub, raw)
        txt = _DATE_SPAN.sub(date_sub, txt)

        # Convert HTML formatting to markdown for tana style
        if self.style == "tana":
            parser = HTMLToMarkdownParser()
            parser.feed(txt)
            return parser.get_markdown()
        return html.unescape(txt)

    @contextmanager
    def add_indent(self, n: int):
        """Context manager to temporarily add indentation."""
        old_indent = self.indent
        self.indent += " " * n
        try:
            yield
        finally:
            self.indent = old_indent

    def _headline(self, node: BaseNode) -> str:
        raw = node.name or node.id
        if node.props.doc_type == "journalPart":
            raw = _journal_headline(raw)

        base = self._inline_to_text(raw)

        # ── NEW: description suffix ────────────────────────────────
        if node.props.description:
            base += " - " + self._inline_to_text(node.props.description)

        # supertags
        tags = getattr(node, "supertags", [])
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
        if len(t.children) < 2 or not (key_node := self.store.get(t.children[0])):
            return
        prefix = (
            f"{self.indent}- {self._inline_to_text(key_node.name or key_node.id)}:: "
        )

        # Handle multi-value tuples (more than 2 children)
        if len(t.children) > 2:
            # All children after the first are values
            yield prefix
            for val_node in t.child_nodes[1:]:
                # For tana style, render as reference if the value is not owned by this tuple
                # (i.e., it's a reference to an existing node)
                with self.add_indent(2):
                    if (
                        self.style == "tana"
                        and val_node.name
                        and val_node.props.owner_id != t.id
                    ):
                        yield f"{self.indent}- [[{self._inline_to_text(val_node.name)}^{val_node.id}]]"
                    else:
                        yield from self.render_node(val_node)
            return

        if len(t.child_nodes) < 2:
            return
        # Binary tuple (key + single value)
        val_node = t.child_nodes[1]

        # try to render value inline
        if (val_txt := self._scalar_text(val_node)) is not None:
            # Add trailing space for consistency with expected output
            yield prefix + val_txt
            # still render value-node children (e.g., URL, tags) one level deeper
            with self.add_indent(2):
                for child in val_node.child_nodes:
                    yield from self.render_node(child)
            return

        # ── non-scalar: fall back to nested layout ────────────────
        # Check if this is an empty value node (no name, no children)
        # Common for unset checkbox attributes
        yield prefix
        with self.add_indent(2):
            if val_node.name or val_node.children:
                yield from self.render_node(val_node)

    def render_node(self, n: BaseNode):
        if _is_wrapper(n):
            for child in n.child_nodes:
                yield from self.render_node(child)
            return

        # Special handling for visual (image) nodes
        if n.props.doc_type == "visual" and (url := self._get_image_url(n)):
            # Use the visual node's name as caption if it has one
            caption = self._inline_to_text(n.name) if n.name else ""
            yield f"{self.indent}-  ![{caption}]({url}) "
            return

        # Special handling for code blocks
        if n.props.doc_type == "codeblock" and self.style == "tana":
            # Find language from tuple
            language = (
                lang_node.name if (lang_node := _get_tuple_value(n, "SYS_A70")) else ""
            )

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
            if (
                isinstance(c, TupleNode)
                and not _is_supertag_tuple(c)
                and len(c.children) >= 1
                and (key_node := self.store.get(c.children[0]))
                and key_node.id == _URL_KEY_ID
            ):
                with self.add_indent(2):
                    yield from self.render_tuple(c)

        # Check if this node has an associationMap - if so, render children as references with associated data
        with self.add_indent(2):
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
                    with self.add_indent(2):
                        # Render associated data if exists
                        yield f"{self.indent}- **Associated data**"
                        # Render tuples from the associated data node
                        with self.add_indent(2):
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
                elif not (
                    len(c.children) >= 1
                    and c.children[0] in (_URL_KEY_ID, _SUPERTAG_KEY_ID)
                ):
                    # Skip rendered supertag assignment and URL tuples
                    yield from self.render_tuple(c)


# Root selection
def _collect_inline_refs(store: NodeStore) -> set[str]:
    ids: set[str] = set()
    for n in store.values():
        if n.name:
            ids.update(_NODE_SPAN.findall(n.name))
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
    return "\n".join(lines).rstrip() + "\n\n"


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
            ttl = hdr.lstrip("- ").rstrip()
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
    attach_supertag_property(store)

    for suffix, sty in ((".md", "md"), (".tanapaste.txt", "tana")):
        out_path = base.with_suffix(suffix)
        out_path.write_text(_export(store, sty), encoding="utf-8")
        print(f"✅ {sty} → {out_path}")


if __name__ == "__main__":
    main()
