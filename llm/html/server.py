#!/usr/bin/env python3
"""
Token v1  (21 chars)
--------------------
1:MMDD-HH:MM-PPPAaaaaaa

- Version prefix (“1:”)
- Human-readable month-day-hour-minute
- 3-char base58 public hash
- blake2b(date‖pepper) (~12 bits quick check)

Rejects obvious typos without the secret; authenticates quickly with it.

TODO: not completely "you mst collect whole thing" yet
"""

import hashlib
import hmac
import math
from datetime import datetime
from hashlib import blake2b, sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys
from typing import Final, List
from zoneinfo import ZoneInfo

import markdown
from jinja2 import Environment, FileSystemLoader

ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58enc(n: int, length: int) -> str:
    out = []
    for _ in range(length):
        n, r = divmod(n, len(ALPHABET))
        out.append(ALPHABET[r])
    return "".join(reversed(out)).rjust(length, ALPHABET[0])


def bytes_b58(x: bytes, len: int) -> str:
    return _b58enc(int.from_bytes(x, "big"), len)


N_TAGS = 7
TAG_LEN = 2


@staticmethod
def _digest_size(chars: int) -> int:
    """Bytes needed so that `chars` base-58 digits can represent it."""
    return math.ceil(chars * math.log2(58) / 8)


class TokenScheme:
    _VERSION = "1"

    # ─── master knobs: base-58 symbol counts ─────────────────────────────
    _DOC_LEN = 3
    _PUB_LEN = 3
    _AUTH_LEN = 8

    def __init__(self, secret: bytes, doc: str):
        self.secret = secret
        self.doc = doc
        # self.digest_size = 4
        # key  = b"super-secret"

    def _doc_hash(self) -> str:
        size = _digest_size(self._DOC_LEN)
        return bytes_b58(sha256(self.doc.encode()).digest()[:size], self._DOC_LEN)

    def make_token(self, now: datetime) -> tuple[str, list[str]]:
        date = now.strftime("%m%d-%H:%M")

        doc_hash = self._doc_hash()
        pub_txt = self._public_auth(date)
        auth_txt = self._private_auth(date)

        prefix = f"{self._VERSION}:{date}-"
        suffix = f"{doc_hash}{pub_txt}{auth_txt}"

        assert self._DOC_LEN + self._PUB_LEN + self._AUTH_LEN == N_TAGS * TAG_LEN
        # return in chunks of 2 chars

        return prefix, [suffix[i : i + 2] for i in range(0, len(suffix), 2)]

    def _public_auth(self, date: str) -> str:
        size = _digest_size(self._PUB_LEN)
        return bytes_b58(
            blake2b(date.encode(), digest_size=size).digest(), self._PUB_LEN
        )

    def _private_auth(self, date: str) -> str:
        size = _digest_size(self._AUTH_LEN)
        digest = hmac.new(self.secret, date.encode(), sha256).digest()[:size]
        return bytes_b58(digest, self._AUTH_LEN)

    class VerificationError(ValueError):
        """Aggregates all individual verification failures."""

        def __init__(self, issues: list[str]):
            super().__init__("; ".join(issues))
            self.issues = issues

    def verify_token(self, token: str):
        """Validate *token* against the current document & secret.

        The method checks every individual component and collects *all*
        mismatches so callers receive a full report in one go instead of being
        forced to fix issues one-by-one.  A single aggregated
        :pyclass:`VerificationError` is raised if any problem is detected.
        """

        issues: list[str] = []

        # ─── basic structure ───────────────────────────────────────────────
        if ":" not in token:
            raise self.VerificationError(["Token is missing ':' separator"])  # nothing more we can do

        version_str, payload = token.split(":", 1)

        if version_str != self._VERSION:
            issues.append(
                f"Version mismatch (expected={self._VERSION}, got={version_str or '<empty>'})"
            )

        # Payload is expected to look like “MMDD-HH:MM-<digest>”
        parts = payload.split("-", 2)
        if len(parts) < 2:
            issues.append("Token payload is incomplete – expected date & digest parts")
            raise self.VerificationError(issues)

        mmdd, hhmm = parts[0], parts[1]
        digest = parts[2] if len(parts) == 3 else ""

        # Validate date components early so that later checks can decide if
        # they can rely on *date*.
        date_valid = True
        if len(mmdd) != 4 or not mmdd.isdigit():
            issues.append(f"Invalid MMDD component: '{mmdd}'")
            date_valid = False

        if len(hhmm) != 5 or hhmm[2] != ":" or not (hhmm[:2].isdigit() and hhmm[3:].isdigit()):
            issues.append(f"Invalid HH:MM component: '{hhmm}'")
            date_valid = False

        date = f"{mmdd}-{hhmm}" if date_valid else None

        # ─── digest parts (may be incomplete) ──────────────────────────────
        doc_act = digest[: self._DOC_LEN]
        pub_act = digest[self._DOC_LEN : self._DOC_LEN + self._PUB_LEN]
        priv_act = digest[self._DOC_LEN + self._PUB_LEN :]

        # Document hash check
        if len(doc_act) != self._DOC_LEN:
            issues.append(
                f"Document hash incomplete ({len(doc_act)}/{self._DOC_LEN} characters provided)"
            )
        else:
            doc_exp = self._doc_hash()
            if doc_act != doc_exp:
                issues.append("Document hash mismatch")

        # Public hash check (depends on date)
        if len(pub_act) != self._PUB_LEN:
            issues.append(
                f"Public hash incomplete ({len(pub_act)}/{self._PUB_LEN} characters provided)"
            )
        elif date is None:
            issues.append("Cannot verify public hash due to invalid date")
        else:
            pub_exp = self._public_auth(date)
            if pub_act != pub_exp:
                issues.append("Public hash mismatch")

        # Private hash check (depends on date)
        if len(priv_act) != self._AUTH_LEN:
            issues.append(
                f"Private hash incomplete ({len(priv_act)}/{self._AUTH_LEN} characters provided)"
            )
        elif date is None:
            issues.append("Cannot verify private hash due to invalid date")
        else:
            priv_exp = self._private_auth(date)
            if not hmac.compare_digest(priv_act, priv_exp):
                issues.append("Private hash mismatch")

        if issues:
            raise self.VerificationError(issues)


env = Environment(loader=FileSystemLoader("."), trim_blocks=True, lstrip_blocks=True)
tpl = env.get_template("index.md")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        text = (Path(__file__).parent / "index.md").read_text()
        ts = TokenScheme(b"hunter2", text)

        # Use San Francisco timezone (America/Los_Angeles)
        sf_time = datetime.now(ZoneInfo("America/Los_Angeles"))
        prefix, bits = ts.make_token(sf_time)

        text = tpl.render(
            prefix=prefix,
            bits=bits,
        )
        html = markdown.markdown(text, extensions=["tables", "fenced_code"]).encode()

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.send_header("Cache-Control", "no-store")  # cache-bust
        self.end_headers()
        self.wfile.write(html)


def _start_server(host: str = "0.0.0.0", port: int = 9000):
    """Start the HTTP server – extracted so that the CLI stays tidy."""

    # Bind to all interfaces so that Docker port-forwarding works.  Inside a
    # container the service is usually accessed via the container’s bridge
    # address (e.g. 172.x.x.x), not 127.0.0.1.  Listening only on the loopback
    # interface therefore makes the process unreachable from the host and
    # results in a “connection reset” error even though the container is up and
    # its health-check may pass.  Using 0.0.0.0 exposes the service on every
    # interface while remaining just as safe inside the isolated container.
    print(f"Starting server on http://{host}:{port}")
    HTTPServer((host, port), Handler).serve_forever()


def _verify_cli(token: str, *, secret: str = "hunter2", doc_path: str = "index.md") -> int:
    """Command-line helper to *verify* a token and print a human readable report.

    Returns an exit-code alike integer so the caller can ``sys.exit`` with it.
    """

    try:
        doc = Path(doc_path).read_text()
    except FileNotFoundError:
        print(f"ERROR: Document file '{doc_path}' not found", file=sys.stderr)
        return 2

    ts = TokenScheme(secret.encode(), doc)

    try:
        ts.verify_token(token)
    except TokenScheme.VerificationError as exc:
        print("Token verification FAILED:")
        for issue in exc.issues:
            print(f"  ✗ {issue}")
        return 1

    print("Token verification succeeded – all checks passed ✅")
    return 0


def _build_arg_parser() -> "argparse.ArgumentParser":
    import argparse

    p = argparse.ArgumentParser(description="Token demo web-server & verifier")
    sub = p.add_subparsers(dest="command", required=False)

    # --- serve -------------------------------------------------------------
    serve = sub.add_parser("serve", help="Start the demo web server (default)")
    serve.add_argument("--host", default="0.0.0.0", help="Interface to bind to")
    serve.add_argument("--port", type=int, default=9000, help="TCP port to listen on")

    # --- verify ------------------------------------------------------------
    verify = sub.add_parser("verify", help="Verify a token against the current document")
    verify.add_argument("token", help="The token to be verified")
    verify.add_argument(
        "--doc",
        default="index.md",
        help="Path to the markdown document the token was generated for (default: index.md)",
    )
    verify.add_argument(
        "--secret",
        default="hunter2",
        help="Shared secret that was used to generate the private component",
    )

    return p


def main(argv: list[str] | None = None):
    import argparse

    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if args.command in (None, "serve"):
        _start_server(host=getattr(args, "host", "0.0.0.0"), port=getattr(args, "port", 9000))
    elif args.command == "verify":
        exit_code = _verify_cli(
            args.token,
            secret=args.secret,
            doc_path=args.doc,
        )
        sys.exit(exit_code)
    else:
        # Should not happen thanks to argparse choices
        parser.error(f"Unknown command {args.command}")


if __name__ == "__main__":
    main()
