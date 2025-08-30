from __future__ import annotations

import argparse
from importlib.resources import files
from pathlib import Path


def build_supplemental_section(supplemental_text: str | None) -> str:
    if not supplemental_text:
        return ""
    lines = [
        "",
        "Supplemental files (golden reviews):",
        "These cover both the formal properties defined below and additional not-yet-formalized feedback.",
        "Your analysis must ensure code passes all formal property definitions and also the additional criteria captured here.",
        "Generalize patterns from these supplements and flag similar issues in the input code.",
        supplemental_text,
    ]
    return "\n".join(lines)


def read_embedded_paths(paths: list[Path]) -> str:
    files_to_embed: list[Path] = []
    for q in paths:
        p = Path(q)
        if p.is_file():
            files_to_embed.append(p)
    blocks: list[str] = []
    for p in sorted(files_to_embed, key=lambda x: str(x)):
        try:
            content = p.read_text(encoding="utf-8")
        except Exception:
            continue
        blocks.append("\n".join([f"<file path=\":/{p}\">", content, "</file>"]))
    return "\n\n".join(blocks)


def _scope_block(scope_text: str, *, static_action: str, ambiguity_tail: str) -> list[str]:
    return [
        "Scope (freeform):",
        f"- {scope_text}",
        "",
        "Scope interpretation rules:",
        "- The scope may describe either:",
        '  1) a Git diff range (e.g., "between merge-base with master and 2 commits before HEAD"), or',
        "  2) a static set of files/paths",
        "- If it's a diff description: resolve to a concrete diff range, enumerate files and hunks, and use `git diff --unified=0` for references.",
        f"- If it's a static file set: {static_action} only those files.",
        f"- On ambiguity, choose the most conservative interpretation, state the resolved scope, and {ambiguity_tail}",
    ]


def _properties_text() -> str:
    # Load packaged Markdown definitions
    base = files("adgn_llm.properties").joinpath("definitions")
    texts: list[str] = []
    for md in sorted(base.rglob("*.md")):
        texts.append(md.read_text(encoding="utf-8"))
    return "\n\n".join(texts)


def _properties_block(properties_text: str, supplemental_section: str | None) -> list[str]:
    lines = ["Property definitions:", properties_text]
    if supplemental_section:
        lines.append(supplemental_section)
    return lines


def build_find_prompt(scope_text: str, supplemental_text: str | None = None) -> str:
    properties_text = _properties_text()
    supplemental_section = build_supplemental_section(supplemental_text)
    lines: list[str] = [
        "Analyze the codebase for violations of the properties defined below. Do not modify any files. Produce a structured textual report.",
        "",
        *_scope_block(scope_text, static_action="analyze", ambiguity_tail="do not include anything outside it."),
        "",
        "Constraints:",
        "- Read-only sandbox: do not execute commands that modify files or the repo",
        "- You MAY run read-only commands to inspect context (e.g., `git status`, `git diff --unified=0`)",
        "- You MUST check every changed hunk within scope",
        "",
        "Reporting requirements:",
        "- Group by file, then by property title",
        "- For each violation: include short rationale and line references (from `git diff --unified=0` or file line numbers)",
        '- If no violations for a file, explicitly state "No violations"',
        "",
        *_properties_block(properties_text, supplemental_section),
    ]
    return "\n".join(lines).strip()


def build_enforce_prompt(scope_text: str, supplemental_text: str | None = None) -> str:
    properties_text = _properties_text()
    supplemental_section = build_supplemental_section(supplemental_text)
    lines: list[str] = [
        "Ensure code within the described scope conforms to the properties defined below and refactor as needed to satisfy them without altering behavior.",
        "",
        *_scope_block(scope_text, static_action="edit", ambiguity_tail="avoid touching anything outside it unless required by the editing policy below."),
        "",
        "Editing policy:",
        "- Prefer minimal, localized edits within the scoped hunks/sections.",
        "- You MAY edit outside the scoped hunks/sections ONLY when necessary to bring the scoped changes and any code you touched into full compliance with all properties (e.g., moving imports to the top of file).",
        "- If such edits cascade (A requires B, which requires C, ...), keep fixing until everything you changed and everything originally in scope is compliant, then stop.",
        "- Do NOT perform broad or unrelated refactors beyond what is required for compliance.",
        "- Do not commit changes.",
        "- After edits, run existing linters/formatters if present (e.g., ruff, pre-commit) and re-verify against properties.",
        "",
        "Requirements:",
        "- You MUST check every changed hunk within the resolved scope",
        "- You MUST bring all scoped files/sections and any cascaded edits into compliance with ALL property definition files",
        "",
        *_properties_block(properties_text, supplemental_section),
        "",
        "Operational guidance:",
        "- Ask for confirmation before any destructive action (deletes/mass renames). Keep changes within the workspace.",
        "- If a property appears to conflict with code behavior, explain the conflict and propose the smallest safe change in your final report.",
        "",
        "Deliverables:",
        "- Apply changes directly in the workspace.",
        "- Print a concise change report as your final message: files changed, properties addressed per file, and any remaining violations you could not safely fix.",
    ]
    return "\n".join(lines).strip()


def build_cmd(model: str, workdir: Path, *, sandbox: str, skip_git_repo_check: bool, full_auto: bool, extra_configs: list[str] | None = None) -> list[str]:
    cmd = [
        "codex",
        f"--model={model}",
        f"--sandbox={sandbox}",
        f"-C{workdir}",
    ]
    if skip_git_repo_check:
        cmd.append("--skip-git-repo-check")
    if full_auto:
        cmd.append("--full-auto")
    for c in (extra_configs or []):
        cmd.extend(["--config", c])
    return cmd


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="adgn-llm codex properties CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("workdir")
    common.add_argument("scope")
    common.add_argument("-m", "--model", default="gpt-5")
    common.add_argument("--dry-run", action="store_true")
    common.add_argument("--skip-git-repo-check", action="store_true")
    common.add_argument("--full-auto", action="store_true")

    sub.add_parser("find", parents=[common])
    sub.add_parser("enforce", parents=[common])

    args = parser.parse_args(argv)
    workdir = Path(args.workdir).resolve()

    if args.command == "find":
        prompt = build_find_prompt(args.scope)
        cmd = build_cmd(args.model, workdir, sandbox="read-only", skip_git_repo_check=args.skip_git_repo_check, full_auto=args.full_auto)
    else:
        prompt = build_enforce_prompt(args.scope)
        cmd = build_cmd(
            args.model,
            workdir,
            sandbox="workspace-write",
            skip_git_repo_check=args.skip_git_repo_check,
            full_auto=args.full_auto,
            extra_configs=['sandbox_permissions=["disk-full-read-access"]'],
        )

    if args.dry_run:
        print(" ".join(cmd))
        print()
        print(prompt)
        return 0

    # Stream to subprocess stdin
    import subprocess
    try:
        return subprocess.run(cmd, check=False, input=prompt, text=True).returncode
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
