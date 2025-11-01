from __future__ import annotations

import argparse
from pathlib import Path

from ember.config import load_settings
from ember.object_store import ObjectStoreClient


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("image_path", type=Path)
    args = parser.parse_args()

    settings = load_settings()
    if settings.object_store is None:
        raise SystemExit("Object store disabled for this deployment")

    client = ObjectStoreClient(settings.object_store)
    handle = client.upload_image(args.image_path, "image/png")
    print(handle.model_dump_json())


if __name__ == "__main__":
    main()
