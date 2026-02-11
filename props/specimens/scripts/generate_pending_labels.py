#!/usr/bin/env python3
"""Generate markdown file listing issues missing graders_match_only_if_reported_on field."""

from collections import defaultdict
from pathlib import Path

import yaml


def normalize_lines(line_spec) -> list[tuple[int, int]]:
    """Normalize line specs to list of (start, end) tuples."""
    if line_spec is None:
        return []
    if isinstance(line_spec, int):
        return [(line_spec, line_spec)]
    if isinstance(line_spec, list):
        if len(line_spec) == 2 and all(isinstance(x, int) for x in line_spec):
            return [(line_spec[0], line_spec[1])]
        result = []
        for item in line_spec:
            if isinstance(item, int):
                result.append((item, item))
            elif isinstance(item, list) and len(item) == 2:
                result.append((item[0], item[1]))
        return result
    return []


# Priority ordering: easiest to confirm -> hardest
# Format: "snapshot|issue_file|occ_id" -> priority (lower = easier, show first)
# Issues not in this list get priority 1000 (unordered, shown after ordered ones)
# Priority 9999 = SKIP (cross-file implications, should NOT set field)
PRIORITY_ORDER = {
    # === EASY (P10): Obviously single-file local issues ===
    # Simple dead code, docs mismatch, local style issues
    "crush/2025-08-30-internal_db|bash-timeout-docs-mismatch.yaml|occ-0": 10,
    "crush/2025-08-30-internal_db|glob-sort-docs-mismatch.yaml|occ-0": 10,
    "crush/2025-08-30-internal_db|misleading-func-name.yaml|occ-0": 10,
    "crush/2025-08-30-internal_db|sentinel-flag-pattern.yaml|occ-0": 10,
    "crush/2025-08-30-internal_db|lsp-stdin-race.yaml|occ-0": 10,
    "crush/2025-08-30-internal_db|create-replace-fallthrough.yaml|occ-0": 10,
    # === EASY (P15): All occurrences in same file, easy bulk assignment ===
    # renderer-guard-clauses - all in same file
    "crush/2025-08-30-internal_db|renderer-guard-clauses.yaml|occ-0": 15,
    "crush/2025-08-30-internal_db|renderer-guard-clauses.yaml|occ-1": 15,
    "crush/2025-08-30-internal_db|renderer-guard-clauses.yaml|occ-2": 15,
    "crush/2025-08-30-internal_db|renderer-guard-clauses.yaml|occ-3": 15,
    "crush/2025-08-30-internal_db|renderer-guard-clauses.yaml|occ-4": 15,
    "crush/2025-08-30-internal_db|renderer-guard-clauses.yaml|occ-5": 15,
    "crush/2025-08-30-internal_db|renderer-guard-clauses.yaml|occ-6": 15,
    "crush/2025-08-30-internal_db|renderer-guard-clauses.yaml|occ-7": 15,
    "crush/2025-08-30-internal_db|renderer-guard-clauses.yaml|occ-8": 15,
    # ducktape/2025-11-26-00 - single-file issues
    "ducktape/2025-11-26-00|agentiddata-wrapper-class.yaml|occ-0": 15,
    "ducktape/2025-11-26-00|common-diff-trunk.yaml|occ-0": 15,
    "ducktape/2025-11-26-00|delete-install-wrapper.yaml|occ-0": 15,
    # === MEDIUM (P20): Each occurrence in its own file, straightforward ===
    # config-nil-chains - each occurrence in its own file
    "crush/2025-08-30-internal_db|config-nil-chains.yaml|occ-0": 20,
    "crush/2025-08-30-internal_db|config-nil-chains.yaml|occ-1": 20,
    "crush/2025-08-30-internal_db|config-nil-chains.yaml|occ-2": 20,
    # control-flow-complexity - each in its own file
    "crush/2025-08-30-internal_db|control-flow-complexity.yaml|occ-0": 20,
    "crush/2025-08-30-internal_db|control-flow-complexity.yaml|occ-1": 20,
    "crush/2025-08-30-internal_db|control-flow-complexity.yaml|occ-2": 20,
    "crush/2025-08-30-internal_db|control-flow-complexity.yaml|occ-3": 20,
    "crush/2025-08-30-internal_db|control-flow-complexity.yaml|occ-4": 20,
    "crush/2025-08-30-internal_db|control-flow-complexity.yaml|occ-5": 20,
    "crush/2025-08-30-internal_db|control-flow-complexity.yaml|occ-6": 20,
    # hardcoded-timeouts - each in its own file
    "crush/2025-08-30-internal_db|hardcoded-timeouts.yaml|occ-0": 20,
    "crush/2025-08-30-internal_db|hardcoded-timeouts.yaml|occ-1": 20,
    "crush/2025-08-30-internal_db|hardcoded-timeouts.yaml|occ-2": 20,
    "crush/2025-08-30-internal_db|hardcoded-timeouts.yaml|occ-3": 20,
    "crush/2025-08-30-internal_db|hardcoded-timeouts.yaml|occ-4": 20,
    "crush/2025-08-30-internal_db|hardcoded-timeouts.yaml|occ-5": 20,
    "crush/2025-08-30-internal_db|hardcoded-timeouts.yaml|occ-6": 20,
    "crush/2025-08-30-internal_db|hardcoded-timeouts.yaml|occ-7": 20,
    "crush/2025-08-30-internal_db|hardcoded-timeouts.yaml|occ-8": 20,
    # timestamp-type-inconsistency - each in its own file
    "crush/2025-08-30-internal_db|timestamp-type-inconsistency.yaml|occ-0": 20,
    "crush/2025-08-30-internal_db|timestamp-type-inconsistency.yaml|occ-1": 20,
    "crush/2025-08-30-internal_db|timestamp-type-inconsistency.yaml|occ-2": 20,
    "crush/2025-08-30-internal_db|timestamp-type-inconsistency.yaml|occ-3": 20,
    "crush/2025-08-30-internal_db|timestamp-type-inconsistency.yaml|occ-4": 20,
    "crush/2025-08-30-internal_db|timestamp-type-inconsistency.yaml|occ-5": 20,
    "crush/2025-08-30-internal_db|timestamp-type-inconsistency.yaml|occ-6": 20,
    "crush/2025-08-30-internal_db|timestamp-type-inconsistency.yaml|occ-7": 20,
    "crush/2025-08-30-internal_db|timestamp-type-inconsistency.yaml|occ-8": 20,
    "crush/2025-08-30-internal_db|timestamp-type-inconsistency.yaml|occ-9": 20,
    "crush/2025-08-30-internal_db|timestamp-type-inconsistency.yaml|occ-10": 20,
    # path-schema-docs-mismatch - each in its own file
    "crush/2025-08-30-internal_db|path-schema-docs-mismatch.yaml|occ-0": 20,
    "crush/2025-08-30-internal_db|path-schema-docs-mismatch.yaml|occ-1": 20,
    # ducktape issues - single file local
    "ducktape/2025-11-26-00|agent-id-fields-use-str.yaml|occ-0": 20,
    "ducktape/2025-11-26-00|allow-case-two-ids.yaml|occ-0": 20,
    "ducktape/2025-11-26-00|ask-approved-inflight.yaml|occ-0": 20,
    "ducktape/2025-11-20-00|collection-params-empty-tuple.yaml|occ-2": 20,
    "ducktape/2025-11-20-00|collection-params-empty-tuple.yaml|occ-3": 20,
    "ducktape/2025-11-20-00|proposal-id-type-mismatch.yaml|occ-0": 20,
    "ducktape/2025-11-20-00|proposal-id-type-mismatch.yaml|occ-1": 20,
    "ducktape/2025-11-20-00|proposal-id-type-mismatch.yaml|occ-2": 20,
    # === SKIP (P9999): Cross-file implications, should NOT set field ===
    # facade-law-of-demeter - dual framing (consumer vs interface design)
    "crush/2025-08-30-internal_db|facade-law-of-demeter.yaml|occ-0": 9999,
    "crush/2025-08-30-internal_db|facade-law-of-demeter.yaml|occ-1": 9999,
    "crush/2025-08-30-internal_db|facade-law-of-demeter.yaml|occ-2": 9999,
}


def get_priority(issue: dict) -> int:
    """Get priority for an issue. Lower = easier = show first."""
    key = f"{issue['project']}/{issue['snapshot']}|{issue['issue_file']}|{issue['occurrence_id']}"
    return PRIORITY_ORDER.get(key, 1000)


def main():
    specimens_root = Path(__file__).parent.parent

    # Find all issue YAML files
    issues = []
    for issue_path in specimens_root.rglob("issues/*.yaml"):
        # Skip pyright_watch_report (single-file snapshot)
        if "pyright_watch_report" in str(issue_path):
            continue

        with issue_path.open() as f:
            try:
                data = yaml.safe_load(f)
            except yaml.YAMLError:
                continue

        if not data or not data.get("should_flag"):
            continue

        for occ in data.get("occurrences", []):
            # Skip if already has the field
            if occ.get("graders_match_only_if_reported_on") is not None:
                continue

            files = occ.get("files", {})
            if len(files) != 1:
                continue  # Only single-file occurrences

            file_path = next(iter(files.keys()))
            line_spec = files[file_path]
            snapshot = issue_path.parent.parent.name
            project = issue_path.parent.parent.parent.name

            issues.append(
                {
                    "project": project,
                    "snapshot": snapshot,
                    "issue_file": issue_path.name,
                    "issue_path": issue_path,
                    "occurrence_id": occ.get("occurrence_id", "occ-0"),
                    "file": file_path,
                    "lines": normalize_lines(line_spec),
                    "rationale": data.get("rationale", ""),
                    "note": occ.get("note"),
                }
            )

    # Group by project/snapshot
    by_snapshot = defaultdict(list)
    for issue in issues:
        key = f"{issue['project']}/{issue['snapshot']}"
        by_snapshot[key].append(issue)

    # Generate markdown
    lines = [
        "# Issues Missing graders_match_only_if_reported_on",
        "",
        f"Total: {len(issues)} single-file occurrences",
        "",
    ]

    # Sort snapshots by descending number of issues
    for snapshot_key in sorted(by_snapshot.keys(), key=lambda k: -len(by_snapshot[k])):
        snapshot_issues = by_snapshot[snapshot_key]
        lines.append(f"## {snapshot_key} ({len(snapshot_issues)})")
        lines.append("")

        # Sort by priority (lower first), then by issue file name
        for issue in sorted(snapshot_issues, key=lambda x: (get_priority(x), x["issue_file"], x["occurrence_id"])):
            priority = get_priority(issue)
            if priority == 9999:
                priority_marker = " [SKIP - cross-file]"
            elif priority == 1000:
                priority_marker = ""
            else:
                priority_marker = f" [P{priority}]"
            lines.append(f"### `{issue['issue_file']}` / `{issue['occurrence_id']}`{priority_marker}")
            lines.append(f"File: `{issue['file']}`")

            # Full rationale as blockquote
            rationale = issue["rationale"].strip()
            if rationale:
                for rationale_line in rationale.split("\n"):
                    lines.append(f"> {rationale_line}")

            # Occurrence-level note if present
            if issue.get("note"):
                lines.append(">")
                lines.append(f"> **Note:** {issue['note']}")

            # Get context from source file
            snapshot_dir = issue["issue_path"].parent.parent
            # Check for code/ subdirectory (vcs: local with root: code)
            source_file = snapshot_dir / "code" / issue["file"]
            if not source_file.exists():
                source_file = snapshot_dir / issue["file"]

            if source_file.exists() and issue["lines"]:
                try:
                    source_lines = source_file.read_text().splitlines()
                    lines.append("```")
                    for start, end in issue["lines"]:
                        # Show +/- 5 context
                        ctx_start = max(1, start - 5)
                        ctx_end = min(len(source_lines), end + 5)
                        for i in range(ctx_start, ctx_end + 1):
                            if i <= len(source_lines):
                                marker = ">>>" if start <= i <= end else "   "
                                lines.append(f"{marker} {i:4d}: {source_lines[i - 1]}")
                        if (start, end) != issue["lines"][-1]:
                            lines.append("   ...")
                    lines.append("```")
                except Exception:
                    pass

            lines.append("")

        lines.append("")

    output_path = specimens_root / "pending-graders-match-labels.md"
    output_path.write_text("\n".join(lines))
    print(f"Wrote {len(issues)} issues to {output_path}")


if __name__ == "__main__":
    main()
