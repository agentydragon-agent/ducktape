from pathlib import Path
import subprocess


def ok():
    subprocess.run(["echo", Path("/etc/hosts")], check=False)
