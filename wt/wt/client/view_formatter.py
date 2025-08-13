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
        if os.getenv("TERM_PROGRAM") in ("iTerm.app", "vscode") or os.getenv(
            "COLORTERM",
        ):
            return f"\033]8;;{url}\007{text}\033]8;;\007"
        return text

    def get_pr_status_text(
        self,
        pr_state: PRState,
        pr_mergeable,
        is_draft: bool = False,
        merged_at: str | None = None,
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
        self,
        name: str,
        status: StatusResult,
        pr_info: PRInfo | None,
        name_width: int = 22,
    ) -> str:
        """Format a status row with nice alignment."""
        # Commit hash - vertically aligned column
        commit_short = (
            status.commit_info.short_hash if status.commit_info else "ERROR"
        )

        # Ahead/behind status with light colors, aligned around center point
        sync_status = format_sync_status(status.ahead_count, status.behind_count)

        # Working directory status
        if not status.is_cached:
            work_status = "unknown"
        elif status.has_dirty_files or status.has_untracked_files:
            changes = []
            if status.has_dirty_files:
                changes.append("modified")
            if status.has_untracked_files:
                changes.append("untracked")
            work_status = "+".join(changes)
        else:
            work_status = "clean"
        if status.is_cached and status.is_stale:
            work_status += " (stale)"

        # GitHub PR status with clickable hyperlinks and clear text
        pr_status = ""
        if pr_info and pr_info.github_pr:
            pr = pr_info.github_pr
            pr_number = pr["number"]
            pr_state = PRState(pr["state"])

            # Create clickable hyperlink - fall back to plain text if not supported
            clickable_link = self.make_hyperlink(
                f"http://go/pull/{pr_number}",
                f"#{pr_number}",
            )

            # Add lines changed info if available
            lines_info = ""
            if pr.get("additions") is not None and pr.get("deletions") is not None:
                lines_info = f" +{pr['additions']}/-{pr['deletions']}"

            pr_status_text = self.get_pr_status_text(
                pr_state,
                pr.get("mergeable"),
                pr.get("draft", False),
                pr.get("merged_at"),
            )

            pr_status = f"{clickable_link} {pr_status_text}{lines_info}"

        # Format with nice alignment - commitish as separate column
        # Note: sync_status contains ANSI codes, so we pad the content to exactly 9 chars
        return f"{name:<{name_width}} {commit_short:<10} {sync_status} {work_status:<10} {pr_status}"

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
        return status.commit_info.short_hash if status.commit_info else "ERROR"
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
        if not status.is_cached:
            return "unknown"
        if status.has_dirty_files or status.has_untracked_files:
            changes = []
            if status.has_dirty_files:
                changes.append("M")
            if status.has_untracked_files:
                changes.append("?")
            s = "+".join(changes)
            return f"{s} (stale)" if status.is_stale else s
        return "clean (stale)" if status.is_stale else "clean"

    def _get_pr_link_column(self, status: StatusResult) -> str:
        """Get PR link column."""
        if not status.pr_info:
            return ""
        if status.pr_info.github_pr:
            pr = status.pr_info.github_pr
            pr_number = pr["number"]
            return self.make_hyperlink(f"http://go/pull/{pr_number}", f"#{pr_number}")
        if status.pr_info.pr_data:
            pr_number = status.pr_info.pr_data.pr_number
            return self.make_hyperlink(f"http://go/pull/{pr_number}", f"#{pr_number}")
        return ""

    def _get_pr_status_column(self, status: StatusResult) -> str:
        """Get PR status text column."""
        if not status.pr_info:
            return ""
        if status.pr_info.github_pr:
            pr = status.pr_info.github_pr
            pr_state = PRState(pr["state"])
            return self.get_pr_status_text(
                pr_state,
                pr.get("mergeable"),
                pr.get("draft", False),
                pr.get("merged_at"),
            )
        if status.pr_info.pr_data:
            d = status.pr_info.pr_data
            return self.get_pr_status_text(d.pr_state, d.mergeable, d.draft, d.merged_at)
        return ""

    def _get_pr_changes_column(self, status: StatusResult) -> str:
        """Get PR changes (+lines/-lines) column."""
        if not status.pr_info:
            return ""
        if status.pr_info.github_pr:
            pr = status.pr_info.github_pr
            if pr.get("additions") is not None and pr.get("deletions") is not None:
                return f"+{pr['additions']}/-{pr['deletions']}"
            return ""
        if status.pr_info.pr_data:
            d = status.pr_info.pr_data
            if d.additions is not None and d.deletions is not None:
                return f"+{d.additions}/-{d.deletions}"
        return ""
    def render_top_status_bar(self, status_response) -> None:
        summary = status_response.readiness_summary
        components = status_response.components
        if not summary and not components:
            return
        discovery = "⟳" if (summary and summary.discovery_scanning) else "✓"
        github_state = "ok"
        if components and components.github:
            github_state = components.github.state.value
        elif summary:
            github_state = summary.github.value
        x_of_y = (
            f"{summary.with_gitstatusd}/{summary.total_worktrees}" if summary else "-/-"
        )
        click.echo(
            f"{discovery} discovery | gitstatusd {x_of_y} | github {github_state}",
        )

    def render_worktree_status_all(
        self,
        sorted_items: list[tuple[str, StatusResult]],
        status_response=None,
    ) -> None:
        if not sorted_items:
            click.echo("🤷 No worktrees found")
            return

        # Build table data
        table_data = []
        for name, status in sorted_items:
            pr_info = ""
            pr_link = self._get_pr_link_column(status)
            pr_status = self._get_pr_status_column(status)
            pr_changes = self._get_pr_changes_column(status)
            state_map = {
                "running": "running",
                "restarting": "restarting",
                "failed": "failed",
                "stopped": "stopped",
                "starting": "starting",
            }
            state = state_map.get(status.gitstatusd_state or "", "")
            if pr_link:
                pr_parts = [pr_link]
                if pr_status:
                    pr_parts.append(pr_status)
                if pr_changes:
                    pr_parts.append(pr_changes)
                pr_info = " ".join(pr_parts)

            table_data.append(
                [
                    name,
                    self._get_commit_column(status),
                    self._get_work_status_column(status),
                    state,
                    pr_info,
                ],
            )

        # Render table with no headers, no grid lines, just clean aligned columns
        click.echo(tabulate(table_data, tablefmt="plain"))

        # Aggregate and show errors below the table to avoid widening columns
        error_lines = []
        for name, status in sorted_items:
            if status.last_error:
                error_lines.append(f"{name}: {status.last_error}")
        if error_lines:
            click.echo("")
            click.echo("Errors:")
            for ln in error_lines:
                click.echo(f"  - {ln}")
            log_path = os.getenv("WT_DIR")
            if log_path:
                click.echo(f"See daemon log: {Path(log_path) / 'daemon.log'}")

        # Component health summary
        if status_response and status_response.daemon_health:
            dh = status_response.daemon_health
            click.echo("")
            click.echo("Health:")
            click.echo(f"  - status: {dh.status}")
            if dh.last_error:
                click.echo(f"  - last_error: {dh.last_error}")
            click.echo(
                f"  - counters: github_errors={dh.github_errors}, gitstatusd_errors={dh.gitstatusd_errors}"
            )

    def render_worktree_status_single(
        self,
        worktree_name: str,
        status: StatusResult,
        pr_info: PRInfo | None,
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
                pr_state,
                pr.get("mergeable"),
                pr.get("draft", False),
                pr.get("merged_at"),
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

    def render_worktree_removal_git_status(
        self,
        name: str,
        has_changes: bool,
        force: bool,
    ) -> None:
        click.echo("  Checking for uncommitted changes...")
        if not has_changes:
            click.echo("  ✓ Working directory is clean")
        elif force:
            click.echo("  ⚠️  Found uncommitted changes (using --force)")
        else:
            # This should trigger an error in the business logic
            pass

    def render_worktree_removal_confirmation(
        self,
        name: str,
        worktree_path: Path,
    ) -> None:
        click.echo(
            f"⚠️  About to permanently remove worktree '{name}' at {worktree_path}",
        )

    def render_worktree_removal_success(self, name: str) -> None:
        click.echo(f"✅ Successfully removed worktree '{name}'")

    def render_worktree_creation_progress(self, worktree_path: Path) -> None:
        """Render worktree creation progress."""
        click.echo(f"Creating worktree at: {worktree_path}")

    def render_hydration_progress(self, strategy_name: str) -> None:
        """Render hydration progress."""
        click.echo(f"Hydrating worktree via {strategy_name}...")
