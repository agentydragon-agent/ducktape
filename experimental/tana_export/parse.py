# tana_models.py  –  fixed version (Pydantic v2)

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, MutableMapping, Optional

from pydantic import BaseModel, ConfigDict, Field

# ──────────────────────────  core helpers  ────────────────────────── #

class Props(BaseModel):
    """Raw props with convenience accessors (read-only)."""
    # -- Pydantic will ignore unknown fields thanks to extra="allow" --
    created: Optional[int] = None
    name:    Optional[str] = None
    description: Optional[str] = None
    _docType:   Optional[str] = None
    _ownerId:   Optional[str] = None
    _metaNodeId: Optional[str] = None
    _sourceId:  Optional[str] = None

    model_config = ConfigDict(extra="allow", frozen=True)

    # convenience
    @property
    def created_dt(self) -> Optional[datetime]:
        return (None if self.created is None
                else datetime.fromtimestamp(self.created / 1_000,
                                             tz=timezone.utc))

    @property
    def is_trash(self) -> bool:
        return bool(self._ownerId and self._ownerId.endswith("_TRASH"))


class BaseNode(BaseModel):
    """Any node in a Tana export."""
    id: str
    props: Props
    children: List[str] = Field(default_factory=list)
    touchCounts: List[int] = Field(default_factory=list)
    modifiedTs: List[int] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow", frozen=True)

    # shortcuts
    @property
    def name(self) -> Optional[str]:      # type: ignore[override]
        return self.props.name

    @property
    def created(self) -> Optional[datetime]:
        return self.props.created_dt

    @property
    def is_trash(self) -> bool:
        return self.props.is_trash

    def resolve_children(self, store: "NodeStore") -> List["BaseNode"]:
        return [store[c] for c in self.children if c in store]


# ─────────────── specialised flavours  ─────────────── #

class TupleNode(BaseNode):
    @property
    def key(self) -> Optional[str]:
        return self.children[0] if self.children else None

    @property
    def value_id(self) -> Optional[str]:
        return self.children[1] if len(self.children) >= 2 else None


class TagDefNode(BaseNode):
    @property
    def tag_name(self) -> str:
        if self.props.name is None:
            raise ValueError("tagDef missing name")
        return self.props.name


class UnknownNode(BaseNode):
    pass


# docType → subclass
_doc_type_registry: Mapping[Optional[str], type[BaseNode]] = {
    "tuple": TupleNode,
    "tagDef": TagDefNode,
    None: UnknownNode,
}


def _node_factory(raw: Dict[str, Any]) -> BaseNode:
    """Build node without mutating frozen props."""
    # inject id into the *props dict* before model validation
    props_fixed = {**raw.get("props", {}), "id": raw["id"]}
    doc_type = props_fixed.get("_docType")
    cls = _doc_type_registry.get(doc_type, UnknownNode)
    return cls.model_validate({**raw, "props": props_fixed})


# ─────────────── container / loader ─────────────── #

class NodeStore(MutableMapping[str, BaseNode]):
    """Dict-like store with helpers."""

    def __init__(self, nodes: Mapping[str, BaseNode]) -> None:
        self._nodes = dict(nodes)

    # mapping interface (read-only)
    def __getitem__(self, k): return self._nodes[k]
    def __iter__(self):       return iter(self._nodes)
    def __len__(self):        return len(self._nodes)
    def __setitem__(self, k, v): raise TypeError("read-only")
    def __delitem__(self, k):   raise TypeError("read-only")

    # ─────────────────────────────────────────────────────────────── #
    #  loader
    # ─────────────────────────────────────────────────────────────── #
    @classmethod
    def from_file(cls, path: str) -> "NodeStore":
        import random  # (local import keeps global namespace tidy)
        import traceback

        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)

        bad: list[tuple[str, dict[str, Any], BaseException, str]] = []
        nodes: Dict[str, BaseNode] = {}

        for doc in data.get("docs", []):
            try:
                node = _node_factory(doc)
                nodes[node.id] = node
            except Exception as exc:          # capture *everything*
                tb = "".join(traceback.format_exception(exc))
                bad.append((doc.get("id", "<none>"), doc, exc, tb))

        # -------- report failures (sample ≤5) -------
        if bad:
            sample = random.sample(bad, k=min(5, len(bad)))
            print(f"⚠  {len(bad)} node(s) failed to parse – showing {len(sample)}:")
            for nid, blob, exc, tb in sample:
                print(f"\n─── id: {nid} ──────────────────────────────────────────")
                print(json.dumps(blob, indent=2, ensure_ascii=False))
                print("Traceback:")
                print(tb.rstrip())

        return cls(nodes)

    # extras
    def get_tagdefs(self) -> List[TagDefNode]:
        return [n for n in self._nodes.values() if isinstance(n, TagDefNode)]


# ─────────────── optional: supertag helper ─────────────── #

def _collect_supertags(store: NodeStore) -> Dict[str, List[str]]:
    TAG_KEY_IDS = {"SYS_A13"}
    idx: Dict[str, List[str]] = {}
    for n in store.values():
        if isinstance(n, TupleNode) and n.key in TAG_KEY_IDS:
            owner = n.props._ownerId
            tag_node = store.get(n.value_id) if n.value_id else None
            if owner and tag_node and tag_node.name:
                idx.setdefault(owner, []).append(tag_node.name)
    return idx


def attach_supertag_view(store: NodeStore) -> None:
    tag_map = _collect_supertags(store)
    BaseNode.supertags = property(lambda self: tag_map.get(self.id, []))  # type: ignore[attr-defined]


# ─────────────── demo ─────────────── #

if __name__ == "__main__":
    import sys
    store = NodeStore.from_file(sys.argv[1])
    attach_supertag_view(store)
    print(f"Loaded {len(store):,} nodes, {len(store.get_tagdefs()):,} supertags.")

