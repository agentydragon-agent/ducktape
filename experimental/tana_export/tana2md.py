"""tana2md.py — structured Tana JSON → Markdown

Example:

  python -m tana2md ~/downloads/tana-export-2025-05-12.json ~/tana-export-2025-05-12

Highlights
-----------
* skips system/view/workspace shells
* a node becomes a *root file* when it:
    – has super‑tag #day, #page, #issue or #event, or
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
import logging
import os
import pathlib
from dataclasses import dataclass
from typing import Any, Dict, List

import tanalib as tl

# ---------------------------------------------------------------------------
# Rendering configuration (view-level)
# ---------------------------------------------------------------------------


@dataclass
class RenderCfg:
    show_id: bool = False
    debug_node: str | None = None


def _is_checkbox_field(field_name: str) -> bool:
    """Determines if a field is a checkbox field based on its name."""
    checkbox_keywords = ["checkbox", "done", "completed", "to-do", "todo"]
    return any(keyword.lower() in field_name.lower() for keyword in checkbox_keywords)


# ─── outline ----------------------------------------------------------------
def outline(
    node: tl.Node,
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
    "Calendar" page).
    """

    if depth > tl.MAX_DEPTH:
        raise RuntimeError(
            f"outline depth {depth} exceeds MAX_DEPTH={tl.MAX_DEPTH} at node {node.id}"
        )

    if node.id in emitted:
        return []

    emitted.add(node.id)
    indent = "  " * depth
    lines: List[str] = []

    # ── tuple ────────────────────────────────────────────────────────────
    if node.doc_type == "tuple":
        lines.append(indent + "- " + node.tuple_line(show_id=cfg.show_id if cfg else False))
        return lines

    # ── regular node ─────────────────────────────────────────────────────
    cfg = cfg or RenderCfg()
    title_text = node.title(show_id=cfg.show_id)
    if title_text:
        # Include all tags, not just super_tags
        tags_inline = "".join(f" #{name}" for name in node.all_tags())
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

    g = tl.load_graph(args.src)
    roots = tl.find_roots(
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
        for name in tl.ROOT_TAGS:
            tid = g.tag_ids.get(name)
            if tid and r.has_tag({tid}):
                bucket = name
                break
        target = args.dst / (bucket if bucket else "")
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{idx:03d}-{tl.slugify(r.title())}.md"
        path.write_text(
            f"<!-- id: {r.id} -->\n" + "\n".join(lines) + "\n", encoding="utf-8"
        )

    # Collect miscellaneous nodes that haven't been emitted yet
    misc_nodes = [n for n in g.values() 
                  if n.id not in emitted and not n.is_system and n.children_ids and n.title()]
    
    # Order nodes by hierarchy so parent nodes are processed before children
    ordered_misc_nodes = tl.order_nodes_by_hierarchy(g, misc_nodes)
    
    # Process the ordered nodes
    for n in ordered_misc_nodes:
        # Only process if not already emitted by a parent (or self)
        if n.id not in emitted:
            misc.extend(outline(n, emitted, root_ids=root_ids, cfg=cfg))
            # Since emitted is updated during processing, we avoid redundantly processing nodes
    
    if misc:
        (args.dst / "zzz_misc.md").write_text("\n".join(misc) + "\n", encoding="utf-8")

    logging.info("wrote %d root files%s", len(roots), " + misc" if misc else "")


if __name__ == "__main__":
    main()