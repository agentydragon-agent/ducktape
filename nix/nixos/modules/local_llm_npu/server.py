"""Minimal OpenAI-compatible API server for Intel NPU inference via OpenVINO GenAI.

Usage: python server.py <model-dir>

Serves POST /v1/chat/completions on port 11435.
"""

import sys
import time
import uuid
from dataclasses import dataclass

import openvino_genai as ov_genai
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


@dataclass
class _State:
    pipe: ov_genai.LLMPipeline | None = None
    model_name: str = "npu-model"


_state = _State()


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = ""
    messages: list[Message]
    max_tokens: int = 512


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest):
    prompt = "\n".join(f"{m.role}: {m.content}" for m in request.messages)

    n_tokens = 0

    def count_tokens(_subword):
        nonlocal n_tokens
        n_tokens += 1
        return False

    start = time.perf_counter()
    result = _state.pipe.generate(prompt, max_new_tokens=request.max_tokens, streamer=count_tokens)
    elapsed = time.perf_counter() - start

    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "model": _state.model_name,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": result}, "finish_reason": "stop"}],
        "usage": {"completion_tokens": n_tokens},
        "_meta": {"elapsed_s": round(elapsed, 2), "tok_per_s": round(n_tokens / elapsed, 1) if elapsed > 0 else 0},
    }


@app.get("/v1/models")
async def list_models():
    return {"data": [{"id": _state.model_name, "object": "model", "owned_by": "local-npu"}]}


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <model-dir>", file=sys.stderr)
        sys.exit(1)

    model_dir = sys.argv[1]
    _state.model_name = model_dir.rstrip("/").rsplit("/", 1)[-1]

    print(f"Loading {_state.model_name} from {model_dir} on NPU...")
    _state.pipe = ov_genai.LLMPipeline(model_dir, "NPU", {"MAX_PROMPT_LEN": 1024, "MIN_RESPONSE_LEN": 512})
    print("Ready. Serving on http://127.0.0.1:11435/v1/chat/completions")
    uvicorn.run(app, host="127.0.0.1", port=11435)


if __name__ == "__main__":
    main()
