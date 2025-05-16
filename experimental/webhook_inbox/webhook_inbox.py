"""
export WEBHOOK_INBOX_KEY='fgBWt1JKhqE6MbZAUntgZ7QBGJ0thPU1Su1qzU529l4='
uvicorn webhook_inbox:app --host 0.0.0.0 --port 8000
"""

import os, time, json, sqlite3, base64, binascii, logging
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse
import textwrap
from fastapi.templating import Jinja2Templates
from cryptography.fernet import Fernet
import zlib
import pickle

WEBHOOK_INBOX_KEY = os.getenv("WEBHOOK_INBOX_KEY", "")  # 44-char url-safe b64, or unset → no crypto
DB           = os.getenv("DB_PATH", "events.db")
MAX_PAYLOAD  = int(os.getenv("MAX_PAYLOAD", "16384"))
PAGE_SIZE    = int(os.getenv("PAGE_SIZE", "50"))
TZ = "America/Los_Angeles"
PAC          = ZoneInfo(TZ)
templates    = Jinja2Templates(directory="templates")

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
        chunks   = textwrap.wrap(ciphertext, 50)
        total    = len(chunks)
        body     = "\n".join(
            f'  {chunk!r}  # line {i+1}/{total}'
            for i, chunk in enumerate(chunks)
        )

        # 4. multiline literal + length assertion

        # 5. final template
        return textwrap.dedent(f"""\
        # The events are encoded in this ciphertext:
        CIPHERTEXT = (
        {body}
        )
        assert len(CIPHERTEXT) == {len(ciphertext)}

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
            iso = datetime.datetime.fromtimestamp(ev["ts"], ZoneInfo({tz!r})).isoformat(timespec="seconds")
            print(ev["id"], iso, ev["payload"])
        """)


class JsonEncoder:
    def encode(self, events):
        # return json.dumps(events, separators=(',', ':')).encode()  # Compact JSON
        return json.dumps(events, indent=2).encode()  # pretty JSON


if WEBHOOK_INBOX_KEY:
    ENCODER = EncryptedEncoder(WEBHOOK_INBOX_KEY)
else:
    ENCODER = JsonEncoder()


def db():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.execute("""CREATE TABLE IF NOT EXISTS events(
                   id      INTEGER PRIMARY KEY,
                   ts      INTEGER,
                   payload TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS access_log(
                   id      INTEGER PRIMARY KEY,
                   ts      INTEGER,
                   path    TEXT,
                   method  TEXT,
                   query   TEXT,
                   payload TEXT,
                   headers TEXT,
                   status  INTEGER)""")
    return c
CONN = db()

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

    # We still capture at most MAX_PAYLOAD bytes for the DB, but *do not* emit
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
    if "before" not in req.query_params:
        return RedirectResponse(url=f"/?before={int(time.time())}", status_code=302)

    try:
        before_ts = int(req.query_params["before"])
    except ValueError:
        raise HTTPException(400, "Invalid 'before' parameter. Expecting timestamp integer.")

    rows = CONN.execute(
        "SELECT id,ts,payload FROM events "
        "WHERE ts < ? ORDER BY ts DESC LIMIT ?", (before_ts, PAGE_SIZE)
    ).fetchall()

    events = [{"id": r[0], "ts": r[1], "payload": r[2]} for r in rows]

    older_link = None
    if rows:
        oldest_ts = rows[-1][1]
        if CONN.execute("SELECT 1 FROM events WHERE ts < ? LIMIT 1",
                        (oldest_ts,)).fetchone():
            older_link = f"/?before={oldest_ts}"

    ctx = {
        "request": req,
        "events_count": len(events),
        "older_link": older_link,
        "page_cutoff_iso": datetime.fromtimestamp(before_ts, PAC).isoformat(timespec="seconds"),
        "encoding": ENCODER.encode(events),
    }
    return templates.TemplateResponse("events.html", ctx)

