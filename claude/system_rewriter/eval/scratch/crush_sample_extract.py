#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# Reuse shared constants
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # add eval/ to path
from constants import TOOLS_HEADER  # type: ignore

PROVIDER_WIRE = Path(os.environ.get("CRUSH_WIRE_LOG", str(Path.home() / ".crush" / "logs" / "provider-wire.log")))

ENV_INTRO = 'Here is useful information about the environment you are running in:'
MODEL_PREFIX = 'You are powered by the model'
MCP_HEADER = '# MCP Server Instructions'


def iter_wire_lines(path: Path):
    if not path.exists():
        return
    opener = None
    if str(path).endswith(".gz"):
        import gzip  # lazy
        opener = lambda p: gzip.open(p, "rt", encoding="utf-8", errors="ignore")
    else:
        opener = lambda p: open(p, "r", encoding="utf-8", errors="ignore")
    with opener(path) as f:  # type: ignore[misc]
        for line in f:
            yield line


def maybe_extract_payload(obj: dict[str, Any]) -> dict[str, Any] | None:
    p = obj.get("payload")
    return p if isinstance(p, dict) else None


def extract_system_text_from_responses_input(payload: dict[str, Any]) -> str:
    """Crush Responses requests can have input as a list of items with optional roles.
    We treat leading items (before first explicit user) as system and join their text.
    Each item's content may be a string or a list of parts with keys like text/input_text/content.
    """
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
    # envGitBlobs: all <env>...</env> blocks following the intro line
    envGitBlobs: list[str] = []
    if ENV_INTRO in s:
        env_re = re.compile(re.escape(ENV_INTRO) + r"\n<env>[\s\S]*?</env>\s*", re.MULTILINE)
        envGitBlobs = [m.group(0) for m in env_re.finditer(s)]
    # toolsBlob: text after TOOLS_HEADER until next known header
    toolsBlob = ""
    i_tools = s.find(TOOLS_HEADER)
    if i_tools != -1:
        after = i_tools + len(TOOLS_HEADER)
        nxt = [x for x in [s.find(ENV_INTRO, after), s.find(MODEL_PREFIX, after), s.find(MCP_HEADER, after)] if x != -1]
        end = min(nxt) if nxt else len(s)
        toolsBlob = s[after:end]
    # modelLine: first line starting with MODEL_PREFIX
    mm = re.search(r"^" + re.escape(MODEL_PREFIX) + r"[^\n]*\n?", s, flags=re.MULTILINE)
    modelLine = mm.group(0) if mm else ""
    # mcpSection: all content after the MCP header's newline
    mcpSection = ""
    i_mcp = s.find(MCP_HEADER)
    if i_mcp != -1:
        nl = s.find("\n", i_mcp)
        mcpSection = "" if nl == -1 else s[nl + 1 :]
    return {"toolsBlob": toolsBlob, "envGitBlobs": envGitBlobs, "modelLine": modelLine, "mcpSection": mcpSection}


def rewrite_system_with_template_py(system_text: str, template_path: Path) -> str:
    template = Path(template_path).read_text(encoding="utf-8")
    blobs = extract_ccr_blobs(system_text)
    placeholders = ['${toolsBlob}', '${envGitBlobs}', '${modelLine}', '${mcpSection}']
    for ph in placeholders:
        cnt = len(re.findall(re.escape(ph), template))
        if cnt != 1:
            raise RuntimeError(f"template placeholder {ph} count={cnt} (expected 1)")
    out = (
        template
        .replace('${toolsBlob}', blobs['toolsBlob'])
        .replace('${envGitBlobs}', ''.join(blobs['envGitBlobs']))
        .replace('${modelLine}', blobs['modelLine'])
        .replace('${mcpSection}', blobs['mcpSection'])
    )
    for ph in placeholders:
        if ph in out:
            raise RuntimeError(f"placeholder {ph} still present after replacement")
    return out


def main():
    # Find first Responses request
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
        sys_text = extract_system_text_from_responses_input(payload)
        blobs = extract_ccr_blobs(sys_text)
        print(json.dumps({
            "path": str(PROVIDER_WIRE),
            "timestamp": e.get("ts"),
            "has_tools_header": (TOOLS_HEADER in sys_text),
            "sys_preview": sys_text[:2000],
            "blobs": {
                "toolsBlob_len": len(blobs["toolsBlob"]),
                "envGitBlobs_count": len(blobs["envGitBlobs"]),
                "modelLine_present": bool(blobs["modelLine"]),
                "mcpSection_len": len(blobs["mcpSection"]),
            },
        }, ensure_ascii=False))
        return 0
    print(json.dumps({"event": "no_request_found", "path": str(PROVIDER_WIRE)}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
