"""Interactive chat with an OpenVINO model on Intel NPU.

Usage: python local-llm-npu-chat.py <model-dir>
"""

import sys

from optimum.intel import OVModelForCausalLM
from transformers import AutoTokenizer, TextStreamer


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <model-dir>", file=sys.stderr)
        sys.exit(1)

    model_dir = sys.argv[1]
    print(f"Loading model from {model_dir} on NPU...")

    tokenizer = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
    model = OVModelForCausalLM.from_pretrained(model_dir, device="NPU", trust_remote_code=True)
    streamer = TextStreamer(tokenizer, skip_prompt=True)

    messages = []
    print("Ready. Type your message (Ctrl+D to quit).")
    while True:
        try:
            user = input("> ")
        except EOFError:
            break
        messages.append({"role": "user", "content": user})
        inputs = tokenizer.apply_chat_template(messages, return_tensors="pt", add_generation_prompt=True)
        output = model.generate(inputs, max_new_tokens=512, streamer=streamer)
        response = tokenizer.decode(output[0][inputs.shape[1] :], skip_special_tokens=True)
        messages.append({"role": "assistant", "content": response})


if __name__ == "__main__":
    main()
