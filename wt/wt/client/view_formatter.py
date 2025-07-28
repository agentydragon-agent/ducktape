import os
from pathlib import Path

import click
from colorama import Style
from tabulate import tabulate

from ..shared.github_models import PRInfo, PRState, PRStatus
from ..shared.protocol import StatusResult

# PR status display mapping - moved from formatters.py
PR_STATUS_DISPLAY_MAP = {
    "merged": ("✅", "already merged"),
    "closed": ("❌", "closed"),
    "can merge": ("🟢", "can merge"),
    "conflict": ("🔴", "has conflict"),
    "open": ("🟡", "open"),
}


def format_sync_status(ahead: int, behind: int) -> str:
    """Format sync status with proper alignment - fixes double formatting issue."""
    if ahead == 0 and behind == 0:
        return "          "  # Fixed width for alignment

    left = f"{behind:>4}↓" if behind > 0 else "     "
    right = f"↑{ahead:<4}" if ahead > 0 else "     "
    content = f"{left} {right}"

    return f"{Style.DIM}{content}{Style.RESET_ALL}"


class ViewFormatter:
    def __init__(self):
        pass

    def format_list_with_more(self, items: list[str], max_items: int = 3) -> str:
        if len(items) <= max_items:
            return ", ".join(items)
        shown = ", ".join(items[:max_items])
        return f"{shown} and {len(items) - max_items} more"

    def make_hyperlink(self, url: str, text: str) -> str:
        if os.getenv("TERM_PROGRAM") in ("iTerm.app", "vscode") or os.getenv("COLORTERM"):
            return f"\033]8;;{url}\007{text}\033]8;;\007"
        return text

    def get_pr_status_text(
        self, pr_state: PRState, pr_mergeable, is_draft: bool = False, merged_at: str | None = None,
    ) -> str:
        # Show draft status first if it's a draft
        if is_draft:
            return "draft"

        # Distinguish between merged and closed based on merged_at
        if pr_state == PRState.CLOSED:
            if merged_at:
                return "merged"
            return "closed"
        if pr_state == PRState.OPEN:
            if pr_mergeable is None:
                return PRStatus.OPEN_UNKNOWN.display_text
            if pr_mergeable:
                return PRStatus.OPEN_MERGEABLE.display_text
            return PRStatus.OPEN_CONFLICTING.display_text
        return pr_state.value.lower()

    def format_status_row(
        self, name: str, status: StatusResult, pr_info: PRInfo | None, name_width: int = 22,
    ) -> str:
        """Format a status row with nice alignment."""
        # Commit hash - vertically aligned column
        commit_short = status.commit_info.short_hash if status.commit_info else "????????"

        # Ahead/behind status with light colors, aligned around center point
        sync_status = format_sync_status(status.ahead_count, status.behind_count)

        # Working directory status
        if status.has_dirty_files or status.has_untracked_files:
            changes = []
            if status.has_dirty_files:
                changes.append("M")
            if status.has_untracked_files:
                changes.append("?")
            work_status = "+".join(changes)
        else:
            work_status = "clean"

        # GitHub PR status with clickable hyperlinks and clear text
        pr_status = ""
        if pr_info and pr_info.github_pr:
            pr = pr_info.github_pr
            pr_number = pr["number"]
            pr_state = PRState(pr["state"])

            # Create clickable hyperlink - fall back to plain text if not supported
            clickable_link = self.make_hyperlink(f"http://go/pull/{pr_number}", f"#{pr_number}")

            # Add lines changed info if available
            lines_info = ""
            if pr.get("additions") is not None and pr.get("deletions") is not None:
                lines_info = f" +{pr['additions']}/-{pr['deletions']}"

            pr_status_text = self.get_pr_status_text(
                pr_state, pr.get("mergeable"), pr.get("draft", False), pr.get("merged_at"),
            )

            pr_status = f"{clickable_link} {pr_status_text}{lines_info}"

        # Format with nice alignment - commitish as separate column
        # Note: sync_status contains ANSI codes, so we pad the content to exactly 9 chars
        return (
            f"{name:<{name_width}} {commit_short:<10} {sync_status} {work_status:<10} {pr_status}"
        )

    def render_worktree_list(self, worktrees: list[tuple[str, Path, bool]]) -> None:
        if worktrees:
            click.echo("Available worktrees:")
            for name, path, exists in worktrees:
                status = "exists" if exists else "missing"
                click.echo(f"{name}: {path} ({status})")
        else:
            click.echo("No worktrees found")

    def _get_commit_column(self, status: StatusResult) -> str:
        """Get commit hash column."""
        return status.commit_info.short_hash if status.commit_info else "????????"

    def _get_sync_column(self, status: StatusResult) -> str:
        """Get ahead/behind sync status column."""
        parts = []
        if status.behind_count > 0:
            parts.append(f"↓{status.behind_count}")
        if status.ahead_count > 0:
            parts.append(f"↑{status.ahead_count}")
        return "+".join(parts) if parts else ""

    def _get_work_status_column(self, status: StatusResult) -> str:
        """Get working directory status column."""
        if status.has_dirty_files or status.has_untracked_files:
            changes = []
            if status.has_dirty_files:
                changes.append("M")
            if status.has_untracked_files:
                changes.append("?")
            return "+".join(changes)
        return "clean"

    def _get_pr_link_column(self, status: StatusResult) -> str:
        """Get PR link column."""
        if not (status.pr_info and status.pr_info.github_pr):
            return ""
        
        pr = status.pr_info.github_pr
        pr_number = pr["number"]
        return self.make_hyperlink(f"http://go/pull/{pr_number}", f"#{pr_number}")

    def _get_pr_status_column(self, status: StatusResult) -> str:
        """Get PR status text column."""
        if not (status.pr_info and status.pr_info.github_pr):
            return ""
        
        pr = status.pr_info.github_pr
        pr_state = PRState(pr["state"])
        return self.get_pr_status_text(
            pr_state, pr.get("mergeable"), pr.get("draft", False), pr.get("merged_at"),
        )

    def _get_pr_changes_column(self, status: StatusResult) -> str:
        """Get PR changes (+lines/-lines) column."""
        if not (status.pr_info and status.pr_info.github_pr):
            return ""
        
        pr = status.pr_info.github_pr
        if pr.get("additions") is not None and pr.get("deletions") is not None:
            return f"+{pr['additions']}/-{pr['deletions']}"
        return ""

    def render_worktree_status_all(self, sorted_items: list[tuple[str, StatusResult]]) -> None:
        if not sorted_items:
            click.echo("🤷 No worktrees found")
            return

        # Build table data
        table_data = []
        for name, status in sorted_items:
            # Build PR info as a single combined column if it exists
            pr_info = ""
            pr_link = self._get_pr_link_column(status)
            pr_status = self._get_pr_status_column(status) 
            pr_changes = self._get_pr_changes_column(status)
            
            if pr_link:
                pr_parts = [pr_link]
                if pr_status:
                    pr_parts.append(pr_status)
                if pr_changes:
                    pr_parts.append(pr_changes)
                pr_info = " ".join(pr_parts)

            table_data.append([
                name,
                self._get_commit_column(status),
                self._get_work_status_column(status),
                pr_info,
            ])

        # Render table with no headers, no grid lines, just clean aligned columns
        click.echo(tabulate(table_data, tablefmt="plain"))

    def render_worktree_status_single(
        self, worktree_name: str, status: StatusResult, pr_info: PRInfo | None,
    ) -> None:
        click.echo(f"📊 Status for worktree: {worktree_name}")
        click.echo(f"🔄 {self.format_status_row(worktree_name, status, pr_info)}")

        # Show recent commit details
        if status.commit_info:
            click.echo(f"💬 Last commit: {status.commit_info.message}")
            click.echo(
                f"👤 Author: {status.commit_info.author} ({status.commit_info.date})",
            )
        else:
            click.echo("💬 Last commit: (unknown)")
            click.echo("👤 Author: (unknown)")

        # Show file status flags (detailed file lists not available in protocol)
        if status.has_dirty_files:
            click.echo("📝 Has modified files")
        if status.has_untracked_files:
            click.echo("❓ Has untracked files")

        # Show PR details if available
        if pr_info and pr_info.github_pr:
            pr = pr_info.github_pr
            pr_number = pr["number"]
            pr_state = PRState(pr["state"])

            # Create clickable link for detailed view
            click.echo(
                f"🔗 PR #{pr_number} ({self.make_hyperlink(f'http://go/pull/{pr_number}', f'go/pull/{pr_number}')})",
            )

            # Format detailed PR status
            status_text = self.get_pr_status_text(
                pr_state, pr.get("mergeable"), pr.get("draft", False), pr.get("merged_at"),
            )
            if status_text in PR_STATUS_DISPLAY_MAP:
                icon, message = PR_STATUS_DISPLAY_MAP[status_text]
                click.echo(f"{icon} Status: This PR {message}")
            else:
                click.echo(f"Status: {status_text}")

    def render_worktree_processes(self, worktree_path: Path, processes) -> None:
        if not processes:
            click.echo("  ✓ No running processes found")
            return

        proc_strings = [f"PID {p.pid} ({p.name})" for p in processes]
        proc_info = self.format_list_with_more(proc_strings)

        click.echo(f"  ⚠️  Found running processes: {proc_info}")

    def render_worktree_removal_progress(self, name: str, worktree_path: Path) -> None:
        click.echo(f"🔍 Checking worktree '{name}' for removal...")
        click.echo("  Checking for running processes...")

    def render_worktree_removal_git_status(self, name: str, has_changes: bool, force: bool) -> None:
        click.echo("  Checking for uncommitted changes...")
        if not has_changes:
            click.echo("  ✓ Working directory is clean")
        elif force:
            click.echo("  ⚠️  Found uncommitted changes (using --force)")
        else:
            # This should trigger an error in the business logic
            pass

    def render_worktree_removal_confirmation(self, name: str, worktree_path: Path) -> None:
        click.echo(f"⚠️  About to permanently remove worktree '{name}' at {worktree_path}")

    def render_worktree_removal_success(self, name: str) -> None:
        click.echo(f"✅ Successfully removed worktree '{name}'")

    def render_worktree_creation_progress(self, worktree_path: Path) -> None:
        """Render worktree creation progress."""
        click.echo(f"Creating worktree at: {worktree_path}")

    def render_hydration_progress(self, strategy_name: str) -> None:
        """Render hydration progress."""
        click.echo(f"Hydrating worktree via {strategy_name}...")
