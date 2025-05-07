
#!/usr/bin/env python3
"""tana2md.py — structured Tana JSON → Markdown

Highlights
-----------
* skips system/view/workspace shells
* a node becomes a *root file* when
    – it has *no parents* **or**
    – it contains a direct tuple that marks it with super‑tag  
      #day  #page  #issue  #event
* definition shells titled *Default* or *Calendar* are ignored
* leftovers, when MISC_MODE=1, go to `zzz_misc.md`
* buckets: files are written to `out/issue/`, `out/day/`, … automatically
* each file starts with `<!-- id: NODE_ID -->`
* SHOW_ID=1 shows ‹id› inline, LOG=DEBUG prints trace;
  DEBUG_NODE=<ID> dumps decisions for one node

Environment flags
-----------------
T2MD_MAX_DEPTH, LOG_INTERVAL, MIN_CHILDREN, STRICT_ROOTS, MISC_MODE
identical semantics to previous iterations.
"""

from __future__ import annotations
import argparse, json, os, pathlib, re, sys, time, logging
from dataclasses import dataclass
from typing import Any, Dict, List, Set

# ─── env ─────────────────────────────────────────────────────────────
SHOW_ID      = bool(int(os.getenv("SHOW_ID", "0")))
MAX_DEPTH    = int(os.getenv("T2MD_MAX_DEPTH", "100"))
LOG_INTERVAL = int(os.getenv("LOG_INTERVAL", "50000"))
MIN_CHILDREN = int(os.getenv("MIN_CHILDREN", "0"))
STRICT_ROOTS = bool(int(os.getenv("STRICT_ROOTS", "0")))
MISC_MODE    = bool(int(os.getenv("MISC_MODE", "0")))
DEBUG_NODE   = os.getenv("DEBUG_NODE")
logging.basicConfig(
    level=logging.DEBUG if os.getenv("LOG", "").upper()=="DEBUG" else logging.INFO,
    format="%(levelname)s %(message)s")

TAG_RE        = re.compile(r"<[^>]*>")
INLINE_REF_RE = re.compile(r'<span[^>]+data-inlineref-node="([^"]+)"[^>]*></span>')
SYSTEM_TYPES  = {
    "tagDef",
    "attributeDef",
    "field-definition",
    "workspace",
    "view",
    "viewDef",  # observed in real exports
}

# ─── Node / Graph ────────────────────────────────────────────────────
@dataclass
class Node:
    id: str
    raw: Dict[str,Any]
    graph: "Graph"

    @property
    def props(self)->Dict[str,Any]:
        return self.raw.get("props",{})

    @property
    def doc_type(self)->str|None:
        return self.props.get("_docType")

    @property
    def children_ids(self)->List[str]:
        return self.raw.get("children",[])

    @property
    def children(self)->List["Node"]:
        return [self.graph[c] for c in self.children_ids if c in self.graph]

    def title(self)->str:
        raw = (self.props.get("name") or
               self.raw.get("name") or
               self.props.get("text") or
               self.props.get("description") or "")
        def repl(m):
            rid=m.group(1)
            return f"[[{self.graph[rid].title() or rid}|{rid}]]"
        txt = INLINE_REF_RE.sub(repl, raw)
        txt = TAG_RE.sub("", txt).replace("\\n"," ").strip()
        return f"{txt} ‹{self.id}›" if SHOW_ID and txt else txt

    def debug(self,msg:str):
        if DEBUG_NODE and self.id==DEBUG_NODE:
            logging.debug(f"[{self.id}] {msg}")

    @property
    def is_system(self)->bool:
        return self.id.startswith("SYS_") or self.doc_type in SYSTEM_TYPES

class Graph(dict):
    def __init__(self, mapping:Dict[str,Any]):
        super().__init__({k:Node(k,v,self) for k,v in mapping.items()})

# ─── load helpers ────────────────────────────────────────────────────
def _from_list(lst:list)->Dict[str,Any]:
    return {n["id"]:n for n in lst if isinstance(n,dict) and "id" in n}

def detect_nodes(data:Any)->Dict[str,Any]:
    if isinstance(data,list): return _from_list(data)
    if not isinstance(data,dict): return {}
    if isinstance(data.get("docs"),list): return _from_list(data["docs"])
    n=data.get("nodes")
    if isinstance(n,list): return _from_list(n)
    if isinstance(n,dict): return {k:{"id":k,**v} for k,v in n.items() if isinstance(v,dict)}
    for v in data.values():
        if isinstance(v,list):
            m=_from_list(v)
            if m: return m
    return {}

def load_graph(path:pathlib.Path)->Graph:
    return Graph(detect_nodes(json.loads(path.read_text())))

# ─── tag helpers ────────────────────────────────────────────────────
def tag_defs(g:Graph)->Dict[str,str]:
    out={}
    for n in g.values():
        if n.doc_type=="tagDef":
            name=str(n.props.get("name","")) .lower()
            if name in {"day","page","issue","event"}:
                out[name]=n.id
    return out

def tuple_line(n:Node, g:Graph, tag_ids:Dict[str,str])->str:
    src=n.props.get("_sourceId")
    tag_name=next((k for k,v in tag_ids.items() if v==src),"tuple")
    vals=[c.title() for c in n.children if c.title()]
    txt=f"{tag_name}: {', '.join(vals)}" if vals else tag_name
    return f"{txt} ‹{n.id}›" if SHOW_ID else txt

def meta_lines(n:Node, g:Graph, tag_ids:Dict[str,str])->List[str]:
    mid=n.props.get("_metaNodeId")
    if not mid or mid not in g: return []
    meta=g[mid]
    out=[]
    for c in meta.children:
        if c.doc_type=="tuple": out.append(tuple_line(c,g,tag_ids))
        else:
            t=c.title()
            if t: out.append(t)
    return out

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
#
# Earlier versions of this script only looked at the direct children which
# meant that nodes tagged according to variant (2) were missed and therefore
# ended up in `zzz_misc.md`. We now consider **both** locations.


# We only consider tuples that explicitly modify the *Node supertags(s)*
# attribute. In real exports that attribute is materialised with id
# `SYS_A13`.  We check for the id either in the children list *or* (less
# frequently) in the `_sourceId` property.

def _discover_super_attr_ids(g: "Graph") -> set[str]:
    """Return ids of attributes named *Node supertags(s)* found in *g*."""
    ids = {
        n.id
        for n in g.values()
        if n.doc_type == "attributeDef" and str(n.props.get("name", "")).lower().startswith("node supertags")
    }
    # Fallback to the historical constant if nothing was found.
    return ids or {"SYS_A13"}


# will be initialised lazily the first time `_tuple_has_tag` is executed
SUPERTAG_ATTR_IDS: set[str] | None = None


def _tuple_has_tag(t: Node, tag_set: set[str]) -> bool:
    """Return *True* when *tuple* references any tag in *tag_set* **and** the
    tuple is attached to the *Node supertags(s)* attribute (id in
    ``SUPERTAG_ATTR_IDS``).
    """

    global SUPERTAG_ATTR_IDS

    if SUPERTAG_ATTR_IDS is None:
        SUPERTAG_ATTR_IDS = _discover_super_attr_ids(t.graph)

    if t.doc_type != "tuple":
        return False

    if not any(cid in tag_set for cid in t.children_ids):
        return False

    # The tuple *must* relate to the super-tag attribute.
    if t.props.get("_sourceId") in SUPERTAG_ATTR_IDS:
        return True
    if any(cid in SUPERTAG_ATTR_IDS for cid in t.children_ids):
        return True

    return False


def has_tag(n: Node, tag_set: set[str]) -> bool:
    """Detect whether *n* is marked with one of *tag_set*.

    We inspect both
      • direct tuple children and
      • tuple children of the optional meta-node.
    """

    # 1) direct tuple under the node itself
    for t in n.children:
        if _tuple_has_tag(t, tag_set):
            n.debug("tag via direct tuple " + t.id)
            return True

    # 2) tuple inside meta shell
    mid = n.props.get("_metaNodeId")
    if mid and mid in n.graph:
        meta = n.graph[mid]
        for t in meta.children:
            if _tuple_has_tag(t, tag_set):
                n.debug("tag via meta-tuple " + t.id)
                return True

    return False

def find_roots(g:Graph, tag_ids:Dict[str,str])->List[Node]:
    parents={cid for n in g.values() for cid in n.children_ids}
    tag_set=set(tag_ids.values())
    roots=[]
    for n in g.values():
        title=n.title()
        if n.is_system or n.doc_type=="search": continue
        if not title or title.lower() in {"default","calendar"}: continue
        non_tuple=[c for c in n.children if c.doc_type!="tuple"]
        if len(non_tuple)<MIN_CHILDREN: continue
        tagged=has_tag(n, tag_set)
        orphan=n.id not in parents
        root = (STRICT_ROOTS and tagged) or (not STRICT_ROOTS and (orphan or tagged))
        if root and tagged:
            roots.append(n)
            n.debug(f"ROOT orphan={orphan} tagged={tagged}")
        else:
            n.debug(f"skip orphan={orphan} tagged={tagged}")
    return roots

# ─── outline ----------------------------------------------------------------
def outline(
    node: Node,
    emitted: Set[str],
    tag_ids: Dict[str, str],
    depth: int = 0,
    root_ids: Set[str] | None = None,
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

    if node.id in emitted or depth > MAX_DEPTH:
        return []

    emitted.add(node.id)
    indent = "  " * depth
    lines: List[str] = []

    # ── tuple ────────────────────────────────────────────────────────────
    if node.doc_type == "tuple":
        lines.append(indent + "- " + tuple_line(node, node.graph, tag_ids))
        return lines

    # ── regular node ─────────────────────────────────────────────────────
    title = node.title()
    if title:
        lines.append(indent + "- " + title)

    # meta-information lines (tuples etc.)
    for ml in meta_lines(node, node.graph, tag_ids):
        lines.append(indent + "  - " + ml)

    for c in node.children:
        # Skip descending into children that are scheduled to become their own
        # Markdown roots. Still include the reference bullet so the link is
        # visible from the parent context.
        if root_ids and c.id in root_ids and c.id != node.id:
            t = c.title()
            if t:
                lines.append(indent + "  - " + t)
            continue

        lines.extend(outline(c, emitted, tag_ids, depth + 1, root_ids))

    return lines

def slugify(t:str,L:int=50)->str:
    return (re.sub(r"[^A-Za-z0-9\-]+","-",t).strip("-") or "untitled")[:L]

# ─── main ──────────────────────────────────────────────────────────
def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument("src",type=pathlib.Path)
    ap.add_argument("dst",type=pathlib.Path)
    ap.add_argument("--top",type=int)
    args=ap.parse_args(argv)

    g=load_graph(args.src)
    tag_ids=tag_defs(g)
    roots=find_roots(g,tag_ids)
    if args.top: roots=roots[:args.top]

    emitted: Set[str] = set()
    root_ids = {r.id for r in roots}
    misc=[]
    for idx,r in enumerate(roots,1):
        lines = outline(r, emitted, tag_ids, root_ids=root_ids)
        if not lines: continue
        # --- determine bucket (issue/day/page/event) --------------------------------
        bucket = None
        for name in ("issue", "day", "page", "event"):
            tid = tag_ids.get(name)
            if tid and has_tag(r, {tid}):
                bucket = name
                break
        target=args.dst/(bucket if bucket else "")
        target.mkdir(parents=True,exist_ok=True)
        path=target/f"{idx:03d}-{slugify(r.title())}.md"
        path.write_text(f"<!-- id: {r.id} -->\n"+"\n".join(lines)+"\n",encoding="utf-8")

    if MISC_MODE:
        for n in g.values():
            if n.id not in emitted and not n.is_system and n.children_ids:
                misc.extend(outline(n, emitted, tag_ids, root_ids=root_ids))
        if misc:
            (args.dst/"zzz_misc.md").write_text("\n".join(misc)+"\n",encoding="utf-8")

    logging.info("wrote %d root files%s", len(roots), " + misc" if misc else "")

if __name__=="__main__": main()
