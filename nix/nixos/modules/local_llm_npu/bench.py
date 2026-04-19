"""Benchmark an OpenVINO model on Intel NPU.

Usage: python local-llm-npu-bench.py <model-dir>
"""

import sys
import time

from optimum.intel import OVModelForCausalLM
from transformers import AutoTokenizer


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <model-dir>", file=sys.stderr)
        sys.exit(1)

    model_dir = sys.argv[1]
    print(f"Loading model from {model_dir} on NPU...")

    tokenizer = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
    model = OVModelForCausalLM.from_pretrained(model_dir, device="NPU", trust_remote_code=True)

    prompt = "Explain the theory of relativity in simple terms."
    inputs = tokenizer(prompt, return_tensors="pt")

    # Warmup
    model.generate(**inputs, max_new_tokens=1)

    # Benchmark
    start = time.perf_counter()
    output = model.generate(**inputs, max_new_tokens=128)
    elapsed = time.perf_counter() - start
    n_tokens = output.shape[1] - inputs["input_ids"].shape[1]

    print(f"Generated {n_tokens} tokens in {elapsed:.2f}s ({n_tokens / elapsed:.1f} tok/s)")
    print(tokenizer.decode(output[0], skip_special_tokens=True))


if __name__ == "__main__":
    main()
