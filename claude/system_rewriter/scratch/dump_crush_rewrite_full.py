#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
PROVIDER_WIRE = Path(os.environ.get("CRUSH_WIRE_LOG", str(Path.home() / ".crush" / "logs" / "provider-wire.log")))
TEMPLATE = ROOT / "demo_template.txt"
OUT_PATH = ROOT / "crush_rewrite_full.json"

ENV_INTRO = 'Here is useful information about the environment you are running in:'
MODEL_PREFIX = 'You are powered by the model'
MCP_HEADER = '# MCP Server Instructions'
TOOLS_HEADER = 'You can use the following tools without requiring user approval:'


def ensure_template() -> Path:
    if not TEMPLATE.exists():
        TEMPLATE.write_text(
            (
                "System rewrite demo\n\n"
                "${toolsBlob}\n"
                "${envGitBlobs}${modelLine}${mcpSection}\n"
            ),
            encoding="utf-8",
        )
    return TEMPLATE


def iter_wire_lines(path: Path):
    if not path.exists():
        return
    if str(path).endswith(".gz"):
        import gzip  # lazy
        with gzip.open(path, "rt", encoding="utf-8", errors="ignore") as f:
            for line in f:
                yield line
    else:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
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
    toolsBlob = ''
    i_tools = s.find(TOOLS_HEADER)
    if i_tools != -1:
        after = i_tools + len(TOOLS_HEADER)
        nxt = [x for x in [s.find(ENV_INTRO, after), s.find(MODEL_PREFIX, after), s.find(MCP_HEADER, after)] if x != -1]
        end = min(nxt) if nxt else len(s)
        toolsBlob = s[after:end]
    mm = re.search(r"^" + re.escape(MODEL_PREFIX) + r"[^\n]*\n?", s, flags=re.MULTILINE)
    modelLine = mm.group(0) if mm else ''
    mcpSection = ''
    i_mcp = s.find(MCP_HEADER)
    if i_mcp != -1:
        nl = s.find("\n", i_mcp)
        mcpSection = '' if nl == -1 else s[nl + 1 :]
    return {"toolsBlob": toolsBlob, "envGitBlobs": envGitBlobs, "modelLine": modelLine, "mcpSection": mcpSection}


def rewrite_system_with_template_py(system_text: str, template_path: Path) -> str:
    template = Path(template_path).read_text(encoding="utf-8")
    blobs = extract_ccr_blobs(system_text)
    # Replace legacy ${vars} exactly once if present; if missing, just skip
    for name, val in (
        ("toolsBlob", blobs["toolsBlob"]),
        ("envGitBlobs", "".join(blobs["envGitBlobs"])),
        ("modelLine", blobs["modelLine"]),
        ("mcpSection", blobs["mcpSection"]),
    ):
        token = '${' + name + '}'
        if token in template:
            if template.count(token) != 1:
                raise RuntimeError(f"template placeholder {token} appears {template.count(token)} times (expected 1)")
            template = template.replace(token, val)
    # Ensure no leftover legacy tokens
    leftover = re.search(r"\$\{(toolsBlob|envGitBlobs|modelLine|mcpSection)\}", template)
    if leftover:
        raise RuntimeError(f"leftover template token: {leftover.group(0)}")
    return template


def first_n(arr: list[Any], n: int) -> list[Any]:
    return arr[:n]

def last_n(arr: list[Any], n: int) -> list[Any]:
    return arr[-n:] if len(arr) > n else arr


def norm_role(it: Any) -> str:
    if isinstance(it, dict):
        return (it.get('role') or it.get('message_role') or '').lower()
    return ''


def drop_system(arr: list[Any]) -> list[Any]:
    return [it for it in arr if isinstance(it, dict) and norm_role(it) != 'system']


def build_rewritten_request(orig: dict[str, Any], new_system_text: str) -> dict[str, Any]:
    req = copy.deepcopy(orig)
    inp = req.get('input')
    if not isinstance(inp, list):
        req['input'] = [
            {"role": "system", "content": [{"type": "input_text", "text": new_system_text}]}
        ]
        return req
    # Keep system + first 2 following items for readability; content unmodified
    first_user = None
    for i, it in enumerate(inp):
        if isinstance(it, dict) and (it.get('role') or it.get('message_role') or '').lower() == 'user':
            first_user = i
            break
    tail = inp[first_user:] if first_user is not None else []
    tail = tail[:2]
    req['input'] = [
        {"role": "system", "content": [{"type": "input_text", "text": new_system_text}]},
        *tail,
    ]
    return req


def main() -> int:
    tpl = ensure_template()
    # Find first request
    payload: dict[str, Any] | None = None
    for line in iter_wire_lines(PROVIDER_WIRE):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("direction") != "request":
            continue
        payload = maybe_extract_payload(e)
        if payload:
            break
    if not payload:
        print(json.dumps({"error": "no request found", "path": str(PROVIDER_WIRE)}))
        return 1

    sys_text = extract_system_text_from_responses_input(payload)
    new_sys = rewrite_system_with_template_py(sys_text, tpl)
    rewritten = build_rewritten_request(payload, new_sys)

    inp_orig = payload.get("input") or []
    inp_rew = rewritten.get("input") or []
    o_no_sys = drop_system(inp_orig)
    r_no_sys = drop_system(inp_rew)

    doc = {
        "paths": {
            "wire_log": str(PROVIDER_WIRE),
            "template": str(tpl),
        },
        "original": {
            "system_full": sys_text,
            "input_first4": first_n(o_no_sys, 4),
            "input_last4": last_n(o_no_sys, 4),
            "tools": payload.get("tools") or [],
        },
        "rewritten": {
            "system_full": new_sys,
            "input_first4": first_n(r_no_sys, 4),
            "input_last4": last_n(r_no_sys, 4),
            "tools": rewritten.get("tools") or [],
        },
    }
    OUT_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(OUT_PATH))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
