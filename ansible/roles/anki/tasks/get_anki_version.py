import sys
import pprint
import re
import subprocess

anki_version_stdout = subprocess.check_output(
    ["/usr/local/bin/anki", "--version"]).decode("utf-8")
match = re.search("Anki ([0-9.]+)", anki_version_stdout)
assert match

# make sure to not print a \n
sys.stdout.write(match.group(1))
