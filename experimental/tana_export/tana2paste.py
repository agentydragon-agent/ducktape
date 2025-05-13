"""tana2paste.py — structured Tana JSON → Tana Paste format

Example:
  python -m tana2paste ~/downloads/tana-export-2025-05-12.json > tana-export-paste.txt

For large exports, use performance options to avoid slowdowns:
  python -m tana2paste --top 20 --max-depth 3 --log-level INFO ~/downloads/tana-export.json > tana-export-paste.txt

With progress information for better visibility during processing:
  python -m tana2paste --top 50 --max-depth 3 --log-level INFO --show-progress ~/downloads/tana-export.json > tana-export-paste.txt

For additional performance options (experimental):
  python -m tana2paste --top 100 --max-depth 4 --show-progress ~/downloads/tana-export.json > tana-export-paste.txt

This converter takes a Tana export JSON file and renders it in Tana Paste format.
Unlike tana2md.py, this creates a single file in Tana Paste format, which begins with
the %%tana%% marker and uses Tana's specific paste format.

The tool includes performance optimizations for handling large Tana exports:
- Limiting the number of root nodes processed with --top
- Limiting the depth of node hierarchies with --max-depth
- Memoization for efficient node ordering
- Progress tracking with --show-progress
- Post-processing for consistent field formatting
- Cache-friendly data structures for better performance

Reference: https://tana.inc/docs/tana-paste
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import pathlib
import re
import sys
import time
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, TextIO, Tuple

import tanalib as tl

# ---------------------------------------------------------------------------
# Rendering configuration
# ---------------------------------------------------------------------------


@dataclass
class RenderCfg:
    show_id: bool = False
    debug_node: str | None = None
    show_progress: bool = False
    parallel: bool = False
    max_workers: int = field(default_factory=lambda: max(1, multiprocessing.cpu_count() - 1))


# ---------------------------------------------------------------------------
# Tana Paste format renderer
# ---------------------------------------------------------------------------
# Performance notes:
# 1. The render_tana_paste function is optimized for single-threaded execution
#    with field name caching and efficient memory usage.
# 2. For large exports, limiting roots with --top and depth with --max-depth
#    provides the most significant performance gains.
# 3. Progress tracking with --show-progress provides visibility into the process
#    without significantly affecting performance.
# 4. The --parallel option is experimental and may actually be slower than
#    the single-threaded version due to process creation overhead and memory usage.
# ---------------------------------------------------------------------------

def process_root_node(args) -> Tuple[str, Set[str]]:
    """
    Process a single root node in parallel.
    
    This function takes a tuple of arguments and returns a tuple of
    (rendered_lines, emitted_nodes).
    """
    node, root_ids, max_depth = args
    # Each process needs its own emitted set
    emitted = set()
    
    # Simplified config for parallel processing
    cfg = RenderCfg(show_id=False)
    
    lines = tana_paste_outline(node, emitted, root_ids=root_ids, cfg=cfg, max_depth=max_depth)
    result = "\n".join(lines) + "\n" if lines else ""
    
    return result, emitted

def tana_paste_outline(
    node: tl.Node,
    emitted: set[str],
    *,
    depth: int = 0,
    root_ids: set[str] | None = None,
    cfg: RenderCfg | None = None,
    max_depth: int | None = None,
) -> List[str]:
    """Render *node* (recursively) in Tana Paste format.

    Similar to the outline function in tana2md.py but renders in Tana Paste format
    according to the official Tana Paste specification.
    """
    # Check both the global MAX_DEPTH and the optional max_depth parameter
    if depth > tl.MAX_DEPTH:
        raise RuntimeError(
            f"outline depth {depth} exceeds MAX_DEPTH={tl.MAX_DEPTH} at node {node.id}"
        )
    
    # Calculate indent here so it's available for all code paths
    indent = "  " * depth
    
    # If max_depth is specified, limit the recursion depth
    # >= because we want to include the node at exactly max_depth, but not its children
    if max_depth is not None and depth >= max_depth:
        # Only process the current node but not its children
        if depth == max_depth:
            if node.doc_type == "tuple":
                return _render_tuple_node(node, indent, emitted)
            else:
                # Return just the node title without processing children
                lines = []
                cfg = cfg or RenderCfg()
                title_text = node.title(show_id=False)
                if title_text:
                    line = _format_node_title(node, title_text, indent, cfg)
                    lines.append(line)
                    # Add meta information but skip children
                    lines.extend(_render_meta_lines(node, indent))
                return lines
        else:
            # For depths > max_depth, return nothing
            return []

    if node.id in emitted:
        return []

    emitted.add(node.id)
    lines: List[str] = []
    
    # Handle different node types
    if node.doc_type == "tuple":
        lines.extend(_render_tuple_node(node, indent, emitted))
    else:
        lines.extend(_render_regular_node(node, indent, depth, emitted, root_ids, cfg, max_depth))
    
    return lines


def _is_checkbox_field(field_name: str) -> bool:
    """Determines if a field is a checkbox field based on its name."""
    checkbox_keywords = ["checkbox", "done", "completed", "to-do", "todo"]
    return any(keyword.lower() in field_name.lower() for keyword in checkbox_keywords)


def _render_tuple_node(node: tl.Node, indent: str, emitted: set[str]) -> List[str]:
    """Render a tuple node in Tana Paste format."""
    lines = []
    src = node.props.get("_sourceId")
    
    # Use a cached field name lookup for better performance
    if not hasattr(node.graph, '_field_name_cache'):
        # Create the cache if it doesn't exist
        node.graph._field_name_cache = {}
    
    # Get field name from cache or compute it
    if src in node.graph._field_name_cache:
        field_name = node.graph._field_name_cache[src]
    else:
        # Get field name from source node
        field_name = None
        
        # First try exact match in tag_ids (case-insensitive for URL field)
        for k, v in node.graph.tag_ids.items():
            if v == src:
                field_name = k
                # Special handling for URL field - ensure casing is correct
                if k.lower() == "url":
                    field_name = "URL"
                break
        
        # If field name not found in tag_ids, try to get it directly from source node
        if field_name is None:
            src_node = node.graph.get(src)
            if src_node and "name" in src_node.props:
                field_name = src_node.props["name"]
                # Special handling for URL field - ensure casing is correct
                if isinstance(field_name, str) and field_name.lower() == "url":
                    field_name = "URL"
            else:
                field_name = "Field"  # Fallback name
                
        # Cache the result
        node.graph._field_name_cache[src] = field_name
    
    # Mark all children as emitted
    for child in node.children:
        emitted.add(child.id)
    
    # Process child values (optimized for common case)
    if field_name == "URL":
        # Special case for URL fields - render each URL separately
        for child in node.children:
            url = None
            # First check text property for URL
            if "text" in child.props and isinstance(child.props["text"], str):
                text = child.props["text"]
                if text.startswith("http://") or text.startswith("https://"):
                    url = text
            
            # Then check name property for URL
            if url is None and "name" in child.props and isinstance(child.props["name"], str):
                name = child.props["name"]
                if name.startswith("http://") or name.startswith("https://"):
                    url = name
                    
            # Finally use title as fallback
            if url is None and child.title():
                url = child.title()
                
            if url:
                lines.append(f"{indent}- URL:: {url}")
                
    elif _is_checkbox_field(field_name):
        # Special case for checkbox fields
        if not node.children:
            # Empty checkbox defaults to unchecked
            lines.append(f"{indent}- [ ]")
        else:
            for child in node.children:
                value = child.title()
                # Use Markdown checkbox format: "- [x]" for checked, "- [ ]" for unchecked
                is_checked = value.lower() in ["yes", "true", "done", "checked"]
                checkbox = "[x]" if is_checked else "[ ]"
                lines.append(f"{indent}- {checkbox}")
    else:
        # Regular fields - collect all values
        values = [c.title() for c in node.children if c.title()]
        if values:
            # Join values without a comma before the first value
            joined_values = " ".join(values)
            lines.append(f"{indent}- {field_name}:: {joined_values}")
        else:
            lines.append(f"{indent}- {field_name}::")
    
    return lines


def _render_regular_node(
    node: tl.Node, 
    indent: str, 
    depth: int, 
    emitted: set[str], 
    root_ids: set[str] | None, 
    cfg: RenderCfg | None,
    max_depth: int | None = None
) -> List[str]:
    """Render a regular (non-tuple) node in Tana Paste format."""
    lines = []
    cfg = cfg or RenderCfg()
    title_text = node.title(show_id=False)
    
    if not title_text:
        return lines
        
    # Render node title with appropriate formatting
    line = _format_node_title(node, title_text, indent, cfg)
    lines.append(line)
    
    # Add meta information
    lines.extend(_render_meta_lines(node, indent))
    
    # Process children
    lines.extend(_process_children(node, depth, emitted, root_ids, cfg, max_depth))
    
    return lines


def _format_node_title(node: tl.Node, title_text: str, indent: str, cfg: RenderCfg) -> str:
    """Format a node's title with tags and ID if needed."""
    # Debug
    if "Field:: URL" in title_text:
        logging.warning(f"Found 'Field:: URL' in title: {title_text}")
        logging.warning(f"Node props: {node.props}")
    
    # Check various node properties for URLs
    url_text = node.props.get("text", "")
    url_name = node.props.get("name", "")
    
    # Determine if this is a URL node by checking multiple properties
    is_url = False
    actual_url = ""
    
    # Check text property first
    if url_text and (url_text.startswith("http://") or url_text.startswith("https://")):
        is_url = True
        actual_url = url_text
    # Then check title
    elif title_text.startswith("http://") or title_text.startswith("https://"):
        is_url = True
        actual_url = title_text
    # Then check name property
    elif url_name and (url_name.startswith("http://") or url_name.startswith("https://")):
        is_url = True
        actual_url = url_name
    
    # Add all tags as #tag format
    tags = node.all_tags()
    tags_text = " ".join(f"#{tag}" for tag in tags)
    
    # Add node ID reference if requested
    node_ref = f"^{node.id}" if cfg.show_id else ""
    
    # Format URL nodes as Markdown links
    if is_url and actual_url:
        # Use the most human-readable property as display text
        display_text = url_name if url_name and url_name != actual_url else actual_url
        line = f"{indent}- [{display_text}]({actual_url})"
    else:
        line = f"{indent}- {title_text}"
    
    # Add tags and node ID
    if tags:
        line += f" {tags_text}"
    if cfg.show_id:
        line += node_ref
    
    return line


def _render_meta_lines(node: tl.Node, indent: str) -> List[str]:
    """Render meta information lines for a node."""
    lines = []
    
    # Get the meta node
    mid = node.props.get("_metaNodeId")
    if not mid or mid not in node.graph:
        return []

    meta = node.graph[mid]
    all_tag_ids = set(node.graph.tag_ids.values())
    
    # Create field name cache if needed
    if not hasattr(node.graph, '_field_name_cache'):
        node.graph._field_name_cache = {}
    
    # Process meta node children
    for child in meta.children:
        if child.doc_type == "tuple":
            # Skip tuples that assign super-tags (they'll be shown inline)
            if node._tuple_has_tag(child, all_tag_ids):
                continue
            
            # Get field name (using cache for performance)
            src = child.props.get("_sourceId")
            
            if src in node.graph._field_name_cache:
                field_name = node.graph._field_name_cache[src]
            else:
                field_name = None
                
                # First try to get field name from tag_ids
                for k, v in node.graph.tag_ids.items():
                    if v == src:
                        field_name = k
                        # Special handling for URL field to ensure correct casing
                        if k.lower() == "url":
                            field_name = "URL"
                        break
                
                # If field name not found in tag_ids, try source node
                if field_name is None:
                    src_node = node.graph.get(src)
                    if src_node and "name" in src_node.props:
                        field_name = src_node.props["name"]
                        # Special handling for URL field
                        if isinstance(field_name, str) and field_name.lower() == "url":
                            field_name = "URL"
                    else:
                        field_name = "Field"  # Fallback
                
                # Cache the result
                node.graph._field_name_cache[src] = field_name
            
            # Process values based on field type (optimized for common cases)
            child_indent = f"{indent}  "
            
            if field_name == "URL":
                # Special case for URL fields
                for c in child.children:
                    url = None
                    # First check text property
                    if "text" in c.props and isinstance(c.props["text"], str):
                        text = c.props["text"]
                        if text.startswith("http://") or text.startswith("https://"):
                            url = text
                    
                    # Then check name property
                    if url is None and "name" in c.props and isinstance(c.props["name"], str):
                        name = c.props["name"]
                        if name.startswith("http://") or name.startswith("https://"):
                            url = name
                    
                    # Finally try title
                    if url is None and c.title():
                        url = c.title()
                        
                    if url:
                        lines.append(f"{child_indent}- URL:: {url}")
                
            elif _is_checkbox_field(field_name):
                # Special case for checkbox fields
                if not child.children:
                    # Empty checkbox defaults to unchecked
                    lines.append(f"{child_indent}- [ ]")
                else:
                    for c in child.children:
                        value = c.title()
                        # Use Markdown checkbox format: "- [x]" for checked, "- [ ]" for unchecked
                        is_checked = value.lower() in ["yes", "true", "done", "checked"]
                        checkbox = "[x]" if is_checked else "[ ]"
                        lines.append(f"{child_indent}- {checkbox}")
            else:
                # Regular fields - collect all values
                values = [c.title() for c in child.children if c.title()]
                if values:
                    # Join values without a comma before the first value
                    joined_values = " ".join(values)
                    lines.append(f"{child_indent}- {field_name}:: {joined_values}")
                else:
                    lines.append(f"{child_indent}- {field_name}::")
        else:
            # For non-tuple children, just use the title
            title = child.title()
            if title:
                lines.append(f"{indent}  - {title}")
    
    return lines


def _process_children(
    node: tl.Node, 
    depth: int, 
    emitted: set[str], 
    root_ids: set[str] | None, 
    cfg: RenderCfg | None,
    max_depth: int | None = None
) -> List[str]:
    """Process a node's children and render them appropriately."""
    lines = []
    child_indent = "  " * (depth + 1)
    
    for c in node.children:
        # Skip children that will be their own roots
        if root_ids and c.id in root_ids and c.id != node.id:
            ref = _create_reference(c, cfg)
            if ref:
                lines.append(f"{child_indent}- {ref}")
            continue
            
        # Skip super-tag tuples (they're rendered inline with the node)
        if c.doc_type == "tuple" and node._tuple_has_tag(c, set(node.graph.tag_ids.values())):
            continue
            
        # Recursively process other children
        lines.extend(tana_paste_outline(c, emitted, depth=depth + 1, root_ids=root_ids, cfg=cfg, max_depth=max_depth))
    
    return lines


def _create_reference(node: tl.Node, cfg: RenderCfg | None) -> str:
    """Create a reference to another node in Tana Paste format."""
    cfg = cfg or RenderCfg()
    title = node.title(show_id=False)
    
    if not title:
        return ""
        
    ref = f"[[{title}"
    if cfg.show_id:
        ref += f"^{node.id}"
    ref += "]]"
    
    return ref


def render_tana_paste(
    g: tl.Graph,
    output: TextIO,
    *,
    strict_roots: bool = False,
    cfg: RenderCfg | None = None,
    top: int | None = None,
    max_depth: int | None = None,
) -> None:
    """Render the entire graph in Tana Paste format to the output stream."""
    # Redirect output to buffer to perform post-processing
    buffer = io.StringIO()
    
    # Start with the Tana Paste marker
    buffer.write("%%tana%%\n")
    
    # Find roots as in tana2md.py
    logging.info(f"Finding root nodes from {len(g)} total nodes...")
    roots = tl.find_roots(
        g, g.tag_ids, strict_roots=strict_roots, debug_node=cfg.debug_node if cfg else None
    )
    logging.info(f"Found {len(roots)} root nodes")
    
    if top:
        logging.info(f"Limiting to top {top} roots")
        roots = roots[:top]
    
    emitted: set[str] = set()
    root_ids = {r.id for r in roots}
    
    # Render each root
    total_roots = len(roots)
    start_time = time.time()
    
    # Check if we should use parallel processing
    if cfg and cfg.parallel and total_roots > 1:
        logging.info(f"Processing {total_roots} roots in parallel with {cfg.max_workers} workers")
        
        # Prepare arguments for parallel processing
        args_list = [(r, root_ids, max_depth) for r in roots]
        
        # Process roots in parallel and collect results
        with ProcessPoolExecutor(max_workers=cfg.max_workers) as executor:
            # Submit all tasks
            future_to_idx = {executor.submit(process_root_node, args): i 
                           for i, args in enumerate(args_list)}
            
            # Process results as they complete
            completed = 0
            for future in as_completed(future_to_idx):
                i = future_to_idx[future] + 1  # 1-indexed for display
                try:
                    result, node_emitted = future.result()
                    emitted.update(node_emitted)  # Merge emitted node IDs
                    if result:
                        buffer.write(result)
                    
                    # Update progress
                    completed += 1
                    if cfg.show_progress and (completed % 5 == 0 or completed == 1 or completed == total_roots):
                        elapsed = time.time() - start_time
                        progress = completed / total_roots * 100
                        logging.info(f"Processed {completed}/{total_roots} roots ({progress:.1f}%) in {elapsed:.1f}s")
                        
                except Exception as exc:
                    logging.error(f"Root {i} generated an exception: {exc}")
    else:
        # Sequential processing (original approach)
        for i, r in enumerate(roots, 1):
            # Show progress every 5 roots or for the first and last
            if i % 5 == 0 or i == 1 or i == total_roots:
                elapsed = time.time() - start_time
                estimated_total = (elapsed / i) * total_roots if i > 0 else 0
                remaining = max(0, estimated_total - elapsed)
                
                progress_info = f"Processing root {i}/{total_roots}: {r.title()[:30]}..."
                
                if cfg and cfg.show_progress and i > 1:
                    progress_info += f" ({elapsed:.1f}s elapsed, ~{remaining:.1f}s remaining)"
                    
                logging.info(progress_info)
                
            lines = tana_paste_outline(r, emitted, root_ids=root_ids, cfg=cfg, max_depth=max_depth)
            if lines:
                buffer.write("\n".join(lines))
                buffer.write("\n")
    
    # Initialize misc_lines here to avoid reference error
    misc_lines = []
    
    # Limit miscellaneous node processing for performance
    # Skip if we already have enough content from roots
    if len(emitted) < 500:  # Only process misc nodes if we haven't already emitted a lot
        # Build a list of all top-level nodes that haven't been emitted yet
        # These are nodes that either have no parent or their parents are all system nodes
        logging.info("Processing miscellaneous nodes...")
        misc_start_time = time.time()
        top_level_nodes = []
        
        # Create a faster lookup for parents
        # This avoids the slow O(n²) process of checking every node against every other node
        parent_map = {}
        child_to_parent = {}
        for parent in g.values():
            if not parent.is_system:
                for child_id in parent.children_ids:
                    if child_id in g:
                        child_to_parent[child_id] = child_to_parent.get(child_id, []) + [parent.id]
        
        # First pass - identify nodes that aren't already emitted
        candidate_nodes = [n for n in g.values() 
                        if n.id not in emitted and not n.is_system and n.title()]
        
        logging.info(f"Found {len(candidate_nodes)} candidate miscellaneous nodes")
        
        # Find top-level nodes by checking if all their parents are system nodes
        # Using the precomputed parent map for much faster lookups
        limit = 200  # Limit the number of misc nodes to process
        count = 0
        
        for node in candidate_nodes:
            if count >= limit:
                break
                
            is_top_level = True
            # Check if this node has any non-system parents that haven't been emitted
            parents = child_to_parent.get(node.id, [])
            
            for parent_id in parents:
                if parent_id in g and not g[parent_id].is_system and parent_id not in emitted:
                    is_top_level = False
                    break
            
            if is_top_level:
                top_level_nodes.append(node)
                count += 1
        
        # Get the top 100 nodes to process
        nodes_to_process = top_level_nodes[:100]
        logging.info(f"Processing {len(nodes_to_process)} top-level miscellaneous nodes")
        
        # Process a limited number of nodes without sorting by depth for better performance
        emitted_count = 0
        
        for i, n in enumerate(nodes_to_process, 1):
            if n.id not in emitted:
                lines = tana_paste_outline(n, emitted, root_ids=root_ids, cfg=cfg, max_depth=max_depth)
                if lines:
                    misc_lines.extend(lines)
                    emitted_count += 1
                    
                    # Add progress indicator every 10 nodes
                    if emitted_count % 10 == 0:
                        misc_elapsed = time.time() - misc_start_time
                        misc_info = f"Processed {emitted_count}/{len(nodes_to_process)} miscellaneous nodes"
                        
                        if cfg and cfg.show_progress and emitted_count > 10:
                            misc_total = (misc_elapsed / emitted_count) * len(nodes_to_process)
                            misc_remaining = max(0, misc_total - misc_elapsed)
                            misc_info += f" ({misc_elapsed:.1f}s elapsed, ~{misc_remaining:.1f}s remaining)"
                            
                        logging.info(misc_info)
    
    if misc_lines:
        buffer.write("\n# Miscellaneous Nodes\n")
        buffer.write("\n".join(misc_lines))
        buffer.write("\n")
        
    # Post-processing: fix any "Field:: URL, http" instances to "URL:: http"
    buffer_text = buffer.getvalue()
    
    # Replace all instances of "Field:: URL, http" with "URL:: http"
    fixed_text = re.sub(r"Field:: URL,\s+(https?://[^\s,]+)", r"URL:: \1", buffer_text)
    
    # Also replace any "Field:: URL" with "URL::" (for empty fields)
    fixed_text = re.sub(r"Field:: URL$", r"URL::", fixed_text, flags=re.MULTILINE)
    fixed_text = re.sub(r"Field:: URL\s*$", r"URL::", fixed_text, flags=re.MULTILINE)
    
    # Fix all "Field::" to proper field names without the "Field::" prefix
    # This ensures proper rendering of all field types
    fixed_text = re.sub(r"Field:: ([^,\n]+)(,?\s*)", r"\1::\2", fixed_text)
    
    # Fix empty Field:: entries
    fixed_text = re.sub(r"Field::\s*$", r"", fixed_text, flags=re.MULTILINE)
    
    # Fix all "tuple::" prefixes to be proper field names
    fixed_text = re.sub(r"tuple:: ([^,\n]+)(,?\s*)", r"\1::\2", fixed_text)
    
    # Fix empty tuple:: entries
    fixed_text = re.sub(r"tuple::\s*$", r"", fixed_text, flags=re.MULTILINE)
    
    # Handle various checkbox field name formats and values (case-insensitive)
    # Create regex patterns for checkbox detection
    checkbox_patterns = [
        # Primary pattern: "Show done/not done with a checkbox"
        r"Show done/not done with a checkbox",
        # Alternative names that might be used
        r"Checkbox",
        r"Done",
        r"Completed",
        r"To-do",
        r"Todo"
    ]
    
    # Create a combined regex pattern that matches any of the checkbox field names
    checkbox_pattern = "|".join(checkbox_patterns)
    
    # Fix regular checkboxes
    fixed_text = re.sub(rf"- (?:{checkbox_pattern})::,?\s*[Yy][Ee][Ss]", r"- [x]", fixed_text, flags=re.IGNORECASE)
    fixed_text = re.sub(rf"- (?:{checkbox_pattern})::,?\s*[Tt][Rr][Uu][Ee]", r"- [x]", fixed_text, flags=re.IGNORECASE)
    fixed_text = re.sub(rf"- (?:{checkbox_pattern})::,?\s*[Dd][Oo][Nn][Ee]", r"- [x]", fixed_text, flags=re.IGNORECASE)
    fixed_text = re.sub(rf"- (?:{checkbox_pattern})::,?\s*[Cc][Hh][Ee][Cc][Kk][Ee][Dd]", r"- [x]", fixed_text, flags=re.IGNORECASE)
    
    fixed_text = re.sub(rf"- (?:{checkbox_pattern})::,?\s*[Nn][Oo]", r"- [ ]", fixed_text, flags=re.IGNORECASE)
    fixed_text = re.sub(rf"- (?:{checkbox_pattern})::,?\s*[Ff][Aa][Ll][Ss][Ee]", r"- [ ]", fixed_text, flags=re.IGNORECASE)
    
    # Default to unchecked for empty checkbox fields
    fixed_text = re.sub(rf"- (?:{checkbox_pattern})::", r"- [ ]", fixed_text, flags=re.IGNORECASE)
    
    # Fix indented checkboxes in meta sections
    fixed_text = re.sub(rf"  - (?:{checkbox_pattern})::,?\s*[Yy][Ee][Ss]", r"  - [x]", fixed_text, flags=re.IGNORECASE)
    fixed_text = re.sub(rf"  - (?:{checkbox_pattern})::,?\s*[Tt][Rr][Uu][Ee]", r"  - [x]", fixed_text, flags=re.IGNORECASE)
    fixed_text = re.sub(rf"  - (?:{checkbox_pattern})::,?\s*[Dd][Oo][Nn][Ee]", r"  - [x]", fixed_text, flags=re.IGNORECASE)
    fixed_text = re.sub(rf"  - (?:{checkbox_pattern})::,?\s*[Cc][Hh][Ee][Cc][Kk][Ee][Dd]", r"  - [x]", fixed_text, flags=re.IGNORECASE)
    
    fixed_text = re.sub(rf"  - (?:{checkbox_pattern})::,?\s*[Nn][Oo]", r"  - [ ]", fixed_text, flags=re.IGNORECASE)
    fixed_text = re.sub(rf"  - (?:{checkbox_pattern})::,?\s*[Ff][Aa][Ll][Ss][Ee]", r"  - [ ]", fixed_text, flags=re.IGNORECASE)
    
    # Default to unchecked for empty checkbox fields
    fixed_text = re.sub(rf"  - (?:{checkbox_pattern})::", r"  - [ ]", fixed_text, flags=re.IGNORECASE)
    
    # Write the final processed output
    output.write(fixed_text)


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
    ap.add_argument("--show-progress", action="store_true", 
                  help="show detailed progress information during processing")
    ap.add_argument("--parallel", action="store_true",
                  help="use experimental parallel processing (may be slower)")
    ap.add_argument("--workers", type=int,
                  help="number of parallel workers for --parallel (default: CPU count - 1)")

    args = ap.parse_args(argv)

    # ---- configuration overrides ------------------------------------
    if args.log_level:
        logging.getLogger().setLevel(args.log_level.upper())

    strict_roots_flag = args.strict_roots or bool(int(os.getenv("STRICT_ROOTS", "0")))
    # Configure rendering options
    max_workers = args.workers if args.workers else max(1, multiprocessing.cpu_count() - 1)
    cfg = RenderCfg(
        show_id=args.show_id, 
        debug_node=args.debug_node,
        show_progress=args.show_progress,
        parallel=args.parallel,
        max_workers=max_workers
    )

    try:
        start_time = time.time()
        g = tl.load_graph(args.src)
        logging.info(f"Graph loaded in {time.time() - start_time:.2f} seconds")
        
        render_start_time = time.time()
        render_tana_paste(
            g, 
            args.output, 
            strict_roots=strict_roots_flag, 
            cfg=cfg,
            top=args.top,
            max_depth=args.max_depth
        )
        total_time = time.time() - start_time
        render_time = time.time() - render_start_time
        
        logging.info(f"Successfully converted to Tana Paste format in {total_time:.2f} seconds")
        if cfg.show_progress:
            logging.info(f"  - Graph loading: {render_start_time - start_time:.2f}s")
            logging.info(f"  - Rendering: {render_time:.2f}s")
    except Exception as e:
        logging.error(f"Error converting to Tana Paste format: {e}")
        if args.log_level == "DEBUG":
            import traceback
            traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())