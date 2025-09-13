local obj = {
  should_flag: true,
  rationale: |||
    Condense and de-duplicate config printing.

    The code prints the config path with an if/else that can be expressed more concisely without losing clarity. A single expression using `or` is shorter and avoids branching noise.

    Before:
    ```python
    if cfg_file:
        print(f"config: {cfg_file}")
    else:
        print("config: <not found, using defaults>")
    ```

    After (shorter):
    ```python
    print(f"config: {cfg_file or '<not found, using defaults>'}")
    ```

    This is a readability-focused micro-refactor: it reduces branching for a simple, readable output and keeps intent clear.
  |||,
  properties: [],
  instances: [{ files: { 'pyright_watch_report.py': [{ start_line: 259, end_line: 262 }] } }],
};

obj
