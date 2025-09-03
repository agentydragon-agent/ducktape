from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from collections.abc import Iterable
from importlib.resources import files
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import tiktoken
import yaml

from .specimen_frontmatter import GitHubSource, GitSource, LocalSource, SpecimenManifest


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
        blocks.append("\n".join([f'<file path=":/{p}">', content, "</file>"]))
    return "\n\n".join(blocks)


def _scope_block(
    scope_text: str, *, static_action: str, ambiguity_tail: str
) -> list[str]:
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
        parts.append(
            f'<file path=":/{rel.as_posix()}">\n{md.read_text(encoding="utf-8")}\n</file>'
        )
    return "\n\n".join(parts)


def _properties_block(
    properties_text: str, supplemental_section: str | None
) -> list[str]:
    lines = ["Property definitions:", properties_text]
    if supplemental_section:
        lines.append(supplemental_section)
    return lines


# Recognized QA tools (names shown to users/agents)
RECOGNIZED_TOOLS: list[str] = [
    "ruff",
    "mypy",
    "pyright",
    "vulture",
    "bandit",
    "pip-audit",
    "safety",
    "codespell",
    "pyupgrade",
    "refurb",
    "flynt",
    "pydocstyle",
    "interrogate",
    "import-linter",
    "semgrep",
    "radon",
    "xenon",
    "pylint",
    "lizard",
    "clonedigger",
    "coverage",
    "diff-cover",
    "jscpd",
    "jscpd(npx)",
]

# Human-facing catalog for CLI table (name, category, description)
TOOL_CATALOG: list[tuple[str, str, str]] = [
    ("ruff", "lint/format", "Fast linter/formatter replacing flake8/isort/pyupgrade"),
    ("mypy", "typing", "Static type checker"),
    ("pyright", "typing", "Fast static type checker"),
    ("vulture", "dead code", "Find unused code"),
    ("bandit", "security", "Find common security issues"),
    ("pip-audit", "security", "Audit Python dependencies for CVEs"),
    ("safety", "security", "Scan dependencies for known vulnerabilities"),
    ("codespell", "style", "Spell checker for code/docs"),
    ("pyupgrade", "modernize", "Rewrite code to modern Python syntax"),
    ("refurb", "modernize", "Refactor suggestions"),
    ("flynt", "modernize", "Convert to f-strings"),
    ("pydocstyle", "docs", "Docstring style checker"),
    ("interrogate", "docs", "Docstring coverage"),
    ("import-linter", "architecture", "Enforce import layer contracts"),
    ("semgrep", "patterns", "Multi-language pattern rules with autofix"),
    ("radon", "complexity", "Cyclomatic complexity/maintainability"),
    ("xenon", "complexity", "CI gate using radon thresholds"),
    ("pylint", "duplicates", "Includes duplicate-code (R0801) detector"),
    ("lizard", "duplicates", "Complexity and clone detection"),
    ("clonedigger", "duplicates", "Clone detector for Python"),
    ("coverage", "coverage", "Code coverage measurement"),
    ("diff-cover", "coverage", "Changed-line coverage gating"),
    ("jscpd", "duplicates(node)", "Language-agnostic copy/paste detector (via npx)"),
]


def _format_tools_table(available: list[str]) -> str:
    avail_set = set(available)
    header = ("Avail", "Tool", "Category", "Description")
    lines = [
        f"{header[0]:<5}  {header[1]:<12}  {header[2]:<14}  {header[3]}",
        f"{'-' * 5}  {'-' * 12}  {'-' * 14}  {'-' * 40}",
    ]
    for name, cat, desc in TOOL_CATALOG:
        status = (
            "yes"
            if name in avail_set or (name == "jscpd" and "jscpd(npx)" in avail_set)
            else "no"
        )
        lines.append(f"{status:<5}  {name:<12}  {cat:<14}  {desc}")
    return "\n".join(lines)


def _tools_and_flow_block(available_tools: list[str]) -> list[str]:
    detected = ", ".join(available_tools) if available_tools else "(none)"
    return [
        "",
        f"Detected analysis tools on PATH: {detected}",
        "Suggested order (analyze): ruff check → mypy/pyright → vulture → bandit → dupes (pylint R0801/lizard) → radon (report).",
        "Suggested order (fix): ruff --fix → pyupgrade --py312-plus → refurb → flynt; re-run ruff check.",
        "After applying fixes, run the analysis tools again and include any remaining issues.",
        "Include a short 'Missing tools' note in your final report if any commonly useful tools were unavailable and how that limited you (if at all).",
    ] + (
        [
            "Tools with special invocation:",
            "- jscpd(npx): npx --yes --no-install jscpd --path . --reporters json --ignore 'node_modules/**'",
        ]
        if "jscpd(npx)" in available_tools
        else []
    )


def _detect_tools() -> list[str]:
    """Detect optional QA tools on PATH and return friendly names in stable order.
    Also detects jscpd via `npx --no-install` if not directly installed.
    """
    tools = [
        ("ruff", "ruff"),
        ("mypy", "mypy"),
        ("pyright", "pyright"),
        ("vulture", "vulture"),
        ("bandit", "bandit"),
        ("pip-audit", "pip-audit"),
        ("safety", "safety"),
        ("codespell", "codespell"),
        ("pyupgrade", "pyupgrade"),
        ("refurb", "refurb"),
        ("flynt", "flynt"),
        ("pydocstyle", "pydocstyle"),
        ("interrogate", "interrogate"),
        ("import-linter", "lint-imports"),
        ("semgrep", "semgrep"),
        ("radon", "radon"),
        ("xenon", "xenon"),
        ("pylint", "pylint"),
        ("lizard", "lizard"),
        ("clonedigger", "clonedigger"),
        ("coverage", "coverage"),
        ("diff-cover", "diff-cover"),
        ("jscpd", "jscpd"),
    ]
    available: list[str] = []
    for name, exe in tools:
        if shutil.which(exe):
            available.append(name)
    # Special case: try Node-based jscpd via npx without installing
    if "jscpd" not in available and shutil.which("npx"):
        try:
            cp = subprocess.run(
                ["npx", "--yes", "--no-install", "jscpd", "--version"],
                check=False,
                text=True,
                capture_output=True,
            )
            if cp.returncode == 0:
                available.append("jscpd(npx)")
        except Exception:
            pass
    return available


def build_find_prompt(scope_text: str, supplemental_text: str | None = None) -> str:
    properties_text = _properties_text()
    supplemental_section = build_supplemental_section(supplemental_text)
    lines: list[str] = [
        "Analyze the codebase for violations of the properties defined below. Do not modify any files. Output only violations; do not list properties/files with 'No violations'. Produce a concise structured report.",
        "",
        *_scope_block(
            scope_text,
            static_action="analyze",
            ambiguity_tail="do not include anything outside it.",
        ),
        "",
        "Constraints:",
        "- Read-only sandbox: do not execute commands that modify files or the repo",
        "- You MAY run read-only commands to inspect context (e.g., `git status`, `git diff --unified=0`)",
        "- You MUST check every changed hunk within scope",
        "",
        "Reporting requirements:",
        "- For each violation: 1-line rationale and precise anchors (e.g., file:41-45, function names, or concise symbol paths)"
        "- For many similar cases, write one short description then follow with a compact list of cases (file:lines or symbol names).",
        "- Do not list properties/files without violations; omit any 'No violations' lines.",
        "- Do not include preparatory narration; print only the report.",
        "",
        *_properties_block(properties_text, supplemental_section),
    ]
    return "\n".join(lines).strip()


def build_open_review_prompt(
    scope_text: str,
    supplemental_text: str | None = None,
    available_tools: list[str] | None = None,
) -> str:
    properties_text = _properties_text()
    supplemental_section = build_supplemental_section(supplemental_text)
    lines: list[str] = [
        "Perform an open-ended code quality review within the scope. Find both violations of the properties below and any other significant issues not already covered by properties or supplements. Run the detected analysis tools first in the suggested order, then do targeted manual review. Output only findings.",
        "",
        *_scope_block(
            scope_text,
            static_action="analyze",
            ambiguity_tail="do not include anything outside it.",
        ),
        "",
        "Constraints:",
        "- Read-only sandbox: do not execute commands that modify files or the repo",
        "- You MAY run read-only commands to inspect context (e.g., `git status`, `git diff --unified=0`)",
        "- You MUST check every changed hunk within scope",
        "",
        "Reporting requirements:",
        "- For each finding: 1-line rationale and precise anchors (e.g., file:41-45, function names, or concise symbol paths)"
        "- For many similar cases, write one short description then follow with a compact list of cases (file:lines or symbol names).",
        "- Do not include preparatory narration; print only the report.",
        "",
        *_properties_block(properties_text, supplemental_section),
    ]
    if available_tools is not None:
        lines.extend(_tools_and_flow_block(available_tools))
    return "\n".join(lines).strip()


def build_enforce_prompt(scope_text: str, supplemental_text: str | None = None) -> str:
    properties_text = _properties_text()
    supplemental_section = build_supplemental_section(supplemental_text)
    lines: list[str] = [
        "Ensure code within the described scope conforms to the properties defined below and refactor as needed to satisfy them without altering behavior.",
        "",
        *_scope_block(
            scope_text,
            static_action="edit",
            ambiguity_tail="avoid touching anything outside it unless required by the editing policy below.",
        ),
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


def build_cmd(
    model: str,
    workdir: Path,
    *,
    sandbox: str,
    skip_git_repo_check: bool,
    full_auto: bool,
    extra_configs: list[str] | None = None,
) -> list[str]:
    # Use codex exec with long flags for model/sandbox; pass configs via -c
    cmd: list[str] = [
        "codex",
        "exec",
        "--model",
        model,
        "--sandbox",
        sandbox,
        "-C",
        str(workdir),
    ]
    if extra_configs:
        for c in extra_configs:
            cmd.extend(["-c", c])
    if full_auto:
        cmd.append("--full-auto")
    if skip_git_repo_check:
        cmd.append("--skip-git-repo-check")
    return cmd


# ---- Specimen helpers (inlined) ----


def _find_specimens_base() -> Path:
    # 1) importlib.resources
    try:
        res = files("adgn_llm").joinpath("properties", "specimens")
        p = Path(str(res))
        if p.exists() and p.is_dir():
            return p
    except Exception:
        pass
    # 2) walk parents from this file for src tree
    here = Path(__file__).resolve()
    for parent in here.parents:
        for rel in (
            Path("src/adgn_llm/properties/specimens"),
            Path("adgn_llm/properties/specimens"),
        ):
            cand = (parent / rel).resolve()
            if cand.exists():
                return cand
    # Fallback
    return Path(str(files("adgn_llm").joinpath("properties", "specimens")))


def _list_specimen_names(base: Path) -> list[str]:
    return sorted(
        [
            p.name
            for p in base.iterdir()
            if p.is_dir() and (p / "manifest.yaml").exists()
        ]
    )


def _resolve_manifest_arg(arg: str | None, base: Path) -> Path | None:
    if arg is None:
        return None
    path = Path(arg)
    if path.exists():
        return path / "manifest.yaml" if path.is_dir() else path
    cand = base / arg / "manifest.yaml"
    if cand.exists():
        return cand
    # unique prefix
    matches = [n for n in _list_specimen_names(base) if n.startswith(arg)]
    if len(matches) == 1:
        return base / matches[0] / "manifest.yaml"
    return None


def _load_manifest(path: Path) -> SpecimenManifest:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return SpecimenManifest.model_validate(data)


def _try_download_github_archive(owner: str, repo: str, ref: str) -> Path | None:
    url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/{ref}"
    tmpdir = Path(tempfile.mkdtemp(prefix="adgn-specimen-archive-"))
    tar_path = tmpdir / f"{repo}-{ref}.tar.gz"
    try:
        with urlopen(url) as resp, tar_path.open("wb") as out:
            out.write(resp.read())
    except (URLError, HTTPError):
        return None
    with tarfile.open(tar_path, "r:gz") as tf:
        tf.extractall(tmpdir)
    for p in tmpdir.iterdir():
        if p.is_dir():
            return p.resolve()
    return None


def _fresh_git_checkout_url(url: str, ref: str, gitconfig: str | None) -> Path:
    tmpdir = Path(tempfile.mkdtemp(prefix="adgn-specimen-git-"))
    env = dict(**os.environ)
    if gitconfig:
        env["GIT_CONFIG_GLOBAL"] = str(Path(gitconfig).expanduser().resolve())
    subprocess.run(
        ["git", "init", str(tmpdir)], check=True, stdout=subprocess.DEVNULL, env=env
    )
    subprocess.run(
        ["git", "-C", str(tmpdir), "remote", "add", "origin", url], check=True, env=env
    )
    subprocess.run(
        ["git", "-C", str(tmpdir), "fetch", "--depth", "1", "origin", ref],
        check=True,
        env=env,
    )
    subprocess.run(
        ["git", "-C", str(tmpdir), "checkout", "--detach", ref], check=True, env=env
    )
    return tmpdir


def _fresh_local_copy(root: Path) -> Path:
    src = root.resolve()
    if not src.exists():
        raise SystemExit(f"Local source root not found: {src}")
    tmpdir = Path(tempfile.mkdtemp(prefix="adgn-specimen-local-"))
    dest = tmpdir / src.name
    shutil.copytree(src, dest)
    return dest


def _build_scope_text(
    include: Iterable[str], exclude: Iterable[str] | None = None
) -> str:
    inc = ", ".join(include)
    if exclude:
        return f"all files under {inc} (excluding: {', '.join(exclude)})"
    return f"all files under {inc}"


def _run_specimen(
    manifest_path: Path,
    *,
    dry_run: bool,
    json_out: bool,
    embed_paths: list[str] | None,
    gitconfig: str | None,
    mode: str = "find",
    final_only: bool = False,
    output_final_message: str | None = None,
) -> int:
    man = _load_manifest(manifest_path)
    # Resolve root
    if isinstance(man.source, GitHubSource):
        root = _try_download_github_archive(
            man.source.org, man.source.repo, man.source.ref
        )
        if root is None:
            root = _fresh_git_checkout_url(
                f"https://github.com/{man.source.org}/{man.source.repo}.git",
                man.source.ref,
                gitconfig,
            )
    elif isinstance(man.source, GitSource):
        # Best-effort tarball when URL is GitHub https
        url = man.source.url
        root = None
        if url.startswith("https://github.com/"):
            parts = url.removeprefix("https://github.com/").rstrip("/")
            if parts.endswith(".git"):
                parts = parts[:-4]
            bits = parts.split("/")
            if len(bits) >= 2:
                root = _try_download_github_archive(bits[0], bits[1], man.source.ref)
        if root is None:
            root = _fresh_git_checkout_url(man.source.url, man.source.ref, gitconfig)
    elif isinstance(man.source, LocalSource):
        root = _fresh_local_copy(manifest_path.parent / man.source.root)
    else:
        raise SystemExit(f"Unsupported source type: {type(man.source)}")

    scope_text = _build_scope_text(man.scope.include, man.scope.exclude)
    # Build supplemental text from embedded files (covered/not_covered_yet or user-specified)
    supplemental_text = (
        read_embedded_paths([Path(p) for p in (embed_paths or [])])
        if embed_paths
        else None
    )
    # Build appropriate prompt
    if mode == "discover":
        # Hint: suppress already known findings; focus on new items
        discover_preamble = (
            "Only report findings that are NOT already listed in the embedded supplements above. "
            "This includes additional instances under existing properties, new categories under existing properties, "
            "or entirely new issues not covered by current properties."
        )
        prompt = (
            discover_preamble
            + "\n\n"
            + build_open_review_prompt(
                scope_text,
                supplemental_text=supplemental_text,
                available_tools=_detect_tools(),
            )
        )
    elif mode == "open":
        # Open-ended review without suppression
        prompt = build_open_review_prompt(
            scope_text,
            supplemental_text=supplemental_text,
            available_tools=_detect_tools(),
        )
    else:
        prompt = build_find_prompt(scope_text, supplemental_text=supplemental_text)
        prompt = prompt + "\n\n" + "\n".join(_tools_and_flow_block(_detect_tools()))

    # Build codex command (read-only sandbox; full-auto; skip git repo check)
    cmd = build_cmd(
        "gpt-5", root, sandbox="read-only", skip_git_repo_check=True, full_auto=True
    )
    out_last_file: Path | None = None
    if output_final_message:
        cmd.extend(["--output-last-message", output_final_message])
    elif final_only:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            out_last_file = Path(tmp.name)
        cmd.extend(["--output-last-message", str(out_last_file)])

    if dry_run:
        # Save prompt to system temp dir and print approx token count
        tmpdir = Path(tempfile.gettempdir()) / "adgn_codex_prompts"
        tmpdir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        outfile = tmpdir / f"codex_prompt_specimen_{mode}_{ts}.md"
        outfile.write_text(prompt, encoding="utf-8")
        tokens = None
        try:
            if "tiktoken" in globals() and tiktoken is not None:
                enc = tiktoken.get_encoding("cl100k_base")
                tokens = len(enc.encode(prompt))
        except Exception:
            tokens = None
        print(" ".join(cmd))
        print(
            f"Detected tools: {', '.join(_detect_tools()) if _detect_tools() else '(none)'}"
        )
        print(_format_tools_table(_detect_tools()))
        print(
            f"Saved prompt: {outfile} (approx tokens: {tokens if tokens is not None else 'n/a'})"
        )
        return 0

    # Execute codex with prompt on stdin
    rc = subprocess.run(cmd, check=False, input=prompt, text=True).returncode
    if out_last_file is not None:
        try:
            print(Path(out_last_file).read_text(encoding="utf-8"))
        except Exception as e:
            print(
                f"[error reading final message file {out_last_file}: {e}]",
                file=sys.stderr,
            )
    return rc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="adgn-llm codex properties CLI",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "Examples:\n"
            "  # Check current repo for violations under a static path set\n"
            "  adgn-codex-properties check $(pwd) 'all files under src/**' --dry-run\n\n"
            "  # Fix code on a static path set (workspace-write sandbox)\n"
            "  adgn-codex-properties fix $(pwd) 'all files under src/**'\n\n"
            "  # Check a saved specimen by name (uses manifest.yaml)\n"
            "  adgn-codex-properties specimen-check 2025-09-02-ducktape_wt --dry-run\n\n"
            "  # Discover only-new findings vs specimen notes\n"
            "  adgn-codex-properties specimen-discover 2025-09-02-ducktape_wt --dry-run\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("workdir")
    common.add_argument("scope")
    common.add_argument("-m", "--model", default="gpt-5")
    common.add_argument("--dry-run", action="store_true")
    common.add_argument("--skip-git-repo-check", action="store_true")
    common.add_argument("--full-auto", action="store_true")
    common.add_argument(
        "--allow-general-findings",
        action="store_true",
        help="Also allow general code-quality findings beyond formal properties",
    )
    common.add_argument(
        "--final-only",
        action="store_true",
        help="Print only the agent's final message to stdout (suppresses trajectory output)",
    )
    common.add_argument(
        "--output-final-message",
        help="Write only the agent's final message to this path (passthrough to codex --output-last-message)",
    )

    sub.add_parser(
        "check",
        parents=[common],
        help="Check for violations using committed property definitions",
        description=(
            "Analyze code within the provided scope against all committed property definitions.\n"
            "- workdir: repo or directory to analyze\n"
            "- scope: freeform description (diff or static files), e.g. 'all files under src/**'\n"
            "Outputs a structured report; does not modify files."
        ),
    )
    sub.add_parser(
        "fix",
        parents=[common],
        help="Refactor code within scope to satisfy property definitions",
        description=(
            "Edit code to bring it into compliance with committed property definitions.\n"
            "- Uses a workspace-write sandbox\n"
            "- Keeps edits minimal and scoped; runs linters/formatters if present"
        ),
    )

    # Specimen runner subcommand (integrated)
    p_spec = sub.add_parser(
        "specimen-check",
        help="Run property scan on a saved specimen (manifest.yaml)",
        description=(
            "Resolve the specimen source+scope from manifest.yaml and run a check scan.\n"
            "- Accepts specimen name (under properties/specimens), a specimen dir, or a manifest.yaml path\n"
            "- Uses a fresh, private temp checkout/copy\n"
            "- Defaults: --full-auto and --skip-git-repo-check"
        ),
    )
    p_spec.add_argument(
        "specimen",
        nargs="?",
        help="Specimen name (under properties/specimens), path to specimen dir, or path to manifest.yaml",
    )
    p_spec.add_argument("--dry-run", action="store_true")
    p_spec.add_argument(
        "--json", action="store_true", help="Request JSON output from critic"
    )
    p_spec.add_argument(
        "--embed-path",
        action="append",
        dest="embed_paths",
        help="Extra files to embed into the prompt (Markdown); repeatable",
    )
    p_spec.add_argument(
        "--gitconfig",
        help="Path to a gitconfig to use for private repo fallback (shallow git)",
    )
    p_spec.add_argument(
        "--final-only",
        action="store_true",
        help="Print only the agent's final message to stdout (suppresses trajectory output)",
    )
    p_spec.add_argument(
        "--output-final-message",
        help="Write only the agent's final message to this path (passthrough to codex --output-last-message)",
    )
    p_spec.add_argument(
        "--allow-general-findings",
        action="store_true",
        help="Also allow general code-quality findings beyond formal properties",
    )

    # New command: specimen-discover — report only new findings vs current specimen notes
    p_spec_new = sub.add_parser(
        "specimen-discover",
        help="Discover only-new issues vs specimen notes",
        description=(
            "Run a scan on a specimen but suppress anything already listed in covered.md/not_covered_yet.md.\n"
            "Reports only additional instances, new categories under existing properties, or entirely new issues."
        ),
    )
    p_spec_new.add_argument(
        "specimen",
        nargs="?",
        help="Specimen name (under properties/specimens), path to specimen dir, or path to manifest.yaml",
    )
    p_spec_new.add_argument("--dry-run", action="store_true")
    p_spec_new.add_argument(
        "--json", action="store_true", help="Request JSON output from critic"
    )
    p_spec_new.add_argument(
        "--gitconfig",
        help="Path to a gitconfig to use for private repo fallback (shallow git)",
    )
    p_spec_new.add_argument(
        "--final-only",
        action="store_true",
        help="Print only the agent's final message to stdout (suppresses trajectory output)",
    )
    p_spec_new.add_argument(
        "--output-final-message",
        help="Write only the agent's final message to this path (passthrough to codex --output-last-message)",
    )
    p_spec_new.add_argument(
        "--allow-general-findings",
        action="store_true",
        help="Also allow general code-quality findings beyond formal properties",
    )

    args = parser.parse_args(argv)

    if args.command == "specimen-check":
        base = _find_specimens_base()
        manifest_path = _resolve_manifest_arg(args.specimen, base)
        if manifest_path is None:
            names = _list_specimen_names(base)
            if not names:
                print(f"No specimens found under: {base}")
                return 2
            print("Available specimens:")
            for n in names:
                print(" -", n)
            return 0
        # Validate gitconfig if provided
        gitconfig_path = None
        if getattr(args, "gitconfig", None):
            p = Path(args.gitconfig).expanduser().resolve()
            if not p.exists():
                print(f"ERROR: --gitconfig file not found: {p}")
                return 2
            gitconfig_path = str(p)
        mode = "open" if getattr(args, "allow_general_findings", False) else "find"
        return _run_specimen(
            manifest_path,
            dry_run=args.dry_run,
            json_out=args.json,
            embed_paths=args.embed_paths,
            gitconfig=gitconfig_path,
            mode=mode,
            final_only=getattr(args, "final_only", False),
            output_final_message=getattr(args, "output_final_message", None),
        )

    if args.command == "specimen-discover":
        base = _find_specimens_base()
        manifest_path = _resolve_manifest_arg(args.specimen, base)
        if manifest_path is None:
            names = _list_specimen_names(base)
            if not names:
                print(f"No specimens found under: {base}")
                return 2
            print("Available specimens:")
            for n in names:
                print(" -", n)
            return 0
        gitconfig_path = None
        if getattr(args, "gitconfig", None):
            p = Path(args.gitconfig).expanduser().resolve()
            if not p.exists():
                print(f"ERROR: --gitconfig file not found: {p}")
                return 2
            gitconfig_path = str(p)
        # Embed existing findings to suppress repeats
        embed_paths = []
        for name in ("covered.md", "not_covered_yet.md"):
            pth = manifest_path.parent / name
            if pth.exists():
                embed_paths.append(str(pth))
        return _run_specimen(
            manifest_path,
            dry_run=args.dry_run,
            json_out=args.json,
            embed_paths=embed_paths,
            gitconfig=gitconfig_path,
            mode="discover",
            final_only=getattr(args, "final_only", False),
            output_final_message=getattr(args, "output_final_message", None),
        )

    if args.command in ("check", "fix"):
        workdir = Path(args.workdir).resolve()
        detected_tools = _detect_tools()
        if not getattr(args, "output_final_message", None):
            print(
                f"Detected tools    : {', '.join(detected_tools) if detected_tools else '(none)'}"
            )
            print(_format_tools_table(detected_tools))
        out_last_file: Path | None = None
        if args.command == "check":
            prompt = (
                build_open_review_prompt(args.scope, available_tools=detected_tools)
                if args.allow_general_findings
                else build_find_prompt(args.scope)
            )
            if args.allow_general_findings:
                prompt = prompt.replace(
                    "Analyze the codebase for violations of the properties defined below. Do not modify any files. Output only violations; do not list properties/files with 'No violations'. Produce a concise structured report.",
                    "Perform an open-ended code quality review within the scope. Find both violations of the properties below and any other significant issues not already covered by properties or supplements. Run the detected analysis tools first in the suggested order, then do targeted manual review. Output only findings.",
                    1,
                )
            cmd = build_cmd(
                args.model,
                workdir,
                sandbox="read-only",
                skip_git_repo_check=args.skip_git_repo_check,
                full_auto=args.full_auto,
            )
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
        if getattr(args, "output_final_message", None):
            cmd.extend(["--output-last-message", args.output_final_message])
        elif args.final_only:
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                out_last_file = Path(tmp.name)
            cmd.extend(["--output-last-message", str(out_last_file)])

        if args.dry_run:
            # Save prompt to system temp dir and print approx token count
            tmpdir = Path(tempfile.gettempdir()) / "adgn_codex_prompts"
            tmpdir.mkdir(parents=True, exist_ok=True)
            ts = int(time.time())
            outfile = tmpdir / f"codex_prompt_{args.command}_{ts}.md"
            outfile.write_text(prompt, encoding="utf-8")
            tokens = None
            try:
                if "tiktoken" in globals() and tiktoken is not None:
                    enc = tiktoken.get_encoding("cl100k_base")
                    tokens = len(enc.encode(prompt))
            except Exception:
                tokens = None
            print(" ".join(cmd))
            print(
                f"Detected tools: {', '.join(_detect_tools()) if _detect_tools() else '(none)'}"
            )
            print(_format_tools_table(_detect_tools()))
            print(
                f"Saved prompt: {outfile} (approx tokens: {tokens if tokens is not None else 'n/a'})"
            )
            return 0

        # Stream to subprocess stdin
        try:
            rc = subprocess.run(cmd, check=False, input=prompt, text=True).returncode
            if out_last_file is not None:
                try:
                    print(Path(out_last_file).read_text(encoding="utf-8"))
                except Exception as e:
                    print(
                        f"[error reading final message file {out_last_file}: {e}]",
                        file=sys.stderr,
                    )
            return rc
        except KeyboardInterrupt:
            return 130
    else:
        parser.error("command is required")


if __name__ == "__main__":
    raise SystemExit(main())
