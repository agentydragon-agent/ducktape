#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from typing import Any

PROVIDER_WIRE = Path(os.environ.get("CRUSH_WIRE_LOG", str(Path.home() / ".crush" / "logs" / "provider-wire.log")))
DEMO_TEMPLATE = Path(__file__).parent / "demo_template.txt"

ENV_INTRO = "Here is useful information about the environment you are running in:"
MODEL_PREFIX = "You are powered by the model"
MCP_HEADER = "# MCP Server Instructions"
TOOLS_HEADER = "You can use the following tools without requiring user approval:"


def ensure_demo_template() -> Path:
    if not DEMO_TEMPLATE.exists():
        DEMO_TEMPLATE.write_text(
            (
                "You are an interactive CLI tool that helps users with software engineering tasks. Use the instructions below and the tools available to you to assist the user.\n\n"
                "${toolsBlob}\n"
                "${envGitBlobs}${modelLine}${mcpSection}\n"
            ),
            encoding="utf-8",
        )
    return DEMO_TEMPLATE


def iter_wire_lines(path: Path):
    if not path.exists():
        return
    opener = None
    if str(path).endswith(".gz"):
        import gzip  # lazy

        def opener(p):
            return gzip.open(p, "rt", encoding="utf-8", errors="ignore")
    else:
        def opener(p):
            return open(p, encoding="utf-8", errors="ignore")
    with opener(path) as f:  # type: ignore[misc]
        for line in f:
            yield line


def maybe_extract_payload(obj: dict[str, Any]) -> dict[str, Any] | None:
    p = obj.get("payload")
    return p if isinstance(p, dict) else None


def extract_system_text_from_responses_input(payload: dict[str, Any]) -> str:
    inp = payload.get("input")
    if not isinstance(inp, list):
        return ""
    sys_parts: list[str] = []
    seen_user = False
    for item in inp:
        if not isinstance(item, dict):
            continue
        role = (item.get("role") or item.get("message_role") or "").lower()
        content = item.get("content")
        texts: list[str] = []
        if isinstance(content, str):
            texts = [content]
        elif isinstance(content, list):
            for c in content:
                if isinstance(c, dict):
                    t = c.get("text") or c.get("input_text") or c.get("content")
                    if isinstance(t, str):
                        texts.append(t)
        if role == "user":
            seen_user = True
        if (role in ("", "system") and not seen_user) and texts:
            sys_parts.append("\n".join(texts))
    return "\n\n".join(p for p in sys_parts if p)


def extract_ccr_blobs(system_text: str) -> dict[str, Any]:
    s = system_text or ""
    envGitBlobs: list[str] = []
    if ENV_INTRO in s:
        env_re = re.compile(re.escape(ENV_INTRO) + r"\n<env>[\s\S]*?</env>\s*", re.MULTILINE)
        envGitBlobs = [m.group(0) for m in env_re.finditer(s)]
    toolsBlob = ""
    i_tools = s.find(TOOLS_HEADER)
    if i_tools != -1:
        after = i_tools + len(TOOLS_HEADER)
        nxt = [
            x
            for x in [
                s.find(ENV_INTRO, after),
                s.find(MODEL_PREFIX, after),
                s.find(MCP_HEADER, after),
            ]
            if x != -1
        ]
        end = min(nxt) if nxt else len(s)
        toolsBlob = s[after:end]
    mm = re.search(r"^" + re.escape(MODEL_PREFIX) + r"[^\n]*\n?", s, flags=re.MULTILINE)
    modelLine = mm.group(0) if mm else ""
    mcpSection = ""
    i_mcp = s.find(MCP_HEADER)
    if i_mcp != -1:
        nl = s.find("\n", i_mcp)
        mcpSection = "" if nl == -1 else s[nl + 1 :]
    return {
        "toolsBlob": toolsBlob,
        "envGitBlobs": envGitBlobs,
        "modelLine": modelLine,
        "mcpSection": mcpSection,
    }


def rewrite_system_with_template_py(system_text: str, template_path: Path) -> str:
    template = Path(template_path).read_text(encoding="utf-8")
    blobs = extract_ccr_blobs(system_text)
    placeholders = ["${toolsBlob}", "${envGitBlobs}", "${modelLine}", "${mcpSection}"]
    # Ensure exactly once
    for ph in placeholders:
        cnt = template.count(ph)
        if cnt != 1:
            raise RuntimeError(f"template placeholder {ph} count={cnt} (expected 1)")
    out = (
        template.replace("${toolsBlob}", blobs["toolsBlob"])
        .replace("${envGitBlobs}", "".join(blobs["envGitBlobs"]))
        .replace("${modelLine}", blobs["modelLine"])
        .replace("${mcpSection}", blobs["mcpSection"])
    )
    for ph in placeholders:
        if ph in out:
            raise RuntimeError(f"placeholder {ph} still present after replacement")
    return out


def build_rewritten_request(orig: dict[str, Any], new_system_text: str) -> dict[str, Any]:
    req = copy.deepcopy(orig)
    inp = req.get("input")
    if not isinstance(inp, list):
        req["input"] = [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": new_system_text}],
            },
        ]
        return req
    # Keep only first 2 non-system items for readability
    # Find first explicit user index
    first_user = None
    for i, it in enumerate(inp):
        if isinstance(it, dict) and (it.get("role") or it.get("message_role") or "").lower() == "user":
            first_user = i
            break
    tail = inp[first_user:] if first_user is not None else []
    tail = tail[:2]
    req["input"] = [
        {
            "role": "system",
            "content": [{"type": "input_text", "text": new_system_text}],
        },
        *tail,
    ]
    return req


def main():
    tpl = ensure_demo_template()
    # Find first request
    for line in iter_wire_lines(PROVIDER_WIRE):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("direction") != "request":
            continue
        payload = maybe_extract_payload(e)
        if not payload:
            continue
        # Shorten original for display (limit input to first 3 entries)
        orig = copy.deepcopy(payload)
        if isinstance(orig.get("input"), list) and len(orig["input"]) > 3:
            orig["input"] = orig["input"][:3]
        sys_text = extract_system_text_from_responses_input(payload)
        new_sys = rewrite_system_with_template_py(sys_text, tpl)
        rewritten = build_rewritten_request(payload, new_sys)
        if isinstance(rewritten.get("input"), list) and len(rewritten["input"]) > 3:
            rewritten["input"] = rewritten["input"][:3]
        print(
            json.dumps(
                {
                    "original_crush_request": orig,
                    "rewritten_crush_request": rewritten,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    print(json.dumps({"error": "no request found", "path": str(PROVIDER_WIRE)}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
