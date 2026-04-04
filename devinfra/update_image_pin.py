"""Update a container image pin in devinfra/image_pins.json.

Usage:
    python3 devinfra/update_image_pin.py <name> --digest sha256:abc...
"""

import argparse
import json
from pathlib import Path

_PINS_FILE = Path(__file__).parent / "image_pins.json"


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


if __name__ == "__main__":
    main()
