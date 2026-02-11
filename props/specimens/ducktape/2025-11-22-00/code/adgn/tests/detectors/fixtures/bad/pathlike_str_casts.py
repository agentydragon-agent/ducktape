from pathlib import Path
import subprocess


def bad():
    subprocess.run(["echo", str(Path("/etc/hosts"))], check=False)
