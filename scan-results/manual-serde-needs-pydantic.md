# Scan Results: Manual Serialization Patterns That Should Use Pydantic

**Scan Date:** 2025-11-16
**Pattern:** Code using manual JSON serialization/deserialization, dict construction, and validation instead of leveraging Pydantic's built-in capabilities.

## Summary

Found **11 instances** across **8 files** where manual serialization/deserialization patterns could benefit from Pydantic models. The findings fall into these categories:

1. **Manual dict construction with `datetime.isoformat()`** (8 instances)
2. **Manual dict parsing with validation logic** (1 instance)
3. **Dataclass with manual serialization method** (1 instance)
4. **Manual datetime conversion in Pydantic model construction** (3 instances)

## Findings by Category

### 1. Manual Dict Construction with `datetime.isoformat()`

These instances manually build dictionaries with `isoformat()` calls for datetime serialization, which Pydantic handles automatically with `model_dump(mode="json")`.

#### `/home/user/ducktape/experimental/cotrl/llm_rl_experiment.py`

**Lines 119-132** - `log_episode()` method
```python
episode_data = {
    "timestamp": datetime.now().isoformat(),
    "model": model,
    "environment": env_name,
    "run_num": run_num,
    "episode_num": episode_num,
    "total_reward": episode.total_reward,
    "num_steps": len(episode.steps),
    "states": [...],
    "actions": [...],
    "rewards": [...],
}
```

**Why it matches:** Manually constructing a dict with `datetime.now().isoformat()` and multiple fields that could be a Pydantic model with automatic datetime serialization.

**Lines 139-151** - `log_step()` method
```python
step_data = {
    "timestamp": datetime.now().isoformat(),
    "model": model,
    "environment": env_name,
    "run_num": run_num,
    "episode_num": episode_num,
    "step_num": step_num,
    "state": step.state.tolist() if isinstance(step.state, np.ndarray) else step.state,
    "action": step.action,
    "reward": step.reward,
    "done": step.done,
    "truncated": step.truncated,
}
```

**Why it matches:** Similar to above - manual dict construction with datetime serialization that could be a Pydantic model.

**Lines 158-160** - `log_summary()` method
```python
summary = {
    "experiment_start": self.start_time.isoformat(),
    "experiment_end": datetime.now().isoformat(),
    "duration_seconds": (datetime.now() - self.start_time).total_seconds(),
    ...
}
```

**Why it matches:** Multiple datetime fields being manually converted to ISO format strings.

---

#### `/home/user/ducktape/llm/ultra-long-cot/ultra_long_cot_o4.py`

**Lines 295-304** - Log entry construction
```python
log_entry = {
    "timestamp": datetime.now().isoformat(),
    "turn": len([m for m in messages if m["role"] == "user"]) - 1,
    "user_input": user_input,
    "response_segments": continuation_count + 1,
    "total_output_tokens": total_generated,
    "context_used_percentage": context_percentage,
    "messages": messages.copy(),
    "usage_details": usage_details,
}
```

**Why it matches:** Manual dict construction with `datetime.isoformat()` for logging that could be a Pydantic model with automatic serialization.

---

#### `/home/user/ducktape/llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/hooks/handler.py`

**Lines 136-146** - Hook log entry
```python
log_entry = {
    "timestamp": timestamp,
    "hook_type": hook_type,
    "session_id": session_id,
    "request": {
        "type": type(request).__name__,
        "data": request.model_dump(),
    },
    "outcome": {"type": type(outcome).__name__, "data": str(outcome)},
    "response": response.model_dump(),
    "decision_details": {},
}
```

**Why it matches:** Manual dict construction combining Pydantic models (via `model_dump()`) with timestamps. Could be a unified Pydantic model that handles the entire structure.

**Line 164** - Decision log entry
```python
log_entry = {"timestamp": datetime.now().isoformat(), "decision_point": decision_point, "details": details}
```

**Why it matches:** Simple manual dict with datetime that could be a Pydantic model.

---

#### `/home/user/ducktape/adgn/src/adgn/inop/engine/optimizer.py`

**Lines 255-267** - Rollout data construction
```python
rollout_data = {
    "task_id": t_id,
    "agent_id": "agent_0",
    "iteration": iteration,
    "timestamp": datetime.now(UTC).isoformat(),
    "runner_id": gr.rollout.runner_id,
    "success": gr.rollout.success,
    "cost_usd": gr.rollout.cost_usd,
    "duration_seconds": gr.rollout.duration_seconds,
    "trajectory": [item.model_dump() for item in gr.rollout.trajectory],
    "files": gr.rollout.files,
    "metadata": gr.rollout.metadata,
}
```

**Why it matches:** Complex nested structure with datetime serialization, mixing manual fields with Pydantic model dumps. Could be a unified Pydantic model.

---

#### `/home/user/ducktape/adgn/src/adgn/mcp/compositor/server.py`

**Line 230** - Sampling snapshot construction
```python
return SamplingSnapshot(ts=datetime.now(UTC).isoformat(), servers=entries_map)
```

**Why it matches:** Manually converting datetime to isoformat string when constructing a Pydantic model. The model should accept `datetime` directly and handle serialization.

---

### 2. Manual Dict Parsing with Validation

#### `/home/user/ducktape/wt/src/wt/shared/github_models.py`

**Lines 121-150** - `coerce_prdata()` function
```python
def coerce_prdata(src: Any) -> PRData:
    if isinstance(src, PRData):
        return src
    if isinstance(src, GitHubPRResponse):
        return PRData(...)
    if isinstance(src, dict):
        num = src["pr_number"] if "pr_number" in src else src["number"]
        st = src.get("pr_state")
        raw_state = st if st is not None else src.get("state")
        if raw_state is None:
            raise KeyError("state")
        state = raw_state if isinstance(raw_state, PRState) else PRState(str(raw_state))
        return PRData(
            pr_number=int(num),
            pr_state=state,
            draft=bool(src.get("draft", False)),
            mergeable=src.get("mergeable"),
            merged_at=src.get("merged_at"),
            additions=src.get("additions"),
            deletions=src.get("deletions"),
        )
    raise TypeError("Unsupported PR data type")
```

**Why it matches:** This is a textbook example of manual dict parsing with field checking (`if "pr_number" in src`, `src.get(...)`), type coercion, and validation. This is exactly what Pydantic's `model_validate()` handles automatically, including:
- Field alias support (multiple field name options)
- Type coercion
- Validation
- Error handling

---

### 3. Dataclass with Manual Serialization Method

#### `/home/user/ducktape/wt/src/wt/shared/github_models.py`

**Lines 165-173** - `PRInfo` dataclass with `to_repr()` method
```python
@dataclass
class PRInfo:
    branch: str
    pr_data: PRData | None = None
    github_pr: HasBasicPR | None = None  # runtime object, not serialized
    gh_error: str | None = None

    def to_repr(self) -> PRInfoRepr:
        return PRInfoRepr(branch=self.branch, pr_data=self.pr_data, gh_error=self.gh_error)
```

**Why it matches:** Dataclass with manual serialization method. The `to_repr()` method selectively converts fields to another Pydantic model. If `PRInfo` were a Pydantic model with `Field(exclude=True)` on `github_pr`, serialization would be automatic via `model_dump()`.

---

### 4. Manual Datetime Conversion in Pydantic Model Construction

These instances manually convert datetime to ISO format strings when creating Pydantic models, rather than letting Pydantic handle datetime fields natively.

#### `/home/user/ducktape/wt/src/wt/shared/github_models.py`

**Line 109** - `from_github_pr()` classmethod
```python
@classmethod
def from_github_pr(cls, pr) -> GitHubPRResponse:
    return cls(
        ...
        merged_at=pr.merged_at.isoformat() if pr.merged_at else None,
        ...
    )
```

**Why it matches:** Manually converting datetime to isoformat string. The `merged_at` field could be typed as `datetime | None` in the Pydantic model, which would handle serialization automatically.

---

#### `/home/user/ducktape/wt/src/wt/server/pr_service.py`

**Line 144** - PRData construction
```python
pr_info = PRData(
    ...
    merged_at=(pr.merged_at.isoformat() if pr.merged_at else None),
    ...
)
```

**Why it matches:** Same pattern - manually converting datetime to string for a Pydantic model field.

---

#### `/home/user/ducktape/wt/src/wt/server/github_client.py`

**Line 72** - PullRequestList construction
```python
mergedAt=(pr.merged_at.isoformat() if pr.merged_at else None),
```

**Why it matches:** Same pattern - manual datetime-to-string conversion in Pydantic model construction.

---

## Recommendations by Priority

### High Priority (Most Impact)

1. **`/home/user/ducktape/wt/src/wt/shared/github_models.py` - `coerce_prdata()` function**
   - Replace with Pydantic's `model_validate()` with field aliases
   - Add a validator if custom coercion logic is truly needed
   - Example:
     ```python
     class PRData(BaseModel):
         pr_number: int = Field(alias="number")
         pr_state: PRState
         ...

         model_config = ConfigDict(populate_by_name=True)

     # Replace coerce_prdata(src) with:
     PRData.model_validate(src)
     ```

2. **Datetime fields in Pydantic models** (3 instances in `github_models.py`, `pr_service.py`, `github_client.py`)
   - Change `merged_at: str | None` to `merged_at: datetime | None` in the Pydantic models
   - Remove manual `.isoformat()` calls
   - Use `model_dump(mode="json")` for serialization

### Medium Priority

3. **Logging structures** in `llm_rl_experiment.py`, `ultra_long_cot_o4.py`, `claude_linter_v2/hooks/handler.py`
   - Create Pydantic models for log entries
   - Use `timestamp: datetime = Field(default_factory=datetime.now)` or similar
   - Serialize with `model_dump_json()` instead of manual `json.dumps()`

4. **`PRInfo` dataclass** in `wt/src/wt/shared/github_models.py`
   - Convert to Pydantic BaseModel
   - Use `Field(exclude=True)` on `github_pr`
   - Replace `to_repr()` with `model_dump(exclude={'github_pr'})`

### Lower Priority

5. **Rollout data** in `adgn/src/adgn/inop/engine/optimizer.py`
   - Create a Pydantic model for rollout data structure
   - Automatic datetime handling and nested model serialization

6. **`SamplingSnapshot`** in `adgn/src/adgn/mcp/compositor/server.py`
   - Change `ts` field from `str` to `datetime`
   - Remove manual `.isoformat()` call

## Benefits of Refactoring

1. **Type Safety**: Pydantic provides runtime type checking and validation
2. **Less Code**: Eliminate manual serialization/deserialization logic
3. **Datetime Handling**: Automatic ISO8601 serialization and parsing
4. **Validation**: Built-in field validation and constraints
5. **Documentation**: Field descriptions via `Field(description=...)`
6. **JSON Schema**: Automatic schema generation for API documentation
7. **Maintainability**: Single source of truth for data structures

## Notes

- No instances of `TypedDict` were found (which is good - those would be high-priority conversions)
- The codebase already uses Pydantic extensively, so these refactorings would align with existing patterns
- Most instances are in active development areas (LLM tooling, worktree management)
