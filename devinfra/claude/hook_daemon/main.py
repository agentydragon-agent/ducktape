"""Hook daemon entry point — starts uvicorn on a Unix domain socket."""

import argparse
import logging
from pathlib import Path

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Hook daemon")
    parser.add_argument("--sock", type=str, required=True, help="UDS path to listen on")
    parser.add_argument("--daemon-dir", type=str, required=True, help="Directory for logs, env persistence")
    args = parser.parse_args()

    daemon_dir = Path(args.daemon_dir)
    daemon_dir.mkdir(parents=True, exist_ok=True)

    # Configure file logging before importing the app (which sets up module loggers)
    log_file = daemon_dir / "daemon.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )

    from devinfra.claude.hook_daemon.server import app, configure  # noqa: PLC0415 — after logging setup

    configure(daemon_dir)

    uvicorn.run(app, uds=args.sock, log_level="warning")


if __name__ == "__main__":
    main()
