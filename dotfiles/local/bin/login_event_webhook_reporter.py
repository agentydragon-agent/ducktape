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
def _flush() -> bool:
    """Try to POST everything in *queue*; keep data if it fails."""
    if not queue:
        return True
    body = json.dumps({"host": socket.gethostname(), "events": queue}).encode()
    try:
        urllib.request.urlopen(
            ENDPOINT, data=body, timeout=TIMEOUT.total_seconds()
        ).read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        log.warning("send failed; will retry", exc_info=True)
        return False
    log.info(
        "sent %d payload(s) (%s), %.1f KiB total",
        len(queue),
        " ".join(
            f"{v}×{k}" for k, v in Counter(ev["event"] for ev in queue).most_common()
        ),
        len(body) / 1024,
    )
    queue.clear()
    return True


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
