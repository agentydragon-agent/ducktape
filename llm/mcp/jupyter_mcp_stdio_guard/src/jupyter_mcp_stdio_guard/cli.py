import os
import sys
from pathlib import Path
from .wrapper import main as _main

def main() -> int:
    return _main()

if __name__ == "__main__":
    sys.exit(main())
