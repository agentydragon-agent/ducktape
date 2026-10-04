"""Regenerate the Nix wrappers' model-only inputs independently of Kubernetes."""

from model_catalog.nix import write_config
from util.bazel.workspace import get_build_workspace_directory


def main() -> None:
    write_config(get_build_workspace_directory())


if __name__ == "__main__":
    main()
