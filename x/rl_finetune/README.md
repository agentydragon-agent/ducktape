# RL Fine-tuning Experiments

Fine-tune open-source LLMs with GRPO (Group Relative Policy Optimization) on
agentic tasks.

## Wordle (hello-world)

Train Qwen3-1.7B to play Wordle via multi-step tool calling. Uses TRL's
`environment_factory` with the TextArena Wordle environment.

### Two-GPU server mode (recommended)

`trl` is not on `PATH` — `wordle_train.py` is a PEP 723 inline-deps script,
so its `trl` install lives in a hash-named uv cache env. Spawn the server
through `uv run --with` so we don't have to chase that path:

```bash
# Terminal 1: vLLM inference on GPU 0
CUDA_VISIBLE_DEVICES=0 uv run --no-project \
    --with 'trl[vllm]' \
    --with 'transformers @ git+https://github.com/huggingface/transformers.git@main' \
    trl vllm-serve --model Qwen/Qwen3-1.7B

# Terminal 2: GRPO training on GPU 1
CUDA_VISIBLE_DEVICES=1 uv run wordle_train.py
```

Health checks once the server is up: `curl http://localhost:8000/health/`
returns `{"status":"ok"}`.

### Single-GPU colocate mode

```bash
uv run wordle_train.py --colocate
```

### Monitor

```bash
tensorboard --logdir wordle_grpo_output
```

## Related

- [TRL GRPO docs](https://huggingface.co/docs/trl/main/en/grpo_trainer)
- [TRL OpenEnv integration](https://huggingface.co/docs/trl/main/en/openenv)
- [DeepSeek-R1 paper](https://arxiv.org/abs/2501.12948)
- `x/cotrl/` — earlier experiment testing LLMs as RL agents at inference time
