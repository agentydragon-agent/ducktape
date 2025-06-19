#!/usr/bin/env python3
"""
git_commit_ai_patch: generate and apply a git commit using AI.
Scans staged changes, asks an AI (via 'claude' CLI) to produce a commit message and patch,
then shows diff and message, asks for confirmation, applies patch to index and commits.
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

def check_git_repo() -> None:
    try:
        subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print("Error: not inside a git repository", file=sys.stderr)
        sys.exit(1)

def get_staged_diff() -> str:
    res = subprocess.run(["git", "diff", "--cached"],
                         check=False, capture_output=True, text=True)
    diff = res.stdout
    if not diff.strip():
        print("No staged changes to commit.", file=sys.stderr)
        sys.exit(1)
    return diff

def ask_ai(diff: str, model: str) -> str:
    prompt = (
        "Write a git commit message and patch based on the staged diff. "
        "Output ONLY the commit message between <message> tags (imperative mood, concise) "
        "and the patch (unified diff) between <patch> tags. No additional text.\n\n"
        f"Staged diff:\n{diff}"
    )
    try:
        proc = subprocess.run([
            "claude", "--model", model, "-p", prompt
        ], check=False, capture_output=True, text=True)
    except FileNotFoundError:
        print("Error: 'claude' CLI not found in PATH", file=sys.stderr)
        sys.exit(1)
    if proc.returncode != 0:
        print(proc.stderr.strip(), file=sys.stderr)
        sys.exit(proc.returncode)
    return proc.stdout

def parse_response(resp: str) -> tuple[str, str]:
    msg_m = re.search(r"<message>\s*(.*?)\s*</message>", resp, re.DOTALL)
    patch_m = re.search(r"<patch>\s*(.*?)\s*</patch>", resp, re.DOTALL)
    if not msg_m or not patch_m:
        print("Error: failed to parse AI response; ensure tags <message> and <patch> are present", file=sys.stderr)
        sys.exit(1)
    return msg_m.group(1).strip(), patch_m.group(1).strip()

def confirm(msg: str, patch: str) -> None:
    print("\n=== Proposed Commit Message ===\n")
    print(msg)
    print("\n=== Proposed Patch ===\n")
    print(patch)
    ans = input("\nApply this commit? [y/N]: ")
    if ans.lower() != 'y':
        print("Aborted.")
        sys.exit(0)

def apply_and_commit(msg: str, patch: str) -> None:
    # write patch to temporary file
    with tempfile.NamedTemporaryFile('w', delete=False) as tmp:
        tmp.write(patch)
        tmp_path = tmp.name
    # apply patch to index
    res = subprocess.run(["git", "apply", "--cached", tmp_path])
    if res.returncode != 0:
        print("Error: failed to apply patch", file=sys.stderr)
        sys.exit(res.returncode)
    # commit
    res = subprocess.run(["git", "commit", "-m", msg])
    if res.returncode != 0:
        print("Error: git commit failed", file=sys.stderr)
        sys.exit(res.returncode)

def main() -> None:
    parser = argparse.ArgumentParser(description="AI-powered git commit via 'claude' CLI.")
    parser.add_argument("--model", default=os.environ.get("GIT_AI_MODEL", "sonnet"),
                        help="AI model to use (default: env GIT_AI_MODEL or 'sonnet')")
    args = parser.parse_args()
    check_git_repo()
    diff = get_staged_diff()
    resp = ask_ai(diff, args.model)
    msg, patch = parse_response(resp)
    confirm(msg, patch)
    apply_and_commit(msg, patch)

if __name__ == '__main__':
    main()