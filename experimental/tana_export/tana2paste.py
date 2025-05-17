from __future__ import annotations

import argparse
import io
import logging
import os
import pathlib
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, List, TextIO

import tanalib as tl


@dataclass
class RenderCfg:
    """Rendering configuration"""
    max_depth: int
    debug_node: str | None = None


def tana_paste_outline(
    node: tl.Node,
    emitted: set[str],
    *,
    depth: int,
    root_ids: set[str],
    cfg: RenderCfg,
    visiting_stack: set[str],
) -> Iterable[str]:
    """Render *node* (recursively) in Tana Paste format.

    Similar to the outline function in tana2md.py but renders in Tana Paste format
    according to the official Tana Paste specification.
    """
    # Initialize visiting stack for recursive calls if this is the top-level call
    if visiting_stack is None:
        visiting_stack = set()

    # Create a separate stack for node rendering to prevent false cycles
    # This allows us to continue even when there are circular references
    render_stack = set(visiting_stack)

    # Check for actual rendering cycles (still visiting this exact node at this exact depth)
    render_key = f"{node.id}:{depth}"
    if render_key in render_stack:
        logging.debug(f"Detected rendering cycle for node {node.id} at depth {depth}")
        return

    # Add this node+depth to the render stack
    render_stack.add(render_key)

    # Calculate indent here so it's available for all code paths
    indent = "  " * depth

    # If node is already emitted, just return a reference to it without recursing
    if node.id in emitted and depth > 0:  # Allow roots to be rendered even if emitted

        # Direct access to name if we'd get a recursive ref
        title_text = node.props.get("name", "")
        logging.debug(f"Using direct access for reference to {node.id}: {title_text}")

        if title_text:
            yield f"{indent}- [[{title_text}]]"
        return

    if depth > cfg.max_depth:
        raise Exception(f"Reached max depth {cfg.max_depth} at node {node.id}")

    # Mark this node as emitted to prevent duplicates and avoid cycles
    emitted.add(node.id)

    # Handle different node types
    if node.doc_type == "tuple":
        yield from _render_tuple_node(node, indent, emitted, visiting_stack)
    else:
        yield from _render_regular_node(node, indent, depth, emitted, root_ids, cfg, visiting_stack)


def _is_checkbox_field(field_name: str) -> bool:
    """Determines if a field is a checkbox field based on its name."""
    # Only use the exact field name from Tana
    return field_name == "Show done/not done with a checkbox"


# Create a cache dictionary for field names
_field_name_cache = {}

def get_field_name(graph, src_id):
    """Get the field name for a source ID with caching.
    
    Args:
        graph: The Tana graph
        src_id: The source ID to look up
        
    Returns:
        The field name for the source ID
    """
    # Use the cache dictionary with src_id as key (which is always hashable)
    cache_key = src_id

    # Check cache first
    if cache_key in _field_name_cache:
        return _field_name_cache[cache_key]

    # First try exact match in tag_ids
    for k, v in graph.tag_ids.items():
        if v == src_id:
            field_name = k
            # Special handling for URL field - ensure casing is correct
            if k.lower() == "url":
                field_name = "URL"
            break
    else:
        # If field name not found in tag_ids, try to get it directly from source node
        src_node = graph.get(src_id)
        if src_node and "name" in src_node.props:
            field_name = src_node.props["name"]
            # Special handling for URL field - ensure casing is correct
            if isinstance(field_name, str) and field_name.lower() == "url":
                field_name = "URL"
        else:
            field_name = "Field"  # Fallback name

    # Cache the result
    _field_name_cache[cache_key] = field_name

    return field_name

def _render_tuple_node(node: tl.Node, indent: str, emitted: set[str], visiting_stack: set[str]) -> Iterable[str]:
    """Render a tuple node in Tana Paste format."""
    # Initialize visiting stack for recursive calls if needed
    if visiting_stack is None:
        visiting_stack = set()

    # Use context manager for cycle protection
    with tl.cycle_protection(visiting_stack, node.id) as cycle_detected:
        if cycle_detected:
            logging.warning(f"Detected cycle while rendering tuple node {node.id}")
            return

        src = node.props.get("_sourceId")

        # Get field name using cached function
        field_name = get_field_name(node.graph, src)

        # Mark all children as emitted
        for child in node.children:
            emitted.add(child.id)

        # Process child values (optimized for common case)
        if field_name == "URL":
            # Special case for URL fields - render each URL separately
            for child in node.children:
                # Skip if child is in visiting stack (cycle detection)
                if child.id in visiting_stack:
                    continue

                url = None
                # First check text property for URL
                if (text := child.props.get("text")) and isinstance(text, str):
                    if text.startswith("http://") or text.startswith("https://"):
                        url = text

                # Then check name property for URL
                if url is None and (name := child.props.get("name")) and isinstance(name, str):
                    if name.startswith("http://") or name.startswith("https://"):
                        url = name

                # Finally use title as fallback
                if url is None:
                    # Use child.title with cycle protection
                    if (title := child.title(visiting_stack=visiting_stack.copy())):
                        url = title

                if url:
                    yield f"{indent}- URL:: {url}"
                    return

        elif _is_checkbox_field(field_name):
            # Special case for checkbox fields
            if not node.children:
                # Empty checkbox defaults to unchecked
                yield f"{indent}- [ ]"
                return
            else:
                for child in node.children:
                    # Skip if child is in visiting stack (cycle detection)
                    if child.id in visiting_stack:
                        continue

                    # Get value using title with cycle protection
                    value = child.title(visiting_stack=visiting_stack.copy())

                    # Determine if the checkbox is checked
                    checkbox = "[x]" if value.lower() == "yes" else "[ ]"

                    # For the title, we need to check if node has a name that's not just "Yes"/"No"
                    title = child.props.get("name", value)

                    # Format with checkbox and title
                    if title:
                        yield f"{indent}- {checkbox} {title}"
                    else:
                        yield f"{indent}- {checkbox}"
                return
        else:
            # Regular fields - collect all values
            values = []
            for child in node.children:
                # Skip if child is in visiting stack (cycle detection)
                if child.id in visiting_stack:
                    continue

                # Get value using title with cycle protection
                title = child.title(visiting_stack=visiting_stack.copy())
                if title:
                    values.append(title)

            # Use the common field formatting function
            yield _format_field_with_value(field_name, values, indent)
            return


def _format_field_with_value(field_name: str, field_values: List[str], indent: str) -> str:
    """Format a field with its values in the correct Tana format.

    Args:
        field_name: The field name/attribute definition name
        field_values: List of values for the field
        indent: The indentation to use

    Returns:
        Formatted field string in Tana Paste format
    """
    # Join values with spaces if there are any
    if field_values:
        values_text = " ".join(field_values)
        return f"{indent}- {field_name}:: {values_text}"
    else:
        return f"{indent}- {field_name}::"

def _render_meta_lines(node: tl.Node, indent: str, visiting_stack: set[str]) -> List[str]:
    """Render meta information lines for a node."""
    # Initialize visiting stack for recursive calls if needed
    if visiting_stack is None:
        visiting_stack = set()

    lines = []

    # Get the meta node
    mid = node.props.get("_metaNodeId")
    if not mid or mid not in node.graph:
        return []

    # If the meta node ID is the same as this node, don't process (immediate cycle)
    if mid == node.id:
        return []

    # If the meta node ID is already in our stack, don't process (contains cycle)
    if mid in visiting_stack:
        return []

    # Keep track of nodes we're visiting to avoid cycles
    new_stack = visiting_stack.copy()
    new_stack.add(node.id)
    new_stack.add(mid)

    meta = node.graph[mid]
    all_tag_ids = set(node.graph.tag_ids.values())

    # Process meta node children
    for child in meta.children:
        # Skip if already in visiting stack
        if child.id in new_stack:
            continue

        # Add this child to visiting stack
        child_stack = new_stack.copy()
        child_stack.add(child.id)

        if child.doc_type == "tuple":
            # Skip tuples that assign super-tags (they'll be shown inline)
            if node._tuple_has_tag(child, all_tag_ids):
                continue

            # Get field name (using cached function)
            src = child.props.get("_sourceId")
            field_name = get_field_name(node.graph, src)

            # Process values based on field type
            child_indent = f"{indent}  "

            if field_name == "URL":
                # Special case for URL fields
                for c in child.children:
                    # Skip if in visiting stack
                    if c.id in child_stack:
                        continue

                    url = None
                    # First check text property for URL
                    if (text := c.props.get("text")) and isinstance(text, str):
                        if text.startswith("http://") or text.startswith("https://"):
                            url = text

                    # Then check name property for URL
                    if url is None and (name := c.props.get("name")) and isinstance(name, str):
                        if name.startswith("http://") or name.startswith("https://"):
                            url = name

                    # Finally try the title
                    if url is None and (title := c.title(visiting_stack=child_stack.copy())):
                        url = title

                    if url:
                        lines.append(f"{child_indent}- URL:: {url}")

            elif _is_checkbox_field(field_name):
                # Special case for checkbox fields
                if not child.children:
                    # Empty checkbox defaults to unchecked
                    lines.append(f"{child_indent}- [ ]")
                else:
                    for c in child.children:
                        # Skip if in visiting stack
                        if c.id in child_stack:
                            continue

                        # Get checkbox value
                        value = c.title(visiting_stack=child_stack.copy())

                        # Use Markdown checkbox format
                        is_checked = value.lower() in ["yes", "true", "done", "checked"]
                        checkbox = "[x]" if is_checked else "[ ]"
                        lines.append(f"{child_indent}- {checkbox}")
            else:
                # Regular fields - collect all values
                values = []
                for c in child.children:
                    # Skip if in visiting stack
                    if c.id in child_stack:
                        continue

                    # Get title with cycle protection
                    if (title := c.title(visiting_stack=child_stack.copy())):
                        values.append(title)

                # Use the common field formatting function
                lines.append(_format_field_with_value(field_name, values, child_indent))
        else:
            # For non-tuple children, just use the title
            # Skip if in visiting stack
            if child.id not in child_stack:
                if (title := child.title(visiting_stack=child_stack.copy())):
                    lines.append(f"{indent}  - {title}")

    return lines


def _format_node_title(node: tl.Node, title_text: str) -> str:
    """Format a node's title with tags if needed."""
    line = f"- {title_text}"

    # Add tags
    if (tags := node.all_tags()):
        line += " " + " ".join(f"#{tag}" for tag in tags)

    return line


def _render_regular_node(
    node: tl.Node,
    indent: str,
    depth: int,
    emitted: set[str],
    root_ids: set[str],
    cfg: RenderCfg,
    visiting_stack: set[str],
) -> List[str]:
    """Render a regular (non-tuple) node in Tana Paste format."""
    # Make a copy of the visiting stack for this node's processing
    node_stack = set(visiting_stack)

    # Check for cycles with this specific node
    if node.id in node_stack:
        return []

    # Add node to visiting stack
    node_stack.add(node.id)

    lines = []

    # For node title, use direct property access if necessary to avoid recursive reference
    # This is important for checkbox rendering which needs the real title
    if node.id in node_stack and node.props.get("name"):
        # Direct access for nodes in the visiting stack
        title_text = node.props["name"]
        logging.debug(f"Using direct title access for {node.id}: {title_text}")
    else:
        title_text = node.title(show_id=False, visiting_stack=node_stack.copy())

    if not title_text:
        return lines

    # Render node title with appropriate formatting
    line = indent + _format_node_title(node, title_text)
    lines.append(line)

    # Add meta information
    meta_lines = _render_meta_lines(node, indent, node_stack.copy())
    if meta_lines:
        lines.extend(meta_lines)

    # Look for checkbox field as direct children
    # Any node that has a "Show done/not done with a checkbox" field should be rendered with checkbox inline
    checkbox_value = None
    checkbox_tuple = None

    # Check if any direct child is a checkbox tuple field
    for child in node.children:
        if child.doc_type == "tuple":
            src_id = child.props.get("_sourceId")
            field_name = get_field_name(node.graph, src_id)

            if field_name == "Show done/not done with a checkbox":
                checkbox_tuple = child
                # Default to unchecked
                checkbox_value = "[ ]"

                # Determine state from tuple value
                for val_node in child.children:
                    # Use direct access to avoid recursive refs for checkbox values
                    if val_node.id in node_stack and val_node.props.get("name"):
                        val = val_node.props.get("name", "")
                        logging.debug(f"Using direct access for checkbox value {val_node.id}: {val}")
                    else:
                        val = val_node.title(visiting_stack=node_stack.copy())

                    if val and val.lower() in ["yes", "true", "done", "checked"]:
                        checkbox_value = "[x]"
                break

    # If this node has a checkbox field, render it inline
    if checkbox_value and checkbox_tuple:
        # Replace the node title with checkbox prefixed version
        lines[0] = f"{indent}- {checkbox_value} {title_text}"
        
        # Mark the checkbox tuple and its children as processed
        emitted.add(checkbox_tuple.id)
        for child in checkbox_tuple.children:
            emitted.add(child.id)
    
    # Process remaining children normally
    yield from _process_children(node, depth, emitted, root_ids, cfg, node_stack.copy())


def _process_children(
    node: tl.Node, 
    depth: int, 
    emitted: set[str], 
    root_ids: set[str] | None, 
    cfg: RenderCfg,
    visiting_stack: set[str] = None,
    skip_checkbox: bool = False
) -> List[str]:
    """Process a node's children and render them appropriately."""
    # Initialize visiting stack for recursive calls if needed
    if visiting_stack is None:
        visiting_stack = set()

    # Make a copy of the visiting stack to avoid modifying the parent's stack
    # Add this node to the stack
    child_stack = set(visiting_stack) | {node.id}

    lines = []
    child_indent = "  " * (depth + 1)

    # Track which child ids we've processed to avoid duplicates
    processed_children = set()

    for c in node.children:
        # Skip if we've already processed this child for this node
        if c.id in processed_children:
            continue

        processed_children.add(c.id)

        # Skip children that will be their own roots
        if root_ids and c.id in root_ids and c.id != node.id:
            if (ref := _create_reference(c)):
                lines.append(f"{child_indent}- {ref}")
            continue

        # Skip super-tag tuples (they're rendered inline with the node)
        if c.doc_type == "tuple" and node._tuple_has_tag(c, set(node.graph.tag_ids.values())):
            continue

        # Skip checkbox tuples if requested (for special rendering)
        if skip_checkbox and c.doc_type == "tuple":
            src_id = c.props.get("_sourceId")
            field_name = get_field_name(node.graph, src_id)
            if _is_checkbox_field(field_name):
                # Mark the checkbox tuple as emitted so it's not processed again
                emitted.add(c.id)
                continue

        # Make sure we're not trying to render a child already in our stack
        if c.id in child_stack:
            continue

        # Recursively process child
        child_lines = tana_paste_outline(
            c,
            emitted,
            depth=depth + 1,
            root_ids=root_ids,
            cfg=cfg,
            visiting_stack=child_stack.copy()
        )
        if child_lines:
            lines.extend(child_lines)

    return lines


def _create_reference(node: tl.Node) -> str:
    """Create a reference to another node in Tana Paste format."""
    title = node.title(show_id=False)

    if not title:
        return ""

    return f"[[{title}]]"


def render_tana_paste(
    g: tl.Graph,
    *,
    cfg: RenderCfg,
) -> Iterable[str]:
    """Render the entire graph in Tana Paste format to the output stream."""
    # Start with the Tana Paste marker
    yield "%%tana%%"

    # Find roots as in tana2md.py
    logging.info(f"Finding root nodes from {len(g)} total nodes...")
    roots = tl.find_roots(
        g, g.tag_ids, debug_node=cfg.debug_node if cfg else None
    )
    logging.info(f"Found {len(roots)} root nodes")

    emitted: set[str] = set()
    root_ids = {r.id for r in roots}

    # Sequential processing (original approach)
    for r in roots:
        yield from tana_paste_outline(r, emitted, root_ids=root_ids, cfg=cfg, depth=0, visiting_stack=set())

    # These are nodes that either have no parent or their parents are all system nodes
    logging.info("Processing miscellaneous nodes...")

    # Create a faster lookup for parents
    # This avoids the slow O(n²) process of checking every node against every other node
    child_to_parent = defaultdict(set)
    for parent in g.values():
        if parent.is_system:
            continue
        for child_id in parent.children_ids:
            child_to_parent[child_id].add(parent.id)

    yield "--- MISC ---"

    # Find misc nodes by checking if all their parents are system nodes
    for node in g.values():
        if node.id in emitted or node.is_system or not node.title():
            continue

        is_top_level = True
        # Check if this node has any non-system parents that haven't been emitted
        for parent_id in child_to_parent[node.id]:
            if not g[parent_id].is_system and parent_id not in emitted:
                is_top_level = False
                break

        if is_top_level and node.id not in emitted:
            yield from tana_paste_outline(node, emitted, root_ids=root_ids, cfg=cfg, depth=0, visiting_stack=set())


# ─── main ──────────────────────────────────────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=pathlib.Path, help="Path to Tana export JSON file")
    ap.add_argument(
        "--output", "-o",
        type=argparse.FileType("w"),
        default=sys.stdout,
        help="Output file (default: stdout)"
    )
    ap.add_argument("--top", type=int, help="only export the first N roots")
    ap.add_argument("--max-depth", type=int,
                    default=100,
                   help="limit the maximum depth of node hierarchies (improves performance)")
    ap.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="override LOG env (default INFO, DEBUG for verbose output)",
    )
    ap.add_argument("--show-id", action="store_true", help="include node ids inline")
    ap.add_argument(
        "--strict-roots", action="store_true", help="only tagged nodes are roots"
    )
    ap.add_argument("--debug-node", help="log decisions for a single node id")

    args = ap.parse_args(argv)

    # ---- configuration overrides ------------------------------------
    if args.log_level:
        logging.getLogger().setLevel(args.log_level.upper())

    # Configure rendering options
    cfg = RenderCfg(
        debug_node=args.debug_node,
        max_depth=args.max_depth,
    )

    g = tl.load_graph(args.src)
    logging.info("Graph loaded")
    with open(args.output, "w") as f:
        for line in render_tana_paste(g, cfg=cfg):
            f.write(line + "\n")


if __name__ == "__main__":
    sys.exit(main())
