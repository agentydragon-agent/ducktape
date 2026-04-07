# TODO

## Scoping

- [ ] Pick base model (size vs capability tradeoff for vast.ai budget)
- [ ] Pick RL framework (OpenRLHF vs TRL vs veRL vs custom)
- [ ] Design task environment and reward function
- [ ] Define tool-call format for the model

## Infrastructure

- [ ] vast.ai setup script (install deps, pull model weights, mount data)
- [ ] Training launch script
- [ ] Checkpoint upload/download (HuggingFace Hub or S3)

## Training

- [ ] SFT warmup dataset (if needed)
- [ ] GRPO training loop
- [ ] Evaluation harness for agentic tasks
