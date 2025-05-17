"""
export WEBHOOK_INBOX_KEY='fgBWt1JKhqE6MbZAUntgZ7QBGJ0thPU1Su1qzU529l4='
uvicorn webhook_inbox:app --host 0.0.0.0 --port 8000
"""

import os, time, json, sqlite3, base64, binascii, logging
from urllib.parse import urlencode
from starlette.datastructures import URL
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse
import textwrap
from fastapi.templating import Jinja2Templates
from cryptography.fernet import Fernet
import zlib
import pickle

WEBHOOK_INBOX_KEY: str = os.getenv("WEBHOOK_INBOX_KEY", "")  # 44-char url-safe b64, or unset → no crypto

MAX_PAYLOAD = int(os.getenv("MAX_PAYLOAD", "16384"))
PAGE_SIZE   = int(os.getenv("PAGE_SIZE", "50"))
TZ          = "America/Los_Angeles"
PAC         = ZoneInfo(TZ)

templates = Jinja2Templates(directory="templates")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
# Configure logging (avoid double config when uvicorn already set it up)
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

logger = logging.getLogger("webhook_inbox")
logger.setLevel(LOG_LEVEL)

# ─────────────────────────────────────────────────────────────────────────────
# Encoder
# ─────────────────────────────────────────────────────────────────────────────
#
# The main encoder class combines both encrypted and plain-JSON output modes.
# It was formerly named ``Encoder`` but is exposed externally as
# ``EncryptedEncoder`` to highlight its default behaviour when a
# ``WEBHOOK_INBOX_KEY`` is configured.
#
class EncryptedEncoder:
    """Encode events, optionally encrypting them.

    Behaviour depends on three factors:

    1. If ``WEBHOOK_INBOX_KEY`` is **unset** the encoder always returns plain JSON.
    2. *Client-supplied key* – when a key is configured, clients can override
       encryption by supplying the correct key in the query string
       (``?key=…``).
    """
    key: str | None

    @property
    def fernet(self):
        return Fernet(self.key) if self.key else None

    @staticmethod
    def _validate_key(key: str):
        try:
            key_bytes = base64.urlsafe_b64decode(key)
        except binascii.Error:
            raise RuntimeError("Key must be a url-safe base64 string.")
        if len(key_bytes) != 32:
            raise RuntimeError("Key has wrong length.")

    def __init__(self, key: str | None):
        # No key → encryption disabled.
        if not key:
            self.key = None
            return
        self._validate_key(key)
        self.key = key

    def plain_encode(self, events):
        # return json.dumps(events, separators=(',', ':')).encode()  # Compact JSON
        return json.dumps(events, indent=2)  # pretty JSON

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def encode(
        self,
        events,
        *,
        provided_key: str | None = None,
    ):
        """Return a *dict* with encoded representation of *events*.

        Return type is a mapping for unpacking into Jinja context.

        Behaviour:

        * No key configured → ``{"plaintext": <pretty JSON>}``

        * Correct key supplied in the request (``?key=…``) → same – plaintext JSON.

        * Key not passed or incorrect →
          ``{"ciphertext_body": …, "ciphertext_len": …, "tz": …}``
          plus ``error`` entry if wrong key was supplied.
        """

        # ── Plain JSON path -------------------------------------------------
        # When no *server*-side key is configured **or** the caller supplied
        # the correct key, return events as pretty-printed JSON.

        # If the *server* is not configured with a key, encryption is entirely
        # disabled and we always serve plaintext JSON irrespective of any
        # client-supplied ``?key`` parameter.  This matches the behaviour
        # documented in the function’s docstring and avoids runtime errors when
        # attempting to instantiate ``Fernet(None)``.

        if not self.key:
            return {"plaintext": self.plain_encode(events)}

        out = {}

        # When a key *is* configured, but the caller supplied the correct key
        # in the query string we again serve plaintext.  Any *incorrect* key is
        # noted in the output so the user is aware the data are still
        # encrypted.

        if provided_key is not None:
            if provided_key == self.key:
                return {"plaintext": self.plain_encode(events)}

            out["error"] = "Incorrect key in URL – data are still encrypted."

        # ── Encrypted path --------------------------------------------------
        # 1. serialize → compress → ASCII-85 to keep ciphertext URL-safe and
        #    printable.
        data = pickle.dumps(events, protocol=5)
        packed = zlib.compress(data, level=9)
        plaintext = base64.a85encode(packed).decode()

        # 2. Fernet-encrypt plaintext
        ciphertext = Fernet(self.key).encrypt(plaintext.encode()).decode()

        # 3. break into ≤50-char chunks and tag each line “# line i/N” for
        #    readability when embedded into documentation.
        width = 60
        chunks = [ciphertext[i : i + width] for i in range(0, len(ciphertext), width)]
        total = len(chunks)
        body = "\n".join(
            f"  {chunk!r}  # line {i+1}/{total}"
            for i, chunk in enumerate(chunks)
        )

        return out | {
            "ciphertext_body": "(\n" + body + "\n)",
            "ciphertext_len": len(ciphertext),
            "tz": TZ,
        }


# ── Encoder setup ----------------------------------------------------------
# A *single* encoder instance is sufficient – it decides at runtime whether to
# encrypt or not based on the presence of a configured key and the client's
# supplied `?key=` parameter.

ENCODER = EncryptedEncoder(WEBHOOK_INBOX_KEY)


def configure_db(path: str | os.PathLike):
    """(Re-)initialise the global SQLite connection and schema.

    Tests use this function to point the application at an isolated temporary
    database **without** having to re-import the module. Production code can
    simply rely on the implicit initialisation that happens on import.
    """

    global CONN

    # Close previous connection (if any) to avoid file locks under Windows
    # and to make sure commits hit the right file.
    if "CONN" in globals():
        try:
            CONN.close()
        except Exception:
            # Ignore errors when connection already closed.
            pass

    # (Re-)create connection and ensure tables exist.
    CONN = sqlite3.connect(str(path), check_same_thread=False)
    CONN.execute(
        """CREATE TABLE IF NOT EXISTS events(
               id      INTEGER PRIMARY KEY,
               ts      INTEGER,
               payload TEXT)"""
    )
    CONN.execute(
        """CREATE TABLE IF NOT EXISTS access_log(
               id      INTEGER PRIMARY KEY,
               ts      INTEGER,
               path    TEXT,
               method  TEXT,
               query   TEXT,
               payload TEXT,
               headers TEXT,
               status  INTEGER)"""
    )
    return CONN


# Initial default connection on module import.
# Database is configurable at runtime via `configure_db` for tests.
configure_db(os.getenv("DB_PATH", "events.db"))

# ── FastAPI + access-logging middleware
app = FastAPI()


def _print_startup_banner() -> None:
    """Emit helpful links to stdout once at startup."""

    # Do not pollute pytest output.
    import sys

    if any(mod.startswith("pytest") for mod in sys.modules):
        return

    base_url = "http://127.0.0.1:8000"  # TODO

    index_url = f"{base_url}/"

    lines: list[str] = [
        "📬  Webhook Inbox ready",
        f"  UI → {index_url}",
    ]
    # TODO: not great, logs the key! potentially into journal
    if WEBHOOK_INBOX_KEY:
        lines.append(f"  Unencrypted UI → {index_url}?key={WEBHOOK_INBOX_KEY}")
    lines.extend(
        [
            "",
            "Send a test webhook:",
            f"""   curl -X POST {index_url} -d '{json.dumps({'hello':'world'})}'""",
        ]
    )

    print("\n".join(lines))


# Trigger banner emission.
_print_startup_banner()

@app.middleware("http")
async def log_all(req: Request, call_next):
    """Log every HTTP request.

    Two separate sinks are used:
    1. A *database* row that also stores (truncated) request bodies for later
       inspection in the web UI.
    2. A *stdout* line for operators.  **Bodies are *not* included** here to
       avoid leaking sensitive data into log aggregators.
    """

    ts = int(time.time())

    # Capture at most MAX_PAYLOAD bytes for the database, but *do not* emit
    # them to stdout logs.
    body = (await req.body())[:MAX_PAYLOAD].decode(errors="replace")

    # Forward the request downstream and capture the response.
    resp = await call_next(req)

    # Store in DB for UI.
    CONN.execute(
        "INSERT INTO access_log(ts,path,method,query,payload,headers,status)"
        " VALUES(?,?,?,?,?,?,?)",
        (ts, req.url.path, req.method, req.url.query,
         body, json.dumps(dict(req.headers.items())), resp.status_code),
    )
    CONN.commit()

    # Emit operator log (no body).
    logger.info(
        "handled_request",
        extra={
            "method": req.method,
            "path": req.url.path,
            "query": req.url.query,
            "status": resp.status_code,
        },
    )

    return resp

# ── POST /  → ingest event
@app.post("/")
async def ingest(req: Request):
    raw = await req.body()
    if len(raw) > MAX_PAYLOAD:
        raise HTTPException(413, "Payload too large")
    try:
        payload = raw.decode()
    except UnicodeDecodeError:
        raise HTTPException(400, "Payload must be valid UTF-8")
    CONN.execute("INSERT INTO events(ts,payload) VALUES(?,?)",
                 (int(time.time()), payload))
    CONN.commit()
    return {"status": "ok"}


# ── GET /  → paged listing
@app.get("/")
def list_events(req: Request):
    # Ensure the paging parameters *before* and *count* exist.  Missing
    # ones are added via redirect so the resulting URL is self-contained and shareable.
    params: dict[str, str] = dict(req.query_params)

    redirect_needed = False

    if "before" not in params:
        params["before"] = str(int(time.time()))
        redirect_needed = True

    if "count" not in params:
        params["count"] = str(PAGE_SIZE)
        redirect_needed = True

    if redirect_needed:
        # Build a new URL with the missing parameters added.  ``URL`` will take
        # care of properly quoting values so we do not have to worry about
        # edge-cases such as spaces or special characters.
        redirect_target = str(URL("/").include_query_params(**params))
        return RedirectResponse(url=redirect_target, status_code=302)

    # ── Parse and validate parameters ────────────────────────────────────
    try:
        before_ts = int(params["before"])
    except ValueError:
        raise HTTPException(400, "Invalid 'before' parameter – must be integer timestamp")

    try:
        count = int(params["count"])
    except ValueError:
        raise HTTPException(400, "Invalid 'count' parameter – must be positive integer")

    if not (1 <= count <= PAGE_SIZE):
        raise HTTPException(400, f"'count' must be between 1 and {PAGE_SIZE}")

    rows = CONN.execute(
        "SELECT id,ts,payload FROM events "
        "WHERE ts < ? ORDER BY ts DESC LIMIT ?", (before_ts, count)
    ).fetchall()

    def _payload_entry(payload):
        try:
            # Try to decode JSON, return raw payload on failure.
            return json.loads(payload)
        except json.JSONDecodeError:
            return payload

    events = [{"id": r[0], "ts": r[1], "payload": _payload_entry(r[2])} for r in rows]

    older_link: str | None = None
    if rows:
        oldest_ts = rows[-1][1]
        if CONN.execute(
            "SELECT 1 FROM events WHERE ts < ? LIMIT 1", (oldest_ts,)
        ).fetchone():
            older_link = str(
                URL("/").include_query_params(before=oldest_ts, count=count)
            )

    # ── Key handling -------------------------------------------------------
    key_param = params.get("key")

    # Only propagate the key to paging links if the client supplied the *correct*
    # one.  Manipulating the URL via ``URL.include_query_params`` guarantees the
    # key is properly percent-encoded should it ever contain reserved
    # characters (even though a valid Fernet key is URL-safe already).
    if older_link and key_param == WEBHOOK_INBOX_KEY and key_param:
        older_link = str(URL(older_link).include_query_params(key=key_param))

    # Build link that jumps straight to the newest events (i.e. “Latest →”).
    # Without a key this is simply the root path “/”.  When the *correct* key
    # has been supplied we must forward it so users browsing plaintext JSON do
    # not suddenly receive encrypted output again when following the link.
    latest_link: str = "/"
    if key_param == WEBHOOK_INBOX_KEY and key_param:
        latest_link = str(URL(latest_link).include_query_params(key=key_param))

    ctx = {
        "request": req,
        "events_count": len(events),
        "older_link": older_link,
        # Convenience string like "[2024-05-16T09:00:00, 2024-05-16T10:00:00)"
        # that makes it obvious which side of the interval is closed and
        # which is open.
        "interval_str": None,  # filled in below
        "latest_link": latest_link,
        **ENCODER.encode(events, provided_key=key_param),
    }

    if WEBHOOK_INBOX_KEY and key_param != WEBHOOK_INBOX_KEY:
        # Link to fetch unencrypted JSON (uses placeholder key so secret is never
        # leaked).  Only shown when the current response is still encrypted.
        ctx["decrypt_link"] = str(URL(str(req.url)).include_query_params(key="KEY"))

    # Build a human-friendly representation of the timestamp interval that the
    # current page covers, e.g. "[2024-05-16T09:00:00, 2024-05-16T10:00:00)".
    format_ts = lambda ts: datetime.fromtimestamp(ts, PAC).isoformat(timespec="seconds")

    if events:
        start_iso = format_ts(events[-1]["ts"])

        # If there are no earlier events (i.e. we're at the beginning of log
        # history) we still use a closed left bracket but add a marker so the
        # user knows there is nothing before this page.
        if not older_link:
            start_iso = f"{start_iso} (beginning of history)"

        # Oldest event is included. Upper bound is exclusive (ts < before).
        ctx["interval_str"] = f"[{start_iso}, {format_ts(before_ts)})"
    else:
        # When the page is empty we cannot derive a concrete start timestamp
        # from the events themselves.  Indicate an open interval extending to
        # negative infinity.  We still use a *closed* right bracket because
        # the upper bound (``before_ts``) is *exclusive*.
        ctx["interval_str"] = f"(-∞, {format_ts(before_ts)})"

    return templates.TemplateResponse("events.html", ctx)

