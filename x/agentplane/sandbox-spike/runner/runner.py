import argparse
import contextlib
import json
import os
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

OPERATION_VALUE = "sandbox-proxy-identity-spike"


def request(url: str, payload: dict[str, str], headers: dict[str, str]) -> tuple[int, object]:
    operation = urllib.request.Request(
        url,
        data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(operation, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def assert_status(actual: int, expected: int, body: object) -> None:
    print(json.dumps({"status": actual, "body": body}, sort_keys=True))
    if actual != expected:
        raise RuntimeError(f"{actual=} != {expected=}")


def inspect_runner() -> None:
    visible_commands = []
    for command_path in Path("/proc").glob("[0-9]*/cmdline"):
        with contextlib.suppress(OSError):
            visible_commands.append(command_path.read_bytes().decode(errors="replace"))
    print(
        json.dumps(
            {
                "credential_env_present": any(
                    name in os.environ for name in ("UPSTREAM_CREDENTIAL", "WORKLOAD_TOKEN", "LITELLM_API_KEY")
                ),
                "credential_mount_present": Path("/var/run/spike-credential").exists(),
                "projected_identity_mount_present": Path("/var/run/spike-identity").exists(),
                "service_account_mount_present": Path("/var/run/secrets/kubernetes.io/serviceaccount").exists(),
                "proxy_process_visible": any("proxy.py" in command for command in visible_commands),
                "proxy_root_mount_visible": Path("/proc/1/root/var/run/spike-credential").exists(),
                "kubernetes_api_address_env_present": "KUBERNETES_SERVICE_HOST" in os.environ,
            },
            sort_keys=True,
        )
    )


def connect(host: str, port: int, expected: str) -> None:
    try:
        with socket.create_connection((host, port), timeout=3):
            result = "connected"
    except OSError:
        result = "blocked"
    print(json.dumps({"host": host, "port": port, "result": result}, sort_keys=True))
    if result != expected:
        raise RuntimeError(f"{result=} != {expected=}")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("idle")
    subparsers.add_parser("inspect")
    restart = subparsers.add_parser("request-restart")
    restart.add_argument("path")
    crash_proxy = subparsers.add_parser("crash-proxy")
    crash_proxy.add_argument("url")
    operate = subparsers.add_parser("operate")
    operate.add_argument("url")
    operate.add_argument("request_id")
    operate.add_argument("expected_status", type=int)
    direct = subparsers.add_parser("direct")
    direct.add_argument("url")
    direct.add_argument("request_id")
    direct.add_argument("expected_status", type=int)
    forge = subparsers.add_parser("forge")
    forge.add_argument("url")
    forge.add_argument("request_id")
    forge.add_argument("expected_status", type=int)
    arbitrary = subparsers.add_parser("arbitrary")
    arbitrary.add_argument("url")
    arbitrary.add_argument("request_id")
    arbitrary.add_argument("expected_status", type=int)
    connection = subparsers.add_parser("connect")
    connection.add_argument("host")
    connection.add_argument("port", type=int)
    connection.add_argument("expected", choices=["connected", "blocked"])
    args = parser.parse_args()

    if args.command == "idle":
        while True:
            restart_path = Path("/tmp/restart-requested")
            if restart_path.exists():
                restart_path.unlink()
                os._exit(42)
            time.sleep(1)
    if args.command == "inspect":
        inspect_runner()
        return
    if args.command == "connect":
        connect(args.host, args.port, args.expected)
        return
    if args.command == "request-restart":
        with Path(args.path).open("x", encoding="utf-8"):
            pass
        return
    if args.command == "crash-proxy":
        crash_request = urllib.request.Request(f"{args.url}/crash-for-test", data=b"", method="POST")
        with urllib.request.urlopen(crash_request, timeout=5) as response:
            print(json.dumps({"status": response.status}))
        return
    payload = {"request_id": args.request_id, "value": OPERATION_VALUE}
    headers = {}
    if args.command == "direct":
        url = f"{args.url}/fixed-operation"
        payload = {"operation": "echo", "value": OPERATION_VALUE}
    elif args.command == "forge":
        url = f"{args.url}/fixed-operation"
        payload = {"operation": "echo", "value": OPERATION_VALUE}
        headers = {"Authorization": "Bearer forged", "X-Forwarded-Sandbox": "sandbox-a", "X-Workload-Token": "forged"}
    elif args.command == "arbitrary":
        url = f"{args.url}/operate"
        payload["target"] = "http://example.invalid/"
    else:
        url = f"{args.url}/operate"
    status, body = request(url, payload, headers)
    assert_status(status, args.expected_status, body)


if __name__ == "__main__":
    main()
