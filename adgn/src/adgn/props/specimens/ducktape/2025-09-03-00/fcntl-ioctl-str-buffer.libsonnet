local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Python 3.11/3.12 do not document accepting a str as the buffer argument to fcntl.ioctl; passing a string for TIOCGWINSZ is not supported in the targeted version (requires-python >=3.11).
    Use termios.tcgetwinsize(fd) in Python 3.11+ or pass a bytes-like buffer (e.g., struct.pack or bytearray) when calling ioctl.

    Evidence:
    - Python 3.11 docs — fcntl.ioctl: "The parameter arg can be one of an integer, an object supporting the read-only buffer interface (like bytes) or an object supporting the read-write buffer interface (like bytearray)."
    - Python 3.12 docs — fcntl.ioctl: same as 3.11 (no str listed).
    - Python 3.13 docs — fcntl.ioctl: "The parameter arg can be an integer, a bytes-like object, or a string." and "A string value is encoded to binary using the UTF-8 encoding."

    Recommendation: replace ioctl(..., TIOCGWINSZ, "        ") with termios.tcgetwinsize(fd) or a bytes-like buffer created via struct.pack/bytearray.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [729],
  },
)
