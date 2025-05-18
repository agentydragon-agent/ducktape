#!/usr/bin/env python3
"""
convert.py – Convert Tana JSON dump to

* Markdown  →  <dump>.converted.md
* Tana-paste → <dump>.converted.tanapaste.txt
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


class Props(BaseModel, extra="forbid"):
    created: Optional[int] = None
    name: Optional[str] = None
    doc_type: Optional[str] = Field(alias="_docType", default=None)
    owner_id: Optional[str] = Field(alias="_ownerId", default=None)
    meta_node_id: Optional[str] = Field(alias="_metaNodeId", default=None)
    source_id: Optional[str] = Field(alias="_sourceId", default=None)
    done: Optional[int] = Field(alias="_done", default=None)
    description: Optional[str] = None # present in e.g. gc7H7gDG3Ce8

    # e.g.:
    # {
    #   "id": "iHWY3SmZFu2C",
    #   "children": [
    #     "7PbP1R_CV2x_",
    #     "JJB1UGrz2EgY",
    #     "IbyIc3t04g44",
    #     "BlKuPFBaBWGf"
    #   ],
    #   "props": {
    #     "_docType": "journalPart",
    #     "_flags": 64,
    #     "_metaNodeId": "0S3tjyvVLiOU",
    #     "_ownerId": "paAiLY7M-RDH",
    #     "created": 1745295053475,
    #     "name": "2025-04-21 - Monday"
    #   },
    #   "modifiedTs": [
    #     1745520191840
    #   ],
    #   "touchCounts": [
    #     13
    #   ]
    # }
    flags: Optional[int] = Field(alias="_flags", default=None)

    # e.g.:
    # {
    #   "id": "avLJUkTGxV00",
    #   "props": {
    #     "_docType": "visual",
    #     "_imageHeight": 500,
    #     "_imageWidth": 754,
    #     "_metaNodeId": "TMDjmbZiD6Vf",
    #     "_ownerId": "5bXtikRAjfQK",
    #     "created": 1721944839775
    #   },
    #   "modifiedTs": [1721944840187],
    #   "touchCounts": [7]
    # }
    imageWidth: Optional[int] = Field(alias="_imageWidth", default=None)
    imageHeight: Optional[int] = Field(alias="_imageHeight", default=None)

    # {
    #   "id": "oxIi6At72Q-R",
    #   "children": [
    #     "UcmDPW21ODoU"
    #   ],
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
    view: Optional[str] = Field(alias="_view", default=None)
    editMode: Optional[bool] = Field(alias="_editMode", default=None)

    # {
    #   "id": "kgqfA9Zxzr66",
    #   "props": {
    #     "created": 1732767570400,
    #     "_metaNodeId": "-AWjLEhOz2EW",
    #     "_ownerId": "uA_iLd0SUk_TRASH",
    #     "_sourceId": "hifkLFEEUc_J",
    #     "searchContextNode": "C0EsOmtaxwVG"
    #   },
    #   "touchCounts": [5],
    #   "modifiedTs": [1732767573651]
    # }
    searchContextNode: Optional[str] = None



    model_config = ConfigDict(extra="allow", frozen=True)

    @property
    def created_dt(self) -> Optional[datetime]:
        if self.created is None:
            return None
        return datetime.fromtimestamp(self.created / 1_000, tz=timezone.utc)

    @property
    def is_trash(self) -> bool:
        return bool(self.owner_id and self.owner_id.endswith("_TRASH"))


class BaseNode(BaseModel, extra="forbid"):
    id: str
    props: Props
    children: List[str] = Field(default_factory=list)
    modifiedTs: Optional[List[int]] = None
    touchCounts: Optional[List[int]] = None
    associationMap: Optional[Dict[str, str]] = None

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
    # There are some nodes with no _docType, e.g. hN3mU6IQqe.
    return _DOC_CLASS.get(raw["props"].get("_docType"), UnknownNode).model_validate(raw)


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
                out.setdefault(n.props.owner_id, []).append(v.name)
    return out


def attach_supertag_property(store: NodeStore) -> None:
    idx: Dict[str, List[str]] = _supertag_index(store)

    # NEW: propagate tags via meta-node link
    for n in store.values():
        if (meta := n.props.meta_node_id) and (meta in idx):
            tags_from_meta = idx[meta]
            tgt = idx.setdefault(n.id, [])
            for t in tags_from_meta:
                if t not in tgt:
                    tgt.append(t)

    # propagate wrapper tags to visible children
    for w in store.values():
        if _is_wrapper(w) and (tags := idx.get(w.id)):
            for cid in w.children:
                idx.setdefault(cid, [])
                for t in tags:
                    if t not in idx[cid]:
                        idx[cid].append(t)

    BaseNode.supertags = property(lambda self: idx.get(self.id, []))  # type: ignore[attr-defined]



# ──────────────────────────  Inline refs  ────────────────────────── #

_NODE_SPAN = re.compile(r'<span data-inlineref-node="([^"]+)"></span>')
_DATE_SPAN = re.compile(r'<span data-inlineref-date="([^"]+)"></span>')


def _inline_to_text(raw: str, store: NodeStore, style: str) -> str:
    def node_sub(m):
        nid = m.group(1)
        tgt = store.get(nid)
        nm  = html.unescape((tgt.name if tgt else nid) or nid)
        return f"[[{nm}^{nid}]]" if style == "tana" else nm

    def date_sub(m):
        data = json.loads(html.unescape(m.group(1)))
        iso  = f'{data["dateTimeString"]}[{data.get("timezone","")}]'
        return f"[[date:{iso}]]" if style == "tana" else iso

    # ── keep verbatim code / image lines ───────────────────────
    if raw.lstrip().startswith("```") or raw.lstrip().startswith("!"):
        return raw                                              # no substitutions
    # ───────────────────────────────────────────────────────────

    txt = _NODE_SPAN.sub(node_sub, raw)
    txt = _DATE_SPAN.sub(date_sub, txt)
    txt = html.unescape(txt)
    txt = re.sub(r"</?strong>", "**", txt, flags=re.IGNORECASE)
    return txt



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

def _is_wrapper(node: BaseNode) -> bool:
    """Nodes that should *not* get their own bullet - just pass through."""
    return node.props.doc_type in {"workspace", "viewDef", "layout"}



def _headline(node: BaseNode, store: NodeStore, style: str) -> str:
    raw = node.name or node.id
    if node.props.doc_type == "journalPart":
        raw = _journal_headline(raw) or raw

    base = _inline_to_text(raw, store, style)

    # ── NEW: description suffix ────────────────────────────────
    if node.props.description:
        desc = _inline_to_text(node.props.description, store, style)
        base = f"{base} - {desc}"

    # supertags
    tags = getattr(node, "supertags", [])
    if node.props.doc_type == "journalPart" and "day" not in tags:
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



# ──────────────────────────────────────────────────────────────
# Helper: return a scalar text representation of a node
#         or None if the node is actually a container.
# ──────────────────────────────────────────────────────────────
def _scalar_text(node: BaseNode, store: NodeStore, sty: str) -> str | None:
    # regular leaf: has its own name
    if node.name:
        return _inline_to_text(node.name, store, sty)

    # special case: a checkbox tuple
    for cid in node.children:
        tup = store.get(cid)
        if isinstance(tup, TupleNode) and len(tup.children) >= 2:
            key = store.get(tup.children[0])
            val = store.get(tup.children[1])
            if key and key.id == "SYS_A55" and val:
                return "[X]" if val.id == "SYS_V03" else "[ ]" if val.id == "SYS_V04" else None

    return None  # container, not a scalar


# ──────────────────────────────────────────────────────────────
# Tuple renderer
# ──────────────────────────────────────────────────────────────
def _render_tuple(t: TupleNode, store: NodeStore, vis: set[str],
                  write, ind: str, sty: str) -> None:
    # need at least key + value
    if len(t.children) < 2:
        return

    key_node = store.get(t.children[0])
    val_node = store.get(t.children[1])
    if not key_node or not val_node:
        return

    key_txt = _inline_to_text(key_node.name or key_node.id, store, sty)

    # ── try to render value inline ────────────────────────────
    val_txt = _scalar_text(val_node, store, sty)
    if val_txt is not None:
        write(f"{ind}- {key_txt}:: {val_txt}")

        # still render value-node children (e.g., URL, tags) one level deeper
        for cid in val_node.children:
            if child := store.get(cid):
                _render_node(child, store, vis, write, ind + "  ", sty)
        return

    # ── non-scalar: fall back to nested layout ────────────────
    write(f"{ind}- {key_txt}::")
    _render_node(val_node, store, vis, write, ind + "  ", sty)



def _render_node(
    n: BaseNode, store: NodeStore, vis: Set[str], write, ind: str, sty: str
):
    if _is_wrapper(n):
        for cid in n.children:
            if child := store.get(cid):
                _render_node(child, store, vis, write, ind, sty)
        return

    if n.id in vis:
        txt = _inline_to_text(n.name or n.id, store, sty)
        txt = f"[[{txt}^{n.id}]]" if sty == "tana" else txt
        write(f"{ind}- {txt}")
        return
    vis.add(n.id)
    write(f"{ind}- {_headline(n, store, sty)}")

    # tuples (skip supertag assignment)
    for cid in n.children:
        if (c := store.get(cid)) and isinstance(c, TupleNode) and not _is_supertag_tuple(c, store):
            _render_tuple(c, store, vis, write, ind + "  ", sty)

    # non-tuple owned children
    for cid in n.children:
        if (c := store.get(cid)) and not isinstance(c, TupleNode) and c.props.owner_id == n.id:
            _render_node(c, store, vis, write, ind + "  ", sty)


# ──────────────────────────  Root selection  ────────────────────────── #
def _collect_inline_refs(store: NodeStore) -> Set[str]:
    ids: Set[str] = set()
    for n in store.values():
        if n.name:
            ids.update(_NODE_SPAN.findall(n.name))
    return ids


def _roots(store: NodeStore) -> List[BaseNode]:
    # nodes that *have* an owner (i.e. are children)
    owned_nodes = {n.id for n in store.values() if n.props.owner_id and not n.is_trash}

    childed = {cid for n in store.values() if not n.is_trash for cid in n.children}
    meta    = {n.props.meta_node_id for n in store.values() if n.props.meta_node_id}
    inline  = _collect_inline_refs(store)

    return sorted(
        [
            n
            for n in store.values()
            if (
                not n.is_trash
                and n.name                                   # ← NEW
                and n.children                               # ← NEW
                and not _is_wrapper(n)            # ← NEW
                and not n.id.startswith("SYS_")   # drop system nodes
                and n.id not in owned_nodes       # exclude nodes that are owned
                and n.id not in childed           # referenced as child anywhere
                and n.id not in meta              # pure meta-nodes
                and n.id not in inline            # only inline-referenced
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
                if c and not isinstance(c, TupleNode) and c.props.owner_id == r.id:
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
