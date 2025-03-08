#!/usr/bin/env python3
"""
A script to dump a Python repo into one text blob, skipping certain files
(similar to a .gitignore approach), and optionally removing repeated text
snippets. Uses Click for CLI, including a trick to allow `-o` with or without a
filename.

It also shows how many tokens each file contributes, sorted descending, top 10.
"""

import os
import sys
import fnmatch
import re

import click
import yaml

CONFIG_PATH = os.path.expanduser("~/.config/repodump.yaml")

DEFAULT_CONFIG = {
    "repos": {},
    "global": {
        "include": [
            "*.py",
            "*.md",
            "*.rst",
        ],
        "exclude": [
            "*.egg-info*",
            "*__pycache__*",
            "*.mo",
            "*.po",
            "*LC_MESSAGES*",
            "*fonts*",
            "*.jpg",
            "*.jpeg",
            "*.png",
            "*.gif",
            "*.webp",
            "*.ico",
            "*.svg",
        ],
    },
}


def load_config():
    """Load YAML config from ~/.config/repodump.yaml or exit if missing."""
    if not os.path.isfile(CONFIG_PATH):
        click.echo(f"Config not found: {CONFIG_PATH}\nPlease create it, then re-run.")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def pattern_match(path, patterns):
    """Return True if 'path' matches any pattern in 'patterns' (fnmatch)."""
    return any(fnmatch.fnmatch(path, p) for p in patterns)


def scan_directory(root_dir, cfg_includes, cfg_excludes):
    """
    Recursively gather text from files that match 'include' but not 'exclude',
    using relative paths from 'root_dir' for matching.
    Track any unknown files not matched by either.
    Returns: (all_files, uncertain_files).
    """
    all_files = []
    uncertain_files = []

    for dirpath, dirnames, filenames in os.walk(root_dir):
        rel_dir = os.path.relpath(dirpath, root_dir)
        if rel_dir == ".":
            rel_dir = ""

        # If this directory is excluded, skip subfolders:
        if rel_dir and pattern_match(rel_dir, cfg_excludes):
            dirnames[:] = []
            continue

        for f in filenames:
            rel_file = os.path.join(rel_dir, f) if rel_dir else f

            if pattern_match(rel_file, cfg_includes):
                all_files.append(os.path.join(dirpath, f))
            elif pattern_match(rel_file, cfg_excludes):
                continue
            else:
                # Not matched => uncertain
                uncertain_files.append(rel_file)

    return all_files, sorted(set(uncertain_files))


def approximate_tokens(byte_count):
    """Roughly estimate tokens from bytes (1 token ~ 4 chars)."""
    return byte_count // 4


def strip_snippets_from_text(text, snippets):
    """
    snippets is a list of dicts, each dict might have:
      - type: "literal" or "regex"
      - lines: str (if type=literal)
      - pattern: str (if type=regex)
      - flags: optional string e.g. "IGNORECASE|MULTILINE"

    Removes all occurrences found anywhere in the text.
    """
    for snip in snippets:
        stype = snip.get("type")
        if stype == "literal":
            text = remove_literal(text, snip.get("lines", ""))
        elif stype == "regex":
            text = remove_regex(text, snip.get("pattern", ""), snip.get("flags", ""))
    return text


def remove_literal(text, snippet):
    """Remove every occurrence of 'snippet' from text."""
    if not snippet:
        return text
    return text.replace(snippet, "")


def remove_regex(text, pattern, flags_str):
    """Remove all matches of 'pattern' from text. 'flags_str' e.g. 'IGNORECASE|MULTILINE'."""
    combined_flags = 0
    for f in flags_str.split("|"):
        f = f.strip().upper()
        if hasattr(re, f):
            combined_flags |= getattr(re, f)

    return re.sub(pattern, "", text, flags=combined_flags)


@click.command(
    context_settings=dict(
        allow_extra_args=True,  # let us parse leftover arguments
        ignore_unknown_options=True
    )
)
@click.option(
    "--output",
    "-o",
    "output_flag",
    is_flag=True,
    default=False,
    help="Enable output. -o => either stdout (if no filename) or file (if filename follows)."
)
@click.option(
    "--copy",
    "-c",
    "copy_output",
    is_flag=True,
    help="Copy final output to clipboard (requires pyperclip)."
)
@click.pass_context
def main(ctx, output_flag, copy_output):
    """
    Dump all matched repo files into a single text blob, optionally removing repeated snippets.
    Also shows top 10 files by token count.
    """
    leftover = ctx.args[:]  # leftover arguments not consumed by Click

    # Figure out if user gave -o, plus a file
    if output_flag:
        if leftover and not leftover[0].startswith("-"):
            output_file = leftover[0]
            leftover = leftover[1:]
        else:
            output_file = ""  # signals "stdout"
    else:
        output_file = None  # signals "no dump"

    if leftover:
        click.echo(f"Warning: ignoring extra arguments: {leftover}")

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

    # Find files
    all_files, uncertain_files = scan_directory(root_dir, includes, excludes)

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

    blob_lines = []
    file_token_counts = []
    for fp in sorted(all_files):
        relpath = os.path.relpath(fp, root_dir)
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            blob_lines.append(f"# Skipped unreadable file: {relpath}\n\n")
            continue

        # remove snippets
        content = strip_snippets_from_text(content, snippets)

        # measure tokens
        tcount = approximate_tokens(len(content.encode("utf-8")))
        file_token_counts.append((relpath, tcount))

        blob_lines.append(f"# FILE: {relpath}\n{content}\n\n")

    final_text = "".join(blob_lines)
    byte_count = len(final_text.encode("utf-8"))
    total_tokens = approximate_tokens(byte_count)

    click.echo(f"Files included: {len(all_files)}")
    click.echo(f"Total size: {byte_count} bytes, ~{total_tokens} tokens.")

    # Sort desc by token count, show top 10
    file_token_counts.sort(key=lambda x: x[1], reverse=True)
    click.echo("\nTop 10 files by token count:")
    for relpath, tcount in file_token_counts[:10]:
        click.echo(f"  {tcount} tokens: {relpath}")

    # Output logic
    if output_file is None:
        return  # no dump

    if output_file == "":
        # user did -o with no filename => stdout
        click.echo("\n=== BEGIN DUMP ===")
        click.echo(final_text, nl=False)
        click.echo("\n=== END DUMP ===")
    else:
        # user gave a filename
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
