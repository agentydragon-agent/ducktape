local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Inline logic parses args_json to extract cmd from argv, using hand-rolled shell
    quoting (reducer.py:69-88):

    cmd: str | None = None
    parsed_args: dict | None = None
    if evt.args_json:
        try:
            args = json.loads(evt.args_json)
            parsed_args = args if isinstance(args, dict) else None
            argv = args.get("argv") or args.get("cmd") if isinstance(args, dict) else None
            if isinstance(argv, list):
                # shell-join with conservative quoting
                parts: list[str] = []
                for a in argv:
                    if isinstance(a, str) and a and all(ch.isalnum() or ch in "_./-" for ch in a):
                        parts.append(a)
                    else:
                        s = str(a).replace("'", "'\\''")
                        parts.append(f"'{s}'")
                cmd = " ".join(parts)
        except json.JSONDecodeError:
            cmd = None
            parsed_args = None

    Problems:
    1. Complex inline logic hard to test
    2. Hand-rolled shell quoting instead of standard library
    3. Should use shlex.join() (Python 3.8+) for proper shell escaping
    4. Mixes parsing and formatting concerns

    Should extract to function:
    def extract_tool_command(args_json: str | None) -> tuple[str | None, dict | None]:
        if not args_json:
            return None, None
        try:
            args = json.loads(args_json)
            if not isinstance(args, dict):
                return None, None
            argv = args.get("argv") or args.get("cmd")
            if isinstance(argv, list):
                import shlex
                cmd = shlex.join(str(a) for a in argv)
            else:
                cmd = None
            return cmd, args
        except json.JSONDecodeError:
            return None, None

    Then use: cmd, parsed_args = extract_tool_command(evt.args_json)

    Benefits:
    - Testable: function can have unit tests
    - Correct: shlex.join handles all edge cases properly
    - Clear separation: parsing vs formatting
    - Reusable: if needed elsewhere
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/reducer.py': [
      [69, 88],     // Inline cmd/argv extraction logic
    ],
  },
)
