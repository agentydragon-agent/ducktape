local I = import '../../specimens/lib.libsonnet';

// iss-031: Redundant variables and manual JSON parsing in runner.py

I.issueOneOccurrence(
  rationale= |||
    The `run_policy_source()` function has several code quality issues:

    **Problem 1: Redundant variable rename**

    Line 32 assigns `client = docker_client`, which is a pointless rename that adds
    no value. The variable is used immediately and throughout the function - just use
    the parameter name directly.

    **Current implementation (runner.py, line 32):**
    ```python
    def run_policy_source(
        *,
        docker_client: DockerClient,
        ...
    ) -> PolicyResponse:
        img: str = image if image else resolve_runtime_image()
        tmo = timeout_secs if timeout_secs is not None else float(...)
        client = docker_client  # ← Pointless rename
        try:
            client.images.get(img)
        except docker.errors.ImageNotFound as e:
            raise RuntimeError(f"policy eval image not found: {img}") from e
        ...
        container = client.containers.create(...)
    ```

    **The correct approach:**

    Use the parameter directly:
    ```python
    def run_policy_source(
        *,
        docker_client: DockerClient,
        ...
    ) -> PolicyResponse:
        img: str = image if image else resolve_runtime_image()
        tmo = timeout_secs if timeout_secs is not None else float(...)
        try:
            docker_client.images.get(img)
        except docker.errors.ImageNotFound as e:
            raise RuntimeError(f"policy eval image not found: {img}") from e
        ...
        container = docker_client.containers.create(...)
    ```

    **Problem 2: Unnecessary cmd and env variables**

    Lines 44-45 create `cmd` and `env` variables that are used only once in the
    immediately following `containers.create()` call. Should inline them.

    **Current implementation (runner.py, lines 44-58):**
    ```python
    ctx_json = json.dumps(input_payload, ensure_ascii=False)
    # Execute the packaged shim module that reads POLICY_INPUT/POLICY_SRC
    cmd = ["python", "-m", "adgn.agent.policy_eval.shim"]
    env = {"PYTHONUNBUFFERED": "1", "POLICY_SRC": source, "POLICY_INPUT": ctx_json}
    container = client.containers.create(
        image=img,
        command=cmd,
        detach=True,
        tty=False,
        environment=env,
        network_mode="none",
        volumes={},
        stdin_open=False,
        read_only=True,
        mem_limit=os.getenv("ADGN_POLICY_EVAL_MEM", "128m"),
        nano_cpus=int(os.getenv("ADGN_POLICY_EVAL_NANO_CPUS", str(500_000_000))),
        auto_remove=True,
    )
    ```

    **The correct approach:**

    Inline both variables:
    ```python
    ctx_json = json.dumps(input_payload, ensure_ascii=False)
    container = docker_client.containers.create(
        image=img,
        command=["python", "-m", "adgn.agent.policy_eval.shim"],
        detach=True,
        tty=False,
        environment={
            "PYTHONUNBUFFERED": "1",
            "POLICY_SRC": source,
            "POLICY_INPUT": ctx_json,
        },
        network_mode="none",
        volumes={},
        stdin_open=False,
        read_only=True,
        mem_limit=os.getenv("ADGN_POLICY_EVAL_MEM", "128m"),
        nano_cpus=int(os.getenv("ADGN_POLICY_EVAL_NANO_CPUS", str(500_000_000))),
        auto_remove=True,
    )
    ```

    **Problem 3: Manual JSON parsing instead of model_validate_json()**

    Line 80 does `json.loads(...)` to parse JSON, then passes the dict to
    `PolicyResponse.model_validate(data)`. Pydantic provides `model_validate_json()`
    which does both steps in one call and is more efficient.

    **Current implementation (runner.py, lines 76-83):**
    ```python
    logs = container.logs(stdout=True, stderr=True) or b""
    text = logs.decode("utf-8", errors="replace")
    if status != 0:
        raise RuntimeError(f"policy eval failed (exit={status}): {text.strip()}")
    try:
        data = json.loads(text.strip().splitlines()[-1]) if text.strip() else {}
    except Exception as e:
        raise RuntimeError(f"invalid JSON from policy eval: {e}; output={text!r}") from e
    return PolicyResponse.model_validate(data)
    ```

    **The correct approach:**

    Use `model_validate_json()` directly on bytes:
    ```python
    logs = container.logs(stdout=True, stderr=True) or b""
    if status != 0:
        text = logs.decode("utf-8", errors="replace")
        raise RuntimeError(f"policy eval failed (exit={status}): {text.strip()}")
    try:
        # Pydantic can parse JSON directly from bytes
        return PolicyResponse.model_validate_json(logs)
    except Exception as e:
        text = logs.decode("utf-8", errors="replace")
        raise RuntimeError(f"invalid JSON from policy eval: {e}; output={text!r}") from e
    ```

    **Benefits:**
    - Pydantic's JSON parser is faster (uses Rust)
    - Works directly on bytes (no decode needed for success case)
    - One-step parsing and validation
    - Better error messages from Pydantic

    **Problem 4: Unnecessarily constraining output format**

    Line 80 uses `.strip().splitlines()[-1]` to extract the last line, which
    unnecessarily constrains the policy output to not contain newlines in the JSON.
    Valid JSON can span multiple lines.

    **Current implementation (runner.py, line 80):**
    ```python
    data = json.loads(text.strip().splitlines()[-1]) if text.strip() else {}
    ```

    This assumes:
    - Policy output is line-based
    - JSON response is on the last line
    - JSON can't contain newlines

    **Why this is problematic:**

    Valid pretty-printed JSON output:
    ```json
    {
      "decision": "allow",
      "rationale": "Looks good"
    }
    ```

    Gets parsed as: `json.loads('"rationale": "Looks good"\n}')` → Error!

    **The correct approach:**

    Parse the entire output directly:
    ```python
    # If policy outputs only JSON
    return PolicyResponse.model_validate_json(logs)

    # Or if there might be debug output before JSON, extract last JSON object
    import re
    # Find last complete JSON object in output
    matches = list(re.finditer(r'\{[^}]*\}', text, re.DOTALL))
    if matches:
        json_text = matches[-1].group()
        return PolicyResponse.model_validate_json(json_text)
    ```

    But ideally: **policy should output ONLY JSON**, not mix debug output and JSON.
    If debug output is needed, send it to stderr, not stdout.

    **Combined fix:**

    ```python
    logs = container.logs(stdout=True, stderr=True) or b""
    if status != 0:
        text = logs.decode("utf-8", errors="replace")
        raise RuntimeError(f"policy eval failed (exit={status}): {text.strip()}")

    try:
        # Parse JSON directly from bytes (Pydantic handles UTF-8)
        return PolicyResponse.model_validate_json(logs.strip())
    except Exception as e:
        text = logs.decode("utf-8", errors="replace")
        raise RuntimeError(f"invalid JSON from policy eval: {e}; output={text!r}") from e
    ```

    Or if the output truly has multiple lines with JSON on the last line:
    ```python
    # Get last non-empty line
    text = logs.decode("utf-8", errors="replace")
    if status != 0:
        raise RuntimeError(f"policy eval failed (exit={status}): {text.strip()}")

    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("policy eval produced no output")

    try:
        return PolicyResponse.model_validate_json(lines[-1])
    except Exception as e:
        raise RuntimeError(f"invalid JSON from policy eval: {e}; output={text!r}") from e
    ```

    **Summary of changes:**

    1. Remove `client = docker_client` rename (use parameter directly)
    2. Inline `cmd` variable in `containers.create()` call
    3. Inline `env` variable in `containers.create()` call
    4. Use `model_validate_json()` instead of `json.loads()` + `model_validate()`
    5. Either parse entire output or clearly document/handle multi-line output
  |||,
  properties=['prefer-concise-code', 'use-platform-primitives', 'avoid-unnecessary-constraints'],
  filesToRanges={
    'adgn/src/adgn/agent/policy_eval/runner.py': [
      [32, 32],  // client = docker_client (redundant rename)
      [44, 45],  // cmd and env variables used only once
      [76, 83],  // Manual json.loads + splitlines[-1] instead of model_validate_json
    ],
  },
  gap_note= |||
    This finding illustrates **"use-platform-primitives"**: Pydantic provides
    `model_validate_json()` which parses JSON and validates in one step. Don't
    do `json.loads()` then `model_validate()` separately.

    Pydantic JSON parsing benefits:
    - Works directly on bytes (no decode needed)
    - Uses fast Rust-based parser (faster than stdlib json)
    - Better error messages (shows validation path)
    - Type-safe (returns typed model, not dict)

    When to use which Pydantic parsing method:
    - `model_validate_json(str | bytes)` - Parse JSON directly
    - `model_validate(dict)` - Validate already-parsed dict
    - `model_validate_python(Any)` - Validate any Python object

    Related to **"prefer-concise-code"**: inline variables used only once:
    - `cmd = [...]; create(command=cmd)` → `create(command=[...])`
    - `client = docker_client; client.do()` → `docker_client.do()`

    Related to **"avoid-unnecessary-constraints"**: don't artificially restrict
    input/output formats without good reason:
    - `.splitlines()[-1]` assumes JSON is on last line only
    - Breaks if policy outputs pretty-printed JSON
    - Breaks if JSON contains newlines in string values

    If you need to extract JSON from mixed output:
    - Have policy output ONLY JSON (recommended)
    - Send debug output to stderr, not stdout
    - Use a clear delimiter if mixing is necessary
    - Document the expected output format
  |||,
)
