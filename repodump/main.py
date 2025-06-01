#!/usr/bin/env python3
"""
Dump a Python repo into one text blob, skipping certain files (similar to a .gitignore approach).
Uses a custom path-aware matching so that '*' does NOT cross directories by default.
If you want subdirectories, use '**' in your pattern.

Examples:
  - "boxes/*.py" => matches "boxes/foo.py", not "boxes/subdir/bar.py"
  - "boxes/**/*.py" => matches "boxes/bar.py" plus deeper, "boxes/subdir/bar.py"
"""

import os
import re
import sys

import click
import yaml

from .patterns import path_match

CONFIG_PATH = os.path.expanduser("~/.config/repodump.yaml")


def load_config():
    """Load YAML config from ~/.config/repodump.yaml or exit if missing."""
    if not os.path.isfile(CONFIG_PATH):
        click.echo(f"Config not found: {CONFIG_PATH}\nPlease create it, then re-run.")
        sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


#
# -------------- The core scanning code --------------
#


def scan_directory(root_dir, cfg_includes, cfg_excludes):
    """
    Recursively gather text from files that match 'include' but not 'exclude',
    using relative paths from 'root_dir' for matching.

    This respects our custom path-based patterns:
      - 'foo/*.py' won't match subdirs
      - 'foo/**/*.py' will
    """
    all_files = []
    uncertain_files = []

    for dirpath, dirnames, filenames in os.walk(root_dir):
        rel_dir = os.path.relpath(dirpath, root_dir)
        if rel_dir == ".":
            rel_dir = ""

        # If this directory is excluded (by the entire dir path):
        if rel_dir and path_match(rel_dir, cfg_excludes):
            # skip subfolders
            dirnames[:] = []
            continue

        for f in filenames:
            rel_file = f if not rel_dir else os.path.join(rel_dir, f)

            # If it matches exclude, skip
            if path_match(rel_file, cfg_excludes):
                continue

            # If it matches include, we want it
            if path_match(rel_file, cfg_includes):
                all_files.append(os.path.join(dirpath, f))
            else:
                # Not matched by either => uncertain
                uncertain_files.append(rel_file)

    return all_files, sorted(set(uncertain_files))


def approximate_tokens(byte_count):
    """Rough estimate: 1 token ~ 4 chars."""
    return byte_count // 4


#
# -------------- Snippet removal code --------------
#


def strip_snippets_from_text(text, snippets):
    """
    snippets: list of dicts, each dict might have:
      - type: "literal" or "regex"
      - lines: str
      - pattern: str
      - flags: e.g. "IGNORECASE|MULTILINE"
    """
    for snip in snippets:
        stype = snip.get("type")
        if stype == "literal":
            text = remove_literal(text, snip.get("lines", ""))
        elif stype == "regex":
            text = remove_regex(text, snip.get("pattern", ""), snip.get("flags", ""))
    return text


def remove_literal(text, snippet):
    """Remove all occurrences of snippet from text."""
    if not snippet:
        return text
    return text.replace(snippet, "")


def remove_regex(text, pattern, flags_str):
    combined_flags = 0
    for f in flags_str.split("|"):
        f = f.strip().upper()
        if hasattr(re, f):
            combined_flags |= getattr(re, f)
    return re.sub(pattern, "", text, flags=combined_flags)


#
# -------------- CLI with Click --------------
#


@click.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
@click.option(
    "--output",
    "-o",
    "output_flag",
    is_flag=True,
    default=False,
    help="Enable output. -o => either stdout (if no filename) or file (if filename follows).",
)
@click.option(
    "--copy",
    "-c",
    "copy_output",
    is_flag=True,
    help="Copy final output to clipboard (requires pyperclip).",
)
@click.pass_context
def main(ctx, output_flag, copy_output):
    """
    Dump matched repo files into one blob, skipping certain files or dirs,
    and removing repeated snippets if configured.

    Single '*' does not cross directories. Use '**' if you want to match subdirs.
    """
    leftover = ctx.args[:]
    if output_flag:
        # If user gave '-o', see if leftover has a filename
        if leftover and not leftover[0].startswith("-"):
            output_file = leftover[0]
            leftover = leftover[1:]
        else:
            output_file = ""
    else:
        output_file = None

    if leftover:
        click.echo(f"Warning: ignoring extra args: {leftover}")

    # Load config
    config = load_config()
    root_dir = os.getcwd()

    # Merge config
    if "repos" not in config:
        config["repos"] = {}
    if "global" not in config:
        config["global"] = DEFAULT_CONFIG["global"]

    repo_cfg = config["repos"].get(root_dir, {})
    includes = repo_cfg.get("include", []) + config["global"].get("include", [])
    excludes = repo_cfg.get("exclude", []) + config["global"].get("exclude", [])
    snippets = config.get("strip_snippets", [])  # optional snippet removal

    # Scan
    all_files, uncertain_files = scan_directory(root_dir, includes, excludes)

    # If unknown => ask user to fix config
    if uncertain_files:
        click.echo("These files are not matched by include/exclude patterns:")
        for u in uncertain_files:
            click.echo(f"  - {u}")
        click.echo(f"\nAdd them to your config in: {CONFIG_PATH}")
        if root_dir not in config["repos"]:
            config["repos"][root_dir] = {"include": [], "exclude": []}
        click.echo("\nExample snippet to add:\n")
        for u in uncertain_files:
            click.echo(f"    # - {u}")
        click.echo("\nThen rerun. Exiting now.")
        sys.exit(0)

    # Read + combine
    blob_lines = []
    file_token_counts = []

    for fp in sorted(all_files):
        relpath = os.path.relpath(fp, root_dir)
        try:
            with open(fp, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            blob_lines.append(f"# Skipped unreadable file: {relpath}\n\n")
            continue

        content = strip_snippets_from_text(content, snippets)
        tokens_here = approximate_tokens(len(content.encode("utf-8")))
        file_token_counts.append((relpath, tokens_here))

        blob_lines.append(f"# FILE: {relpath}\n{content}\n\n")

    final_text = "".join(blob_lines)
    byte_count = len(final_text.encode("utf-8"))
    total_tokens = approximate_tokens(byte_count)

    click.echo(f"Files included: {len(all_files)}")
    click.echo(f"Total size: {byte_count} bytes, ~{total_tokens} tokens.")

    # Sort desc, show top 10
    file_token_counts.sort(key=lambda x: x[1], reverse=True)
    top_10 = file_token_counts[:10]
    click.echo("\nTop 10 files by token count:")
    for path_, tcount_ in top_10:
        click.echo(f"  {tcount_} tokens: {path_}")

    # Output logic
    if output_file is None:
        return  # no dump

    if output_file == "":
        # -o => stdout
        click.echo("\n=== BEGIN DUMP ===")
        click.echo(final_text, nl=False)
        click.echo("\n=== END DUMP ===")
    else:
        # -o somefile => write
        outpath = os.path.abspath(output_file)
        with open(outpath, "w", encoding="utf-8") as wf:
            wf.write(final_text)
        click.echo(f"Dump written to: {outpath}")

    if copy_output:
        try:
            import pyperclip

            pyperclip.copy(final_text)
            click.echo("Dump copied to clipboard.")
        except ImportError:
            click.echo("pyperclip not installed; cannot copy to clipboard.")


if __name__ == "__main__":
    main()
