"""
Core data models for working with Tana JSON dumps.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .types import NodeId


class Props(BaseModel):
    created: int | None = None
    name: str | None = None
    doc_type: str | None = Field(alias="_docType", default=None)
    owner_id: NodeId | None = Field(alias="_ownerId", default=None)
    meta_node_id: NodeId | None = Field(alias="_metaNodeId", default=None)
    source_id: NodeId | None = Field(alias="_sourceId", default=None)
    done: int | None = Field(alias="_done", default=None)
    description: str | None = None  # present in e.g. gc7H7gDG3Ce8
    flags: int | None = Field(alias="_flags", default=None)
    image_width: int | None = Field(alias="_imageWidth", default=None)
    image_height: int | None = Field(alias="_imageHeight", default=None)
    published: int | None = Field(alias="_published", default=None)
    view: str | None = Field(alias="_view", default=None)
    edit_mode: bool | None = Field(alias="_editMode", default=None)
    search_context_node: str | None = Field(alias="searchContextNode", default=None)

    model_config = ConfigDict(extra="forbid", frozen=True)

    @property
    def created_dt(self) -> datetime | None:
        if self.created is None:
            return None
        return datetime.fromtimestamp(self.created / 1_000, tz=UTC)

    @property
    def is_trash(self) -> bool:
        return bool(self.owner_id and self.owner_id.endswith("_TRASH"))


class BaseNode(BaseModel):
    id: NodeId
    props: Props
    children: list[NodeId] = Field(default_factory=list)
    modified_ts: list[int] | None = Field(alias="modifiedTs", default=None)
    touch_counts: list[int] | None = Field(alias="touchCounts", default=None)
    association_map: dict[NodeId, NodeId] | None = Field(
        alias="associationMap",
        default=None,
    )
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
            raise RuntimeError("Node not attached to a store")
        return [self._store[cid] for cid in self.children if cid in self._store]


class TupleNode(BaseNode): ...


class TagDefNode(BaseNode): ...


class VisualNode(BaseNode):
    """Node representing visual content (images)."""

    def get_image_url(self) -> str | None:
        """Extract image URL from visual node's metadata."""
        if not self._store:
            raise RuntimeError("Node not attached to a store")

        if not self.props.meta_node_id:
            return None

        metanode = self._store.get(self.props.meta_node_id)
        if not metanode:
            return None

        # Look for media tuple in metanode children
        # Import here to avoid circular dependency
        from .constants import MEDIA_KEY_ID
        from .query import get_tuple_value

        if val_node := get_tuple_value(metanode, MEDIA_KEY_ID):
            return val_node.name

        return None


class CodeBlockNode(BaseNode):
    """Node representing a code block."""

    def get_language(self) -> str:
        """Get the programming language of the code block."""
        if not self._store:
            raise RuntimeError("Node not attached to a store")

        # Import here to avoid circular dependency
        from .constants import LANGUAGE_KEY_ID
        from .query import get_tuple_value

        if lang_node := get_tuple_value(self, LANGUAGE_KEY_ID):
            return lang_node.name or ""

        return ""


class UnknownNode(BaseNode): ...


_DOC_CLASS: Mapping[str | None, type[BaseNode]] = {
    "tuple": TupleNode,
    "tagDef": TagDefNode,
    "visual": VisualNode,
    "codeblock": CodeBlockNode,
    None: UnknownNode,
}


class NodeStore(Mapping[NodeId, BaseNode]):
    def __init__(self, mapping: Mapping[NodeId, BaseNode]):
        self._m = dict(mapping)
        self._supertag_index: dict[NodeId, list[str]] = {}
        # Set store reference on each node
        for node in self._m.values():
            # Use object.__setattr__ to set on frozen model
            object.__setattr__(node, "_store", self)
        # Build supertag index
        self._build_supertag_index()

    # mapping protocol (read-only)
    def __getitem__(self, k: NodeId) -> BaseNode:
        return self._m[k]

    def __iter__(self):
        return iter(self._m)

    def __len__(self):
        return len(self._m)

    def get_supertags(self, node_id: NodeId) -> list[str]:
        """Get all supertags for a node."""
        return self._supertag_index.get(node_id, [])

    def has_supertag(self, node_id: NodeId, tag: str) -> bool:
        """Check if a node has a specific supertag."""
        return tag in self._supertag_index.get(node_id, [])

    def _build_supertag_index(self) -> None:
        """Build the supertag index from node relationships."""
        from collections import defaultdict

        from .constants import SUPERTAG_KEY_ID

        idx: defaultdict[NodeId, list[str]] = defaultdict(list)

        def _add(node_id: NodeId, tags: list[str]) -> None:
            for tag in tags:
                if tag and tag not in idx[node_id]:
                    idx[node_id].append(tag)

        # Find all supertag assignments
        for n in self.values():
            if not (
                isinstance(n, TupleNode)
                and len(n.children) >= 2
                and n.props.owner_id
                and (key_node := self.get(n.children[0]))
                and key_node.id == SUPERTAG_KEY_ID
            ):
                continue
            # Handle multi-value tuples - all children after the key are tag values
            for v in n.child_nodes[1:]:
                if v.name:
                    idx[n.props.owner_id].append(v.name)

        # Propagate tags via meta-node link
        for n in self.values():
            if n.props.meta_node_id:
                _add(n.id, list(idx[n.props.meta_node_id]))

        # Propagate wrapper tags to visible children
        def _is_wrapper(node: BaseNode) -> bool:
            return node.props.doc_type in {"workspace", "viewDef", "layout"}

        for w in self.values():
            if _is_wrapper(w):
                for cid in w.children:
                    _add(cid, list(idx[w.id]))

        self._supertag_index = dict(idx)

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

        nodes = {NodeId(n.id): n for n in (_make_node(doc) for doc in data["docs"])}
        return cls(nodes)


def load_tana_export(path: Path) -> NodeStore:
    """
    Load a Tana export JSON and convert it to a NodeStore with supertags.

    This is a convenience function that loads the file with supertags
    automatically indexed.

    Args:
        path: Path to the Tana JSON export file

    Returns:
        NodeStore with supertag index built
    """
    return NodeStore.from_file(path)
