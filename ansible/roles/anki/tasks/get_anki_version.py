import sys
import re
import subprocess

PATTERN = re.compile("^Anki ([0-9.]+)$", flags=re.MULTILINE)


def extract_version(stdout):
    if not (match := PATTERN.search(stdout)):
        raise ValueError(f"{stdout!r} does not contain {match}")
    return match.group(1)


def test_extract_version():
    input = "Anki starting...\nInitial setup...\nStarting Anki 25.02...\nAnki 25.02\n"
    assert extract_version(input) == "25.02"


def main():
    stdout = subprocess.check_output(["/usr/local/bin/anki", "--version"]).decode(
        "utf-8"
    )
    # make sure to not print a \n
    sys.stdout.write(extract_version(stdout))


if __name__ == "__main__":
    test_extract_version()
    main()
