"""
export WEBHOOK_INBOX_KEY='fgBWt1JKhqE6MbZAUntgZ7QBGJ0thPU1Su1qzU529l4='
uvicorn webhook_inbox:app --host 0.0.0.0 --port 8000
"""

import os, time, json, sqlite3, base64, binascii, logging
from urllib.parse import urlencode
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

class EncryptedEncoder:
    def __init__(self, key):
        try:
            key_bytes = base64.urlsafe_b64decode(key)
            if len(key_bytes) != 32:
                raise ValueError
        except (binascii.Error, ValueError):
            raise RuntimeError("Key must must be a 44-char url-safe base64 string.")

        self.fernet = Fernet(key)

    def encode(self, events, tz="UTC"):
        # 1. serialize → compress → ASCII-85
        data = pickle.dumps(events, protocol=5)
        packed = zlib.compress(data, level=9)
        plaintext = base64.a85encode(packed).decode()

        # 2. Fernet-encrypt plaintext
        ciphertext = self.fernet.encrypt(plaintext.encode()).decode()

        # 3. break into ≤50-char chunks and tag each line “# line i/N”
        width  = 50
        chunks = [ciphertext[i:i+width] for i in range(0, len(ciphertext), width)]
        total  = len(chunks)
        body   = "\n".join(
            f'  {chunk!r}  # line {i+1}/{total}'
            for i, chunk in enumerate(chunks)
        )
        body = "(\n" + body + "\n)"

        # 5. final template
        # TODO: fix the spaces
        return textwrap.dedent("""
        # The events are encoded in this ciphertext:
        CIPHERTEXT = {}
        assert len(CIPHERTEXT) == {}

        # You should have a Fernet key of 32 base64-encoded bytes:
        WEBHOOK_INBOX_KEY: str = ...
        assert len(WEBHOOK_INBOX_KEY) == 44

        # Read the data by decrypting them first using something like this code:
        import zlib, base64, pickle, datetime
        from zoneinfo import ZoneInfo
        from cryptography.fernet import Fernet

        plain_b85 = Fernet(WEBHOOK_INBOX_KEY).decrypt(CIPHERTEXT.encode())
        events = pickle.loads(zlib.decompress(base64.a85decode(plain_b85)))

        for ev in events:
            iso = datetime.datetime.fromtimestamp(ev["ts"], ZoneInfo({!r})).isoformat(timespec="seconds")
            print(ev["id"], iso, ev["payload"])
        """).format(body, len(ciphertext), tz)


class JsonEncoder:
    def encode(self, events):
        # return json.dumps(events, separators=(',', ':')).encode()  # Compact JSON
        return json.dumps(events, indent=2)  # pretty JSON


if WEBHOOK_INBOX_KEY:
    ENCODER = EncryptedEncoder(WEBHOOK_INBOX_KEY)
else:
    ENCODER = JsonEncoder()


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
        return RedirectResponse(url="/?" + urlencode(params), status_code=302)

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

    older_link = None
    if rows:
        oldest_ts = rows[-1][1]
        if CONN.execute("SELECT 1 FROM events WHERE ts < ? LIMIT 1",
                        (oldest_ts,)).fetchone():
            older_link = f"/?before={oldest_ts}&count={count}"

    ctx = {
        "request": req,
        "events_count": len(events),
        "older_link": older_link,
        # Convenience string like "[2024-05-16T09:00:00, 2024-05-16T10:00:00)"
        # that makes it obvious which side of the interval is closed and
        # which is open.
        "interval_str": None,  # filled in below
        "encoding": ENCODER.encode(events),
    }

    # Build a human-friendly representation of the timestamp interval that the
    # current page covers, e.g. "[2024-05-16T09:00:00, 2024-05-16T10:00:00)".
    if events:
        format_ts = lambda ts: datetime.fromtimestamp(ts, PAC).isoformat(timespec="seconds")
        start_iso = format_ts(events[-1]["ts"]) if events else "-∞"

        # If there are no earlier events (i.e. we're at the beginning of log
        # history) we still use a closed left bracket but add a marker so user
        # knows there is nothing before this page.
        if not older_link:
            start_iso = f"{start_iso} (beginning of history)"

        # Oldest event is included. Upper bound is exclusive (ts < before).
        ctx["interval_str"] = f"[{start_iso}, {format_ts(before_ts)})"

    return templates.TemplateResponse("events.html", ctx)

