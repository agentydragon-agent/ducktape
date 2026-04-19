"""Export a HuggingFace model to OpenVINO IR format.

Usage: python local-llm-npu-export.py <model-id> <output-dir>
"""

import sys

from optimum.intel import OVModelForCausalLM
from transformers import AutoTokenizer


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <model-id> <output-dir>", file=sys.stderr)
        sys.exit(1)

    model_id, out_dir = sys.argv[1], sys.argv[2]
    print(f"Exporting {model_id} to OpenVINO IR at {out_dir} ...")

    model = OVModelForCausalLM.from_pretrained(model_id, export=True, trust_remote_code=True)
    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    model.save_pretrained(out_dir)
    tokenizer.save_pretrained(out_dir)
    print(f"Exported to {out_dir}")


if __name__ == "__main__":
    main()
