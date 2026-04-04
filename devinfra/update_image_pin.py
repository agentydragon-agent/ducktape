"""Update a container image pin in devinfra/image_pins.json.

Also syncs the digest to MODULE.bazel if the image has an oci.pull() block there.

Usage:
    python3 devinfra/update_image_pin.py <name> --digest sha256:abc...
"""

import argparse
import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_PINS_FILE = _REPO_ROOT / "devinfra" / "image_pins.json"
_MODULE_BAZEL = _REPO_ROOT / "MODULE.bazel"


def _sync_digest_to_module_bazel(name: str, digest: str) -> None:
    """Update the oci.pull digest for `name` in MODULE.bazel, if present."""
    text = _MODULE_BAZEL.read_text()
    pattern = rf'(name = "{name}",\n\s+)digest = "sha256:[a-f0-9]+"'
    updated = re.sub(pattern, rf'\1digest = "{digest}"', text)
    if updated != text:
        _MODULE_BAZEL.write_text(updated)
        print(f"Synced {name} digest to {_MODULE_BAZEL}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Update a container image pin.")
    parser.add_argument("name", help="Image name (key in image_pins.json)")
    parser.add_argument("--digest", required=True, help="New digest (sha256:...)")
    args = parser.parse_args()

    pins = json.loads(_PINS_FILE.read_text())
    if args.name not in pins:
        parser.error(f"Unknown image: {args.name} (known: {', '.join(sorted(pins))})")

    pins[args.name]["digest"] = args.digest
    _PINS_FILE.write_text(json.dumps(pins, indent=2) + "\n")
    print(f"Updated {args.name} in {_PINS_FILE}")

    _sync_digest_to_module_bazel(args.name, args.digest)


if __name__ == "__main__":
    main()
