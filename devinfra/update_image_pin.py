"""Update a container image pin in devinfra/image_pins.json (and MODULE.bazel for digest pins).

Usage:
    python3 devinfra/update_image_pin.py <name> --digest sha256:abc...
    python3 devinfra/update_image_pin.py <name> --tag devel-20260401-abc1234
"""

import argparse
import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_PINS_FILE = _REPO_ROOT / "devinfra" / "image_pins.json"
_MODULE_BAZEL = _REPO_ROOT / "MODULE.bazel"


def _sync_digest_to_module_bazel(name: str, digest: str) -> None:
    """Update the oci.pull digest for `name` in MODULE.bazel."""
    text = _MODULE_BAZEL.read_text()
    pattern = rf'(name = "{name}",\n\s+)digest = "sha256:[a-f0-9A-F]+"'
    updated = re.sub(pattern, rf'\1digest = "{digest}"', text)
    if updated == text:
        print(f"Warning: no oci.pull block found for {name} in MODULE.bazel")
        return
    _MODULE_BAZEL.write_text(updated)
    print(f"Updated {name} digest in {_MODULE_BAZEL}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Update a container image pin.")
    parser.add_argument("name", help="Image name (key in image_pins.json)")
    parser.add_argument("--digest", help="New digest (sha256:...)")
    parser.add_argument("--tag", help="New tag")
    args = parser.parse_args()

    if not args.digest and not args.tag:
        parser.error("At least one of --digest or --tag is required")

    pins = json.loads(_PINS_FILE.read_text())
    if args.name not in pins:
        parser.error(f"Unknown image: {args.name} (known: {', '.join(sorted(pins))})")

    pin = pins[args.name]
    if args.digest:
        pin["digest"] = args.digest
    if args.tag:
        pin["tag"] = args.tag

    _PINS_FILE.write_text(json.dumps(pins, indent=2) + "\n")
    print(f"Updated {args.name} in {_PINS_FILE}")

    # For digest-pinned images, also sync to MODULE.bazel's oci.pull block
    if args.digest and pin.get("pin_type") == "digest":
        _sync_digest_to_module_bazel(args.name, args.digest)


if __name__ == "__main__":
    main()
