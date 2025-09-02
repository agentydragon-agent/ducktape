from __future__ import annotations

import argparse
from importlib.resources import files
from pathlib import Path

from . import specimen_runner as sr


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
    # Load packaged Markdown definitions and wrap each with a file tag that
    # encodes its path relative to the properties/ root, so cross-links are meaningful.
    props_root = Path(files("adgn_llm").joinpath("properties"))
    defs_dir = props_root / "definitions"
    parts: list[str] = []
    for md in sorted(defs_dir.rglob("*.md")):
        rel = md.relative_to(props_root)  # e.g., definitions/python/type-hints.md
        parts.append(f"<file path=\":/{rel.as_posix()}\">\n{md.read_text(encoding='utf-8')}\n</file>")
    return "\n\n".join(parts)


def _properties_block(properties_text: str, supplemental_section: str | None) -> list[str]:
    lines = ["Property definitions:", properties_text]
    if supplemental_section:
        lines.append(supplemental_section)
    return lines


def build_find_prompt(scope_text: str, supplemental_text: str | None = None) -> str:
    properties_text = _properties_text()
    supplemental_section = build_supplemental_section(supplemental_text)
    lines: list[str] = [
        "Analyze the codebase for violations of the properties defined below. Do not modify any files. Output only violations; do not list properties/files with 'No violations'. Produce a concise structured report.",
        "",
        *_scope_block(scope_text, static_action="analyze", ambiguity_tail="do not include anything outside it."),
        "",
        "Constraints:",
        "- Read-only sandbox: do not execute commands that modify files or the repo",
        "- You MAY run read-only commands to inspect context (e.g., `git status`, `git diff --unified=0`)",
        "- You MUST check every changed hunk within scope",
        "",
        "Reporting requirements:",
        "- For each violation: 1-line rationale and precise anchors (e.g., file:41–45, function names, or concise symbol paths)",
        "- For many similar cases, write one short description then follow with a compact list of cases (file:lines or symbol names).",
        "- Do not list properties/files without violations; omit any 'No violations' lines.",
        "- Do not include preparatory narration; print only the report.",
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
    # Use codex exec with long flags for model/sandbox; pass configs via -c
    cmd: list[str] = ["codex", "exec", "--model", model, "--sandbox", sandbox, "-C", str(workdir)]
    if extra_configs:
        for c in extra_configs:
            cmd.extend(["-c", c])
    if full_auto:
        cmd.append("--full-auto")
    if skip_git_repo_check:
        cmd.append("--skip-git-repo-check")
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

    # Specimen runner subcommand (integrated)
    p_spec = sub.add_parser("specimen", help="Run critic against a specimen by name/path")
    p_spec.add_argument("specimen", nargs="?", help="Specimen name (under properties/specimens), path to specimen dir, or path to manifest.yaml")
    p_spec.add_argument("--dry-run", action="store_true")
    p_spec.add_argument("--json", action="store_true", help="Request JSON output from critic")
    p_spec.add_argument("--embed-path", action="append", dest="embed_paths", help="Extra paths to embed into the prompt")
    p_spec.add_argument("--gitconfig", help="Path to a gitconfig to use (private repos fallback)")

    args = parser.parse_args(argv)

    if args.command == "specimen":
        base = sr.find_specimens_base()
        manifest_path = sr.resolve_manifest_arg(args.specimen, base)
        if manifest_path is None:
            names = sr.list_specimen_names(base)
            if not names:
                print(f"No specimens found under: {base}")
                return 2
            print("Available specimens:")
            for n in names:
                print(" -", n)
            return 0
        # Validate gitconfig if provided
        gitconfig_path = None
        if args.gitconfig:
            p = Path(args.gitconfig).expanduser().resolve()
            if not p.exists():
                print(f"ERROR: --gitconfig file not found: {p}")
                return 2
            gitconfig_path = str(p)
        cfg = sr.RunnerConfig(dry_run=args.dry_run, output_json=args.json, embed_paths=args.embed_paths, gitconfig=gitconfig_path)
        return sr.run_critic(manifest_path, cfg)

    elif args.command in ("find", "enforce"):
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
    else:
        parser.error("command is required")


if __name__ == "__main__":
    raise SystemExit(main())
