#!/usr/bin/env python3
"""
GNOME + logind event reporter + ActivityWatch batch uploader
 • Buffers while offline, bulk-posts when online
 • Retries every FLUSH_INTERVAL
 • Logs to systemd-journal
 • Polls ActivityWatch every AW_PERIOD and includes the data
"""

import json
import logging
import os
import signal
import socket
import time
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta

import requests
from gi.repository import GLib
from pydbus import SystemBus
from systemd.journal import JournalHandler

# ─ CONFIG ────────────────────────────────────────────────────────────────────
ENDPOINT = "https://webhook.agentydragon.com/"  # full URL
TIMEOUT = timedelta(seconds=3)  # HTTP timeout
FLUSH_INTERVAL = timedelta(minutes=10)  # retry cadence

# Maximum allowed JSON body size for a single POST request (bytes).  If the
# queue would result in a larger payload, it is split into multiple requests.
# Events whose individual payload would exceed the limit are dropped with an
# error logged.
MAX_PAYLOAD = 16_384  # 16 KiB – enforced hard limit sent to the server

# ActivityWatch
AW_API = "http://localhost:5600/api/0"
AW_PERIOD = timedelta(minutes=5)  # poll cadence

LOGLEVEL = "INFO"  # DEBUG / INFO
# ──────────────────────────────────────────────────────────────────────────────

# journal logger
log = logging.getLogger("login_event_webhook_reporter")
log.setLevel(LOGLEVEL)
log.addHandler(JournalHandler())
log.propagate = False

queue = []  # buffered events (list[dict])

# watermark; first poll covers last 5 min
aw_cur = datetime.now() - timedelta(minutes=5)


# ─ helpers ───────────────────────────────────────────────────────────────────
def _make_body(events: list[dict]) -> bytes:
    """Return JSON body bytes for *events* batch."""
    return json.dumps(
        {"host": socket.gethostname(), "events": events}, separators=(",", ":")
    ).encode()


def _post(body: bytes) -> bool:
    """Send *body* to the endpoint.  Return True on success."""
    try:
        urllib.request.urlopen(
            ENDPOINT, data=body, timeout=TIMEOUT.total_seconds()
        ).read()
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        log.warning("send failed; will retry", exc_info=True)
        return False


def _flush() -> bool:
    """Try to POST everything in *queue* adhering to MAX_PAYLOAD.

    Splits the queue into multiple requests so that each JSON body is below
    MAX_PAYLOAD bytes.  If a single event would exceed the limit by itself it
    is dropped and logged as an error.  On the first failed POST, the
    remaining (unsent) events are kept in *queue* for a later retry.
    """

    if not queue:
        return True

    sent_any = False  # did we manage to send at least one batch?
    while queue:
        batch: list[dict] = []

        # Build a batch whose encoded size stays within MAX_PAYLOAD.
        while queue:
            next_ev = queue[0]
            tentative_body = _make_body(batch + [next_ev])
            if len(tentative_body) <= MAX_PAYLOAD:
                batch.append(queue.pop(0))  # move from queue → batch
            else:
                # Adding next_ev would exceed limit.
                break

        if not batch:
            # Single event is too large even on its own -> drop it.
            oversized = queue.pop(0)
            size = len(_make_body([oversized]))
            log.error(
                "dropping oversized event %s (%d bytes > %d)",
                oversized.get("event", "?"),
                size,
                MAX_PAYLOAD,
            )
            continue  # try with remaining events

        body = _make_body(batch)

        if len(body) > MAX_PAYLOAD:
            # Sanity guard; shouldn't happen because of the logic above.
            log.error("internal error: constructed oversized payload – skipping batch")
            queue[:0] = batch  # prepend back for retry
            break

        if not _post(body):
            # Failed – prepend unsent events back to queue in original order.
            queue[:0] = batch  # type: ignore[slice-assignment]
            break

        # Success.
        sent_any = True
        log.info(
            "sent %d event(s) (%s), %.1f KiB",
            len(batch),
            " ".join(
                f"{v}×{k}"
                for k, v in Counter(ev["event"] for ev in batch).most_common()
            ),
            len(body) / 1024,
        )

    return not queue or sent_any


def _q(event, **ev):
    """Queue *ev* and attempt immediate flush."""
    queue.append(dict(event=event, **ev))
    log.info("queued %s (q=%d)", event, len(queue))
    _flush()


def _periodic(_: int) -> bool:
    _flush()
    return True  # keep timer


# ─ ActivityWatch polling ─────────────────────────────────────────────────────
def _aw_poll(_: int) -> bool:
    global aw_cur
    ts_from, aw_cur = aw_cur, datetime.now()  # advance watermark even if fetch fails

    try:
        buckets = requests.get(f"{AW_API}/buckets", timeout=3).json()
    except requests.RequestException:
        log.warning("AW bucket list error", exc_info=True)
        return True  # keep timer

    events_by_bucket = {}
    for bid in buckets:
        try:
            ev = requests.get(
                f"{AW_API}/buckets/{bid}/events",
                params={"start": ts_from.isoformat(timespec="seconds") + "Z"},
                timeout=3,
            ).json()
        except requests.RequestException:
            log.warning(f"AW bucket {bid=} get error", exc_info=True)
            continue
        if ev:
            events_by_bucket[bid] = ev

    if events_by_bucket:
        _q(
            event="activitywatch",
            since=ts_from.timestamp(),
            until=aw_cur.timestamp(),
            events=events_by_bucket,
        )
        total = sum(len(v) for v in events_by_bucket.values())
        log.debug("AW: queued %d events from %d buckets", total, len(events_by_bucket))
    return True  # keep timer


# ─ GNOME / logind hooks ──────────────────────────────────────────────────────
def emit(ev: str):
    _q(event=ev, ts=int(time.time()))


bus = SystemBus()
mgr = bus.get("org.freedesktop.login1")


def _find_session():
    """Locate our login1 session path."""
    sid, uid = os.environ.get("XDG_SESSION_ID"), os.getuid()
    matches = []
    for s_id, u, _user, _seat, path in mgr.ListSessions():
        if sid and s_id == sid:
            matches.append(path)
        elif u == uid:
            matches.append(path)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise RuntimeError("multiple sessions – set XDG_SESSION_ID")
    raise RuntimeError("no sessions – set XDG_SESSION_ID")


session = bus.get(".login1", _find_session())
session.onLock = lambda *_: emit("locked")
session.onUnlock = lambda *_: emit("unlocked")
mgr.onPrepareForSleep = lambda down: emit("suspending" if down else "resumed")


def goodbye(*_):
    emit("session_end")
    loop.quit()


emit("session_start")

# ─ timers & mainloop ─────────────────────────────────────────────────────────
GLib.timeout_add_seconds(int(FLUSH_INTERVAL.total_seconds()), _periodic, 0)
GLib.timeout_add_seconds(int(AW_PERIOD.total_seconds()), _aw_poll, 0)

loop = GLib.MainLoop()
for sig in (signal.SIGINT, signal.SIGTERM):
    signal.signal(sig, goodbye)
loop.run()
