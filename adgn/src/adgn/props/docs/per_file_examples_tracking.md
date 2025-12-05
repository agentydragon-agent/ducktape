# Per-File Training Examples - Implementation Tracking

## Optional/Future Enhancements 📋

### Prompt Optimizer Integration (separate from current implementation)
- [ ] Mount prompt_optimizer_context.md in container or bake into image
- [ ] Update prompt optimizer system prompt to read+embed context file
- [ ] Note: prompt optimizer ≠ GEPA (separate optimization strategies; docs already clarify this)

### critic_scopes.yaml Refinement
- [ ] Review and refine scopes for ducktape/2025-12-04-00 (currently naive per-component)

### Testing & Validation
- [ ] Add integration test: full pipeline with per-file examples
- [ ] Benchmark: measure actual recall improvement with per-file training

**Note:** Test flakiness is low priority - tests pass on retry, functionality works correctly.

## Notes

**Behavior-Cloning Goal:**
The critic should learn MY (user's) subjective taste and judgment calls. This isn't generic code review - it's behavior-cloning specific preferences about:
- What duplication is acceptable vs should be refactored
- What naming is clear vs verbose
- What abstraction level is appropriate
- What comments add value vs are noise

**Optimization Approaches (not mutually exclusive):**
1. **GEPA** (gepa-ai/gepa library) - Evolutionary search with reflection
2. **Prompt-optimizer agent** - LLM-based iterative improvement
3. **Manual tuning** - Direct prompt engineering

Per-file examples support all three approaches by providing more training signal.

**Terminal Metric:**
Full-repo review (all files) remains the real-world performance measure. Per-file examples are for training/optimization, not the end goal.
