import shlex
import sys


def main() -> None:
    py = shlex.quote(sys.executable)
    func = f"""wt() {{
local wt_command_file=$(mktemp)
trap 'rm -f "$wt_command_file"' EXIT
{py} -m wt.cli sh "$@" 3>"$wt_command_file"
local wt_exit_code=$?
if [ $wt_exit_code -eq 0 ] || [ $wt_exit_code -eq 2 ]; then
    if [ -s "$wt_command_file" ]; then
        local wt_shell_commands="$(cat "$wt_command_file")"
        if [ -n "$wt_shell_commands" ]; then
            eval "$wt_shell_commands"
        fi
    fi
fi
rm -f "$wt_command_file"
return $wt_exit_code
}}"""
    print(func)

if __name__ == "__main__":
    main()
