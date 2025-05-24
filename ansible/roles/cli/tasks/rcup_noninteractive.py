# Pass arguments to rcup, check it didn't ask for confirmation.
import re
import shlex
import subprocess
import sys

argv = sys.argv[1:]
args = ["rcup", *argv]
output = subprocess.check_output(args).decode("utf-8")

if not output:
    # OK
    sys.exit(0)

if re.match(r"overwrite .+\? \[ynaq\]", output):
    print("rcup interactively asked whether to overwrite, you should it manually:")
else:
    print("rcup produced unhandled output")

print("    " + shlex.join(args))
sys.exit(1)
