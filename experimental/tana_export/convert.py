#!/usr/bin/env python3
"""
tana_export.py – Convert a raw **Tana JSON dump** to

* Markdown  →  <dump>.converted.md
* Tana-paste → <dump>.converted.tanapaste.txt

Features
========
✓  Pydantic v2, frozen read-only models
✓  ≤ 5 random validation failures printed with full JSON + traceback
✓  Drops trash nodes *and* all top-level system nodes (`SYS_*`)
✓  Suppresses the special “Node supertags(s)” tuple in body (but keeps #tags in headline)
✓  Handles inline `<span data-inlineref-node>` / `…-date` → links / ISO strings
✓  Prevents nodes referenced **only inline** from becoming stray top-level bullets
✓  Renders ordinary tuples as

        - Key::
          - <value subtree>

✓  Pretty “journal day” headings:
        "2025-05-06 - Tuesday"  →  "Tue, May 6 #day"

"""

from __future__ import annotations

import argparse
import html
import json
import random
import re
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set

from pydantic import BaseModel, ConfigDict, Field


class Props(BaseModel):
    created: Optional[int] = None
    name: Optional[str] = None
    _docType: str
    _ownerId: str
    # _ownerId: Optional[str] = None
    _metaNodeId: Optional[str] = None
    _sourceId: Optional[str] = None

    model_config = ConfigDict(extra="allow", frozen=True)

    @property
    def created_dt(self) -> Optional[datetime]:
        if self.created is None:
            return None
        return datetime.fromtimestamp(self.created / 1_000, tz=timezone.utc)

    @property
    def is_trash(self) -> bool:
        return bool(self._ownerId and self._ownerId.endswith("_TRASH"))


class BaseNode(BaseModel):
    id: str
    props: Props
    children: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow", frozen=True)

    @property
    def name(self) -> Optional[str]:  # type: ignore[override]
        return self.props.name

    @property
    def is_trash(self) -> bool:
        return self.props.is_trash


class TupleNode(BaseNode): ...


class TagDefNode(BaseNode): ...


class UnknownNode(BaseNode): ...


_DOC_CLASS: Mapping[Optional[str], type[BaseNode]] = {
    "tuple": TupleNode,
    "tagDef": TagDefNode,
    None: UnknownNode,
}


def _make_node(raw: Dict[str, Any]) -> BaseNode:
    return _DOC_CLASS.get(raw["props"]["_docType"], UnknownNode).model_validate(raw)


class NodeStore(Mapping[str, BaseNode]):
    def __init__(self, mapping: Mapping[str, BaseNode]):
        self._m = dict(mapping)

    # mapping protocol (read-only)
    def __getitem__(self, k):
        return self._m[k]

    def __iter__(self):
        return iter(self._m)

    def __len__(self):
        return len(self._m)

    @classmethod
    def from_file(cls, path: Path):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)

        ok, bad = {}, []
        for doc in data["docs"]:
            try:
                n = _make_node(doc)
                ok[n.id] = n
            except Exception as exc:
                bad.append(
                    (
                        doc.get("id", "<none>"),
                        doc,
                        "".join(traceback.format_exception(exc)),
                    )
                )
        if bad:
            print(f"⚠  {len(bad)} node(s) failed – showing {min(5,len(bad))}:")
            for nid, blob, tb in random.sample(bad, min(5, len(bad))):
                print(f"\n── id: {nid} ──")
                print(json.dumps(blob, indent=2, ensure_ascii=False))
                print(tb)
        return cls(ok)


# ──────────────────────────  Supertag view  ────────────────────────── #

_SUPERTAG_KEY_ID = "SYS_A13"  # “Node supertags(s)”


def _supertag_index(store: NodeStore) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for n in store.values():
        if isinstance(n, TupleNode) and len(n.children) >= 2:
            k, v = store.get(n.children[0]), store.get(n.children[1])
            if k and k.id == _SUPERTAG_KEY_ID and v and v.name:
                out.setdefault(n.props._ownerId, []).append(v.name)
    return out


def attach_supertag_property(store: NodeStore):
    idx = _supertag_index(store)
    BaseNode.supertags = property(lambda self: idx.get(self.id, []))  # type: ignore[attr-defined]


# ──────────────────────────  Inline refs  ────────────────────────── #

_NODE_SPAN = re.compile(r'<span data-inlineref-node="([^"]+)"></span>')
_DATE_SPAN = re.compile(r'<span data-inlineref-date="([^"]+)"></span>')


def _inline_to_text(raw: str, store: NodeStore, style: str) -> str:
    def node_sub(m):
        nid = m.group(1)
        target = store.get(nid)
        nm = html.unescape((target.name if target else nid) or nid)
        return f"[[{nm}^{nid}]]" if style == "tana" else nm

    def date_sub(m):
        data = json.loads(html.unescape(m.group(1)))
        iso = f'{data["dateTimeString"]}[{data.get("timezone","")}]'
        return f"[[date:{iso}]]" if style == "tana" else iso

    txt = _NODE_SPAN.sub(node_sub, raw)
    txt = _DATE_SPAN.sub(date_sub, txt)
    return html.unescape(txt)


# ──────────────────────────  Headline  ────────────────────────── #


def _journal_headline(name: str) -> str | None:
    # pattern: YYYY-MM-DD - Weekday
    try:
        date_str = name.split(" ")[0]  # "2025-05-06"
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        # TODO: detect day more robustly
        return dt.strftime("%a, %b %-d")  # "Tue, May 6"
    except Exception:
        return None


def _headline(node: BaseNode, store: NodeStore, style: str) -> str:
    raw = node.name or node.id
    if node.props._docType == "journalPart":
        if pretty := _journal_headline(raw):
            raw = pretty
    base = _inline_to_text(raw, store, style)

    # supertags
    tags = getattr(node, "supertags", [])
    # journal day gets #day automatically if not already tagged
    if node.props._docType == "journalPart" and "day" not in tags:
        tags.append("day")
    if tags:
        base += " " + " ".join(f"#{t}" for t in tags)
    return base


# ──────────────────────────  Rendering  ────────────────────────── #


def _is_supertag_tuple(t: TupleNode, store: NodeStore) -> bool:
    if not t.children:
        return False
    if not (k := store.get(t.children[0])):
        return False
    return k.id == _SUPERTAG_KEY_ID


def _render_tuple(
    t: TupleNode, store: NodeStore, vis: Set[str], write, ind: str, sty: str
):
    if len(t.children) < 2:
        return
    key, val = store.get(t.children[0]), store.get(t.children[1])
    if not key or not val:
        return
    write(f"{ind}- {_inline_to_text(key.name or key.id, store, sty)}::")
    _render_node(val, store, vis, write, ind + "  ", sty)


def _render_node(
    n: BaseNode, store: NodeStore, vis: Set[str], write, ind: str, sty: str
):
    if n.id in vis:
        txt = _inline_to_text(n.name or n.id, store, sty)
        txt = f"[[{txt}^{n.id}]]" if sty == "tana" else txt
        write(f"{ind}- {txt}")
        return
    vis.add(n.id)
    write(f"{ind}- {_headline(n, store, sty)}")

    # tuples (skip supertag assignment)
    for cid in n.children:
        c = store[cid]
        if isinstance(c, TupleNode) and not _is_supertag_tuple(c, store):
            _render_tuple(c, store, vis, write, ind + "  ", sty)

    # non-tuple owned children
    for cid in n.children:
        c = store[cid]
        if c and not isinstance(c, TupleNode) and c.props._ownerId == n.id:
            _render_node(c, store, vis, write, ind + "  ", sty)


# ──────────────────────────  Root selection  ────────────────────────── #
def _collect_inline_refs(store: NodeStore) -> Set[str]:
    ids: Set[str] = set()
    for n in store.values():
        if n.name:
            ids.update(_NODE_SPAN.findall(n.name))
    return ids


def _roots(store: NodeStore) -> List[BaseNode]:
    owned = {
        n.props._ownerId for n in store.values() if n.props._ownerId and not n.is_trash
    }
    childed = {cid for n in store.values() if not n.is_trash for cid in n.children}
    meta = {n.props._metaNodeId for n in store.values() if n.props._metaNodeId}
    inline = _collect_inline_refs(store)

    return sorted(
        [
            n
            for n in store.values()
            if (
                not n.is_trash
                and not n.id.startswith("SYS_")  # drop system
                and n.id not in owned  # owned by someone?
                and n.id not in childed  # listed as child?
                and n.id not in meta  # ← exclude pure meta‑nodes
                and n.id not in inline  # only referenced inline?
                and not isinstance(n, TupleNode)  # tuples never roots
            )
        ],
        key=lambda n: (n.props.created or 0),
    )


# ──────────────────────────  Exporters  ────────────────────────── #
def _export(store: NodeStore, style: str) -> str:
    lines: List[str] = []
    if style == "tana":
        lines.append("%%tana%%")
    vis: Set[str] = set()
    write = lines.append

    for r in _roots(store):
        _render_node(r, store, vis, write, "" if style == "tana" else "", style)

        if style == "md":
            hdr = lines.pop()
            ttl = hdr.lstrip("- ").rstrip()
            lines.append(ttl)
            lines.append("=" * len(ttl))
            vis.remove(r.id)  # show owned children again
            for cid in r.children:
                c = store.get(cid)
                if c and not isinstance(c, TupleNode) and c.props._ownerId == r.id:
                    _render_node(c, store, vis, write, "", style)

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
