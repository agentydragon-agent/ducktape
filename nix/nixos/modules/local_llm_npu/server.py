"""Minimal OpenAI-compatible API server for OpenVINO NPU inference.

Usage: python local-llm-npu-server.py <model-dir>

Serves POST /v1/chat/completions on port 11435.
"""

import sys
import time
import uuid
from dataclasses import dataclass, field

import uvicorn
from fastapi import FastAPI
from optimum.intel import OVModelForCausalLM
from pydantic import BaseModel
from transformers import AutoTokenizer

app = FastAPI()


@dataclass
class _State:
    model: OVModelForCausalLM = field(default=None)
    tokenizer: AutoTokenizer = field(default=None)
    model_name: str = "npu-model"


_state = _State()


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = ""
    messages: list[Message]
    max_tokens: int = 512
    temperature: float = 0.7


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest):
    inputs = _state.tokenizer.apply_chat_template(
        [m.model_dump() for m in request.messages], return_tensors="pt", add_generation_prompt=True
    )
    start = time.perf_counter()
    output = _state.model.generate(inputs, max_new_tokens=request.max_tokens)
    elapsed = time.perf_counter() - start
    response_text = _state.tokenizer.decode(output[0][inputs.shape[1] :], skip_special_tokens=True)
    n_tokens = output.shape[1] - inputs.shape[1]
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "model": _state.model_name,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": response_text}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": inputs.shape[1],
            "completion_tokens": n_tokens,
            "total_tokens": inputs.shape[1] + n_tokens,
        },
        "_meta": {"elapsed_s": round(elapsed, 2), "tok_per_s": round(n_tokens / elapsed, 1)},
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
    _state.tokenizer = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
    _state.model = OVModelForCausalLM.from_pretrained(model_dir, device="NPU", trust_remote_code=True)
    print("Ready. Serving on http://127.0.0.1:11435/v1/chat/completions")
    uvicorn.run(app, host="127.0.0.1", port=11435)


if __name__ == "__main__":
    main()
