"""Interactive chat on Intel NPU via OpenVINO GenAI.

Usage: python chat.py <model-dir>
"""

import sys

import openvino_genai as ov_genai


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <model-dir>", file=sys.stderr)
        sys.exit(1)

    model_dir = sys.argv[1]
    print(f"Loading {model_dir} on NPU...")

    pipe = ov_genai.LLMPipeline(model_dir, "NPU", {"MAX_PROMPT_LEN": 1024, "MIN_RESPONSE_LEN": 512})

    print("Ready. Type your message (Ctrl+D to quit).")
    while True:
        try:
            user = input("> ")
        except EOFError:
            break
        result = pipe.generate(user, max_new_tokens=512)
        print(result)


if __name__ == "__main__":
    main()
