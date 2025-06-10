# Pass arguments to rcup, check it didn't ask for confirmation.
import re
import shlex
import subprocess
import sys

argv = sys.argv[1:]
args = ["rcup", *argv]

# Run rcup with a pipe to capture output
proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

# Give it a moment to either complete or start prompting
try:
    output, errors = proc.communicate(timeout=2)

    # Process completed without interaction
    if proc.returncode == 0 and not output:
        # OK - rcup completed successfully with no output
        sys.exit(0)
    elif proc.returncode != 0:
        # rcup failed
        print(f"rcup failed with code {proc.returncode}")
        if output:
            print(f"stdout: {output}")
        if errors:
            print(f"stderr: {errors}")
        sys.exit(1)

except subprocess.TimeoutExpired:
    # Still running after timeout - likely waiting for input
    proc.kill()
    output, errors = proc.communicate()

    if re.search(r"overwrite .+\? \[ynaq\]", output + errors):
        print(
            "rcup interactively asked whether to overwrite, you should run it manually:",
        )
    else:
        print("rcup appears to be waiting for input (timed out)")
        if output:
            print(f"stdout: {output}")
        if errors:
            print(f"stderr: {errors}")

    print("    " + shlex.join(args))
    sys.exit(1)

# If we got here, rcup produced output but completed
if re.search(r"overwrite .+\? \[ynaq\]", output):
    print("rcup interactively asked whether to overwrite, you should run it manually:")
else:
    print("rcup produced unexpected output:")
    print(output)

print("    " + shlex.join(args))
sys.exit(1)
