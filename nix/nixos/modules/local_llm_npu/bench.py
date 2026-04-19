"""Benchmark LLM inference on Intel NPU via OpenVINO GenAI.

Usage: python bench.py <model-dir>
"""

import sys
import time

import openvino_genai as ov_genai


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <model-dir>", file=sys.stderr)
        sys.exit(1)

    model_dir = sys.argv[1]
    print(f"Loading {model_dir} on NPU...")

    pipe = ov_genai.LLMPipeline(model_dir, "NPU", {"MAX_PROMPT_LEN": 1024, "MIN_RESPONSE_LEN": 512})

    prompt = "Explain the theory of relativity in simple terms."

    # Warmup
    pipe.generate(prompt, max_new_tokens=1)

    # Benchmark
    n_tokens = 0

    def count_tokens(token):
        nonlocal n_tokens
        n_tokens += 1
        return False

    start = time.perf_counter()
    result = pipe.generate(prompt, max_new_tokens=128, streamer=count_tokens)
    elapsed = time.perf_counter() - start

    print(f"Generated {n_tokens} tokens in {elapsed:.2f}s ({n_tokens / elapsed:.1f} tok/s)")
    print(result)


if __name__ == "__main__":
    main()
