local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Line 80 uses `.strip().splitlines()[-1]` to extract the last line, which unnecessarily constrains the policy output to not contain newlines in the JSON. Valid JSON can span multiple lines.

    **Current implementation assumes:**
    - Policy output is line-based
    - JSON response is on the last line
    - JSON can't contain newlines

    **Why this is problematic:**

    Valid pretty-printed JSON output would break:
    ```json
    {
      "decision": "allow",
      "rationale": "Looks good"
    }
    ```
    Gets parsed as: `json.loads('"rationale": "Looks good"\n}')` → Error!

    **Correct approach:**

    Parse the entire output directly (ideally policy should output ONLY JSON, not mix debug output and JSON. If debug output is needed, send it to stderr, not stdout):

    ```python
    try:
        return PolicyResponse.model_validate_json(logs.strip())
    except Exception as e:
        text = logs.decode("utf-8", errors="replace")
        raise RuntimeError(f"invalid JSON from policy eval: {e}; output={text!r}") from e
    ```
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/policy_eval/runner.py': [[80, 80]],
  },
)
