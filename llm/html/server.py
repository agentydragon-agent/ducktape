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

    def verify_token(self, token: str):
        if not token.startswith(self._VERSION):
            raise ValueError("Invalid token version")

        try:
            date, rest = token.removeprefix(self._VERSION).rsplit("-", 1)
            doc_act, rest = rest[: self._DOC_LEN], rest[self._DOC_LEN :]
            pub_act, priv_act = rest[: self._PUB_LEN], rest[self._PUB_LEN :]
        except ValueError:
            raise ValueError("Invalid token format")

        if self._doc_hash() != doc_act:
            raise ValueError("Document hash mismatch")

        pub_exp = self._public_auth(date)
        if pub_act != pub_exp:
            raise ValueError("Public hash mismatch")
        exp_auth = self._private_auth(date)
        if not hmac.compare_digest(priv_act, exp_auth):
            raise ValueError("Private hash mismatch")


env = Environment(loader=FileSystemLoader("."), trim_blocks=True, lstrip_blocks=True)
tpl = env.get_template("index.md")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        text = (Path(__file__).parent / "index.md").read_text()
        ts = TokenScheme(b"hunter2", text)

        prefix, bits = ts.make_token(datetime.now())

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


if __name__ == "__main__":
    # Bind to all interfaces so that Docker port-forwarding works.  Inside a
    # container the service is usually accessed via the container’s bridge
    # address (e.g. 172.x.x.x), not 127.0.0.1.  Listening only on the loopback
    # interface therefore makes the process unreachable from the host and
    # results in a “connection reset” error even though the container is up and
    # its health-check may pass.  Using 0.0.0.0 exposes the service on every
    # interface while remaining just as safe inside the isolated container.
    host, port = "0.0.0.0", 9000

    print(f"Starting server on http://{host}:{port}")
    HTTPServer((host, port), Handler).serve_forever()
