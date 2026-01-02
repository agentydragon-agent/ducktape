import shlex
import sys
from importlib import resources


def main() -> None:
    py = shlex.quote(sys.executable)
    # Load the shell function template from package resources and substitute __PY__
    with resources.files("wt.shell").joinpath("wt.sh").open("r", encoding="utf-8") as f:
        tpl = f.read()
    print(tpl.replace("__PY__", py))


if __name__ == "__main__":
    main()
