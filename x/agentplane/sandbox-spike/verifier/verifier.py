import json
import os
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast

AUDIENCE = "agentplane-sandbox-proxy-spike"
CREDENTIAL_PATH = Path("/var/run/spike-credential/value")
CREDENTIAL_VERSION_PATH = Path("/var/run/spike-credential/version")
KUBERNETES_TOKEN_PATH = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
KUBERNETES_CA_PATH = Path("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
MAX_BODY_BYTES = 1024
NAMESPACE = "agentplane-sandbox-spike"
NONCE = re.compile(r"[0-9a-f]{32}")
OPERATION_VALUE = "sandbox-proxy-identity-spike"
PROXY_USERNAME = f"system:serviceaccount:{NAMESPACE}:sandbox-proxy"
accepted_nonces: set[str] = set()
accepted_nonces_lock = threading.Lock()


def read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def object_map(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"invalid_{name}")
    return cast(dict[str, object], value)


def object_list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"invalid_{name}")
    return cast(list[object], value)


def string_field(value: dict[str, object], name: str) -> str:
    field = value.get(name)
    if not isinstance(field, str):
        raise ValueError(f"invalid_{name}")
    return field


def json_object(data: bytes) -> dict[str, object]:
    parsed: object = json.loads(data)
    return object_map(parsed, "json_object")


def kubernetes_request(path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    host = os.environ["KUBERNETES_SERVICE_HOST"]
    port = os.environ["KUBERNETES_SERVICE_PORT_HTTPS"]
    request = urllib.request.Request(
        f"https://{host}:{port}{path}",
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {read_file(KUBERNETES_TOKEN_PATH)}", "Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    context = ssl.create_default_context(cafile=KUBERNETES_CA_PATH)
    with urllib.request.urlopen(request, context=context, timeout=5) as response:
        return json_object(response.read())


def token_review(token: str) -> dict[str, object]:
    return kubernetes_request(
        "/apis/authentication.k8s.io/v1/tokenreviews",
        {
            "apiVersion": "authentication.k8s.io/v1",
            "kind": "TokenReview",
            "spec": {"audiences": [AUDIENCE], "token": token},
        },
    )


def one_extra(extra: dict[str, object], name: str) -> str:
    values = extra.get(name)
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], str):
        raise ValueError(f"missing_{name.rsplit('/', 1)[-1]}")
    return values[0]


class VerificationError(Exception):
    def __init__(self, status: int, reason: str):
        self.status = status
        self.reason = reason


def verify(handler: BaseHTTPRequestHandler, payload: object) -> dict[str, object]:
    if payload != {"operation": "echo", "value": OPERATION_VALUE}:
        raise VerificationError(400, "invalid_operation")
    authorization = handler.headers.get("Authorization", "")
    if authorization != f"Bearer {read_file(CREDENTIAL_PATH)}":
        raise VerificationError(401, "invalid_upstream_credential")
    credential_version = handler.headers.get("X-Credential-Version")
    if credential_version != read_file(CREDENTIAL_VERSION_PATH):
        raise VerificationError(401, "credential_version_mismatch")
    workload_token = handler.headers.get("X-Workload-Token")
    if workload_token is None:
        raise VerificationError(401, "missing_workload_token")
    try:
        review = token_review(workload_token)
    except (OSError, urllib.error.URLError):
        raise VerificationError(503, "token_review_unavailable") from None
    try:
        status = object_map(review.get("status"), "token_review_status")
    except ValueError as error:
        raise VerificationError(401, str(error)) from None
    if status.get("authenticated") is not True:
        raise VerificationError(401, "workload_token_rejected")
    try:
        audiences = object_list(status.get("audiences"), "token_review_audiences")
        user = object_map(status.get("user"), "token_review_user")
        extra = object_map(user.get("extra"), "token_review_extra")
    except ValueError as error:
        raise VerificationError(401, str(error)) from None
    if AUDIENCE not in audiences:
        raise VerificationError(401, "wrong_token_audience")
    if user.get("username") != PROXY_USERNAME:
        raise VerificationError(403, "wrong_service_account")
    try:
        pod_name = one_extra(extra, "authentication.kubernetes.io/pod-name")
        pod_uid = one_extra(extra, "authentication.kubernetes.io/pod-uid")
    except ValueError as error:
        raise VerificationError(401, str(error)) from None
    pod = kubernetes_request(f"/api/v1/namespaces/{NAMESPACE}/pods/{urllib.parse.quote(pod_name)}")
    try:
        pod_metadata = object_map(pod.get("metadata"), "pod_metadata")
        pod_status = object_map(pod.get("status"), "pod_status")
        current_pod_uid = string_field(pod_metadata, "uid")
        pod_ip = string_field(pod_status, "podIP")
        owner_values = object_list(pod_metadata.get("ownerReferences"), "pod_owners")
        owners = [object_map(owner, "pod_owner") for owner in owner_values]
    except ValueError:
        raise VerificationError(503, "invalid_pod_response") from None
    if current_pod_uid != pod_uid:
        raise VerificationError(401, "stale_pod_uid")
    if handler.client_address[0] != pod_ip:
        raise VerificationError(403, "source_pod_mismatch")
    owners = [owner for owner in owners if owner.get("controller") is True and owner.get("kind") == "Sandbox"]
    if len(owners) != 1:
        raise VerificationError(403, "sandbox_owner_missing")
    try:
        sandbox_name = string_field(owners[0], "name")
        sandbox_uid = string_field(owners[0], "uid")
    except ValueError:
        raise VerificationError(503, "invalid_sandbox_owner") from None
    sandbox = kubernetes_request(
        f"/apis/agents.x-k8s.io/v1beta1/namespaces/{NAMESPACE}/sandboxes/{urllib.parse.quote(sandbox_name)}"
    )
    try:
        sandbox_metadata = object_map(sandbox.get("metadata"), "sandbox_metadata")
        current_sandbox_name = string_field(sandbox_metadata, "name")
        current_sandbox_uid = string_field(sandbox_metadata, "uid")
    except ValueError:
        raise VerificationError(503, "invalid_sandbox_response") from None
    if current_sandbox_uid != sandbox_uid:
        raise VerificationError(403, "sandbox_owner_uid_mismatch")
    nonce = handler.headers.get("X-Request-Nonce", "")
    if NONCE.fullmatch(nonce) is None:
        raise VerificationError(400, "invalid_nonce")
    try:
        request_time = int(handler.headers.get("X-Request-Timestamp", ""))
    except ValueError:
        raise VerificationError(400, "invalid_timestamp") from None
    age_seconds = int(time.time()) - request_time
    if age_seconds < -5 or age_seconds > 30:
        raise VerificationError(409, "stale_request")
    with accepted_nonces_lock:
        if nonce in accepted_nonces:
            raise VerificationError(409, "replayed_request")
        accepted_nonces.add(nonce)
    return {
        "accepted": True,
        "credential_version": credential_version,
        "pod_name": pod_name,
        "pod_uid": pod_uid,
        "sandbox_name": current_sandbox_name,
        "sandbox_uid": current_sandbox_uid,
        "service_account": PROXY_USERNAME,
    }


class VerifierHandler(BaseHTTPRequestHandler):
    server_version = "sandbox-spike-verifier"

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self.send_json(200, {"status": "ok"})
            return
        self.send_json(404, {"error": "unknown_operation"})

    def do_POST(self) -> None:
        if self.path != "/fixed-operation":
            self.send_json(404, {"error": "unknown_operation"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if not 0 < content_length <= MAX_BODY_BYTES:
                raise VerificationError(400, "invalid_body_size")
            payload = json.loads(self.rfile.read(content_length))
            self.send_json(200, verify(self, payload))
        except json.JSONDecodeError:
            self.send_json(400, {"error": "invalid_json"})
        except VerificationError as error:
            self.send_json(error.status, {"error": error.reason})
        except (KeyError, OSError, urllib.error.HTTPError, urllib.error.URLError):
            self.send_json(503, {"error": "identity_lookup_unavailable"})


def main() -> None:
    ThreadingHTTPServer(("0.0.0.0", 8080), VerifierHandler).serve_forever()


if __name__ == "__main__":
    main()
