from __future__ import annotations

import argparse
import ssl
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--bytes", type=int, default=32)
    args = parser.parse_args()

    ssl._create_default_https_context = ssl._create_unverified_context
    with urllib.request.urlopen(args.url, timeout=30) as response:
        payload = response.read(args.bytes)
    if not payload:
        raise SystemExit("Fetched payload is empty")
    print(len(payload))


if __name__ == "__main__":
    main()
