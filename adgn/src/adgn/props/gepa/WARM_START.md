# GEPA Warm Start Implementation

## Problem: SnapshotInput → int Mapping

GEPA's checkpoint system stores validation scores keyed by integer indices (0, 1, 2, ...), but the actual `SnapshotInput` objects are passed as a plain list to `optimize()`.

### How the Mapping Works

1. **At optimization time:**
   - We pass `valset: list[SnapshotInput]` to `optimize()`
   - GEPA wraps it in `ListDataLoader` which uses list indices as DataIds
   - `valset[0]` → DataId 0, `valset[1]` → DataId 1, etc.

2. **In the checkpoint:**
   - Scores are stored as `prog_candidate_val_subscores[prog_idx] = {0: 0.85, 2: 0.90, ...}`
   - The integers (0, 2, ...) are indices into the valset list

3. **When loading checkpoint:**
   - We must pass the **exact same valset in the exact same order**
   - Otherwise, integer keys in checkpoint point to wrong examples

### The Critical Invariant

**The valset order MUST be deterministic and stable across all runs.**

If the order changes:
- Checkpoint says "program 5 got score 0.85 on example 2"
- But "example 2" now refers to a different SnapshotInput
- The Pareto frontier becomes meaningless

## Solution: Deterministic Ordering

We enforce deterministic ordering at two levels:

### 1. Snapshot Level
```python
# In load_datasets():
valid_snapshots = session.query(Snapshot).filter_by(split=Split.VALID).order_by(Snapshot.slug).all()
```

Without `order_by()`, PostgreSQL can return rows in any order (especially after updates/deletes).

### 2. Critic Scope Level (Within Each Snapshot)
```python
# In Snapshot model:
critic_scopes: Mapped[list[CriticScopeDB]] = relationship(
    back_populates="snapshot_obj",
    cascade="all, delete-orphan",
    order_by="CriticScopeDB.id"  # ← Ensures consistent ordering
)
```

Since each snapshot has multiple critic scopes (per-file training examples), we must order these consistently too. We use the auto-increment `id` field which provides stable ordering.

### Complete Ordering Path

The final valset is constructed as:
```python
valset = list(chain.from_iterable(
    _build_snapshot_inputs_from_snapshot(s)
    for s in valid_snapshots  # ← Ordered by slug
))

# Within each snapshot:
for scope_db in snapshot.critic_scopes:  # ← Ordered by id
    inputs.append(SnapshotInput(slug=snapshot.slug, target_files=scope_db.files))
```

This produces a deterministic sequence like:
```
[
    SnapshotInput(slug="ducktape/2025-11-20-00", target_files={...}),  # scope id=1
    SnapshotInput(slug="ducktape/2025-11-20-00", target_files={...}),  # scope id=2
    SnapshotInput(slug="ducktape/2025-11-26-00", target_files={...}),  # scope id=3
    ...
]
```

## Warm Start Index Building

In `build_historical_gepa_state()`, we build the index:

```python
valset_idx_by_key: dict[tuple[SnapshotSlug, str], int] = {
    (snapshot_input.slug, hash_critic_scope_files(snapshot_input.target_files)): idx
    for idx, snapshot_input in enumerate(valset)
}
```

Then match historical runs:
```python
historical_runs = session.query(
    Prompt.prompt_text,
    Prompt.prompt_sha256,
    DBCriticRun.snapshot_slug,
    DBCriticRun.files_hash,  # ← Match on this
    DBGraderRun.output,
).join(...).filter(...).all()

for prompt_text, prompt_sha, snapshot_slug, files_hash, grader_output in historical_runs:
    val_idx = valset_idx_by_key.get((snapshot_slug, files_hash))
    if val_idx is not None:
        prompt_to_scores[prompt_sha][val_idx] = grader_output.recall
```

The `(snapshot_slug, files_hash)` key matches database runs to current valset indices.

## Checkpoint Field Values

All required GEPAState fields are set in the warm-start checkpoint:

- `program_candidates`: Historical prompts from database
- `prog_candidate_val_subscores`: Sparse score matrix (list of dicts)
- `pareto_front_valset`: Best score per validation example
- `program_at_pareto_front_valset`: Programs achieving best scores
- `list_of_named_predictors`: ["system_prompt"]
- `named_predictor_id_to_update_next_for_program_candidate`: [0, 0, ...]
- `parent_program_for_candidate`: [[None], [None], ...] (unknown parentage)
- `i`: -1 (next iteration will be 0)
- `num_full_ds_evals`: 0 (sparse coverage, no complete sweeps)
- `total_num_evals`: 0 (budget applies to this run only)
- `num_metric_calls_by_discovery`: [0, 0, ...] (unknown discovery cost)
- `full_program_trace`: []
- `best_outputs_valset`: None (don't track outputs for historical runs)
- `validation_schema_version`: 2 (sparse scores schema)
