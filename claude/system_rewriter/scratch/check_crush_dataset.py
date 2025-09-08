#!/usr/bin/env python3
import json
import random
from collections import Counter, deque
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "dataset_crush.jsonl"

N_FIRST = 3
N_MIDDLE = 3
N_LAST = 3

first_objs: list[dict] = []
last_objs: deque[dict] = deque(maxlen=N_LAST)
mid_objs: list[dict] = []

first_raw: list[str] = []
last_raw: deque[str] = deque(maxlen=N_LAST)
mid_raw: list[str] = []

counts = Counter(
    total_lines=0,
    empty_lines=0,
    invalid_json=0,
    non_object=0,
    missing_oai_request=0,
    missing_input_and_messages=0,
    empty_input_list=0,
    missing_correlation_id=0,
    missing_timestamp=0,
)

random.seed(0)


def _text_preview(oai_req: dict, maxlen: int = 200) -> str:
    inp = oai_req.get("input")
    if isinstance(inp, list) and inp:
        item = inp[0]
        if isinstance(item, dict):
            content = item.get("content")
            if isinstance(content, str):
                s = content
            elif isinstance(content, list):
                parts = []
                for c in content:
                    if isinstance(c, dict):
                        t = c.get("text") or c.get("input_text") or c.get("content")
                        if isinstance(t, str):
                            parts.append(t)
                s = "\n".join(parts)
            else:
                s = (
                    json.dumps(content, ensure_ascii=False)
                    if content is not None
                    else ""
                )
            s = s.replace("\n", " ")
            return s[:maxlen] + ("…" if len(s) > maxlen else "")
    msgs = oai_req.get("messages")
    if isinstance(msgs, list) and msgs:
        m0 = msgs[0]
        if isinstance(m0, dict):
            c = m0.get("content")
            if isinstance(c, str):
                s = c
            elif isinstance(c, list):
                parts = [p.get("text", "") for p in c if isinstance(p, dict)]
                s = "\n".join([p for p in parts if p])
            else:
                s = json.dumps(c, ensure_ascii=False) if c is not None else ""
            s = s.replace("\n", " ")
            return s[:maxlen] + ("…" if len(s) > maxlen else "")
    return ""


def _summary_entry(obj: dict) -> dict:
    oai = obj.get("oai_request") or {}
    inp = oai.get("input")
    msgs = oai.get("messages")
    return {
        "correlation_id": obj.get("correlation_id"),
        "timestamp": obj.get("timestamp"),
        "oai_keys": sorted(list(oai.keys())) if isinstance(oai, dict) else None,
        "input_len": len(inp) if isinstance(inp, list) else None,
        "messages_len": len(msgs) if isinstance(msgs, list) else None,
        "preview": _text_preview(oai),
    }


with DATA_PATH.open("r", encoding="utf-8") as f:
    for i, line in enumerate(f, start=1):
        counts["total_lines"] += 1
        s = line.rstrip("\n")
        if not s.strip():
            counts["empty_lines"] += 1
            continue
        try:
            obj = json.loads(s)
        except Exception:
            counts["invalid_json"] += 1
            continue
        if not isinstance(obj, dict):
            counts["non_object"] += 1
            continue
        # samples
        if len(first_objs) < N_FIRST:
            first_objs.append(obj)
            first_raw.append(s)
        if len(mid_objs) < N_MIDDLE:
            mid_objs.append(obj)
            mid_raw.append(s)
        else:
            j = random.randint(1, i)
            if j <= N_MIDDLE:
                mid_objs[j - 1] = obj
                mid_raw[j - 1] = s
        last_objs.append(obj)
        last_raw.append(s)

        if not obj.get("correlation_id"):
            counts["missing_correlation_id"] += 1
        if obj.get("timestamp") is None:
            counts["missing_timestamp"] += 1
        oai = obj.get("oai_request")
        if not isinstance(oai, dict):
            counts["missing_oai_request"] += 1
            continue
        has_input = isinstance(oai.get("input"), list)
        has_messages = isinstance(oai.get("messages"), list)
        if not (has_input or has_messages):
            counts["missing_input_and_messages"] += 1
        if has_input and len(oai.get("input") or []) == 0:
            counts["empty_input_list"] += 1

print("# Crush dataset sanity check (raw + summaries)")
print(json.dumps({"path": str(DATA_PATH)}, ensure_ascii=False))
print("\n== RAW first/middle/last ==")
print(
    json.dumps(
        {
            "first": first_raw,
            "middle": mid_raw,
            "last": list(last_raw),
        },
        ensure_ascii=False,
        indent=2,
    )
)
print("\n== Samples (summaries) ==")
print(
    json.dumps(
        {
            "first": [_summary_entry(x) for x in first_objs],
            "middle": [_summary_entry(x) for x in mid_objs],
            "last": [_summary_entry(x) for x in list(last_objs)],
        },
        ensure_ascii=False,
        indent=2,
    )
)
print("\n== Summary counts ==")
print(json.dumps(counts, ensure_ascii=False, indent=2))
