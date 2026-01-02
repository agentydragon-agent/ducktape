import json
import re
import subprocess
from pathlib import Path

PATTERN = re.compile("^Anki ([0-9.]+)$", flags=re.MULTILINE)


def extract_version(stdout):
    if not (match := PATTERN.search(stdout)):
        raise ValueError(f"{stdout=!r} does not contain {PATTERN!r}")
    return match.group(1)


def test_extract_version():
    input = "Anki starting...\nInitial setup...\nStarting Anki 25.02...\nAnki 25.02\n"
    assert extract_version(input) == "25.02"


def main():
    anki_path = Path("/usr/local/bin/anki")

    if not anki_path.exists():
        print(json.dumps({"installed": False}))
        return

    stdout = subprocess.check_output([anki_path, "--version"]).decode("utf-8")
    version = extract_version(stdout)
    print(json.dumps({"installed": True, "version": version}))


if __name__ == "__main__":
    test_extract_version()
    main()
