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

# Titles whose aggregated duration is below this many seconds are coalesced
# into a generic "other" entry per app.  Helps keep payload compact by
# discarding extremely brief window switches.
MERGE_SHORT_TITLE_SEC = 3  # seconds

# ──────────────────────────────────────────────────────────────────────────────
# Lightweight CLI (runs before resident initialisation)

import argparse
import sys


def _run_cli_helpers() -> None:
    """Handle one-off helper command-line flags that should exit quickly.

    Currently supports only ``--aw-dump`` which performs a single ActivityWatch
    poll (since the initial high-water-mark of *now − 5 min*) and prints the
    payload that would have been queued by the daemon to *stdout*.
    """

    cli = argparse.ArgumentParser(add_help=False)
    cli.add_argument(
        "--aw-dump",
        action="store_true",
        help="Query ActivityWatch once, dump resulting JSON payload to stdout, then exit.",
    )

    args, _unknown = cli.parse_known_args()

    if not args.aw_dump:
        return  # no helper flags – proceed with normal initialisation

    # Helper mode active – perform minimal work and exit.
    ts_from = datetime.now() - timedelta(minutes=5)
    events_by_bucket, ts_to = _collect_aw_events(ts_from)

    payload = {
        "event": "activitywatch",
        "since": int(ts_from.timestamp()),
        "until": int(ts_to.timestamp()),
        "events": events_by_bucket,
    }

    _ensure_aw_size(payload)

    # Serialize once so we can report accurate byte size.
    json_blob = json.dumps(payload, separators=(",", ":"))
    print(f"{len(json_blob.encode()):,} bytes")
    print(json_blob)
    sys.exit(0)


# The helper handler will be invoked a bit later once the shared *_collect_aw_events*
# function becomes available so that we don't have to duplicate any logic.
# ──────────────────────────────────────────────────────────────────────────────

# journal logger
log = logging.getLogger("login_event_webhook_reporter")
log.setLevel(LOGLEVEL)
log.addHandler(JournalHandler())
log.propagate = False

queue = []  # buffered events (list[dict])

# watermark; first poll covers last 5 min
aw_cur = datetime.now() - timedelta(minutes=5)

# ─ immediate AW snapshot helper ─────────────────────────────────────────────


def _send_aw_snapshot() -> None:
    """Collect ActivityWatch events *since the current watermark* and queue
    them immediately.  Also advances the global watermark ``aw_cur``.

    Called on:
      • SIGUSR1 (manual trigger)
      • System suspend (PrepareForSleep True)
    """

    global aw_cur

    ts_from = aw_cur
    events_by_bucket, ts_to = _collect_aw_events(ts_from)
    aw_cur = ts_to

    if not events_by_bucket:
        return

    ev_payload = {
        "event": "activitywatch",
        "since": int(ts_from.timestamp()),
        "until": int(ts_to.timestamp()),
        "events": events_by_bucket,
    }

    _ensure_aw_size(ev_payload)

    _q(**ev_payload)

    log.info(
        "AW snapshot queued via signal/suspend (size=%d bytes)",
        len(_make_body([ev_payload])),
    )


# ─ helpers ───────────────────────────────────────────────────────────────────
def _make_body(events: list[dict]) -> bytes:
    """Return JSON body bytes for *events* batch."""
    return json.dumps(
        {"host": socket.gethostname(), "events": events},
        separators=(",", ":"),
    ).encode()


def _post(body: bytes) -> bool:
    """Send *body* to the endpoint.  Return True on success."""
    try:
        urllib.request.urlopen(
            ENDPOINT,
            data=body,
            timeout=TIMEOUT.total_seconds(),
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
def _collect_aw_events(ts_from: datetime) -> tuple[dict[str, list], datetime]:
    """Return a tuple ``(events_by_bucket, ts_to)`` containing ActivityWatch
    events that occurred since *ts_from* (inclusive).

    Additional normalisation is applied so that downstream consumers receive a
    trimmed-down representation suited for webhook transport and debugging:

    • Each event’s ``timestamp`` ISO string is replaced by an integer ``ts``
      field containing Unix seconds.
    • Events whose ``duration`` is present and **< 1.0 s** are dropped.

    Any *requests* failures are internally caught – the function never raises
    and returns an empty mapping when polling fails.
    """

    ts_to = datetime.now()

    try:
        buckets = requests.get(f"{AW_API}/buckets", timeout=3).json()
    except requests.RequestException:
        log.warning("AW bucket list error", exc_info=True)
        return {}, ts_to

    events_by_bucket: dict[str, list] = {}

    for bid in buckets:
        try:
            evs = requests.get(
                f"{AW_API}/buckets/{bid}/events",
                params={"start": ts_from.isoformat(timespec="seconds") + "Z"},
                timeout=3,
            ).json()
        except requests.RequestException:
            log.warning(f"AW bucket {bid=} get error", exc_info=True)
            continue

        # Aggregate durations by app -> title -> seconds
        agg: dict[str, dict[str, int]] = {}
        misc: list[dict] = []  # for buckets w/o app/title

        for ev in evs:
            dur = ev.get("duration", 0)
            if not isinstance(dur, (int, float)) or dur < 1:
                continue

            data = ev.get("data", {}) or {}
            app, title = data.get("app"), data.get("title")

            if app and title:
                per_app = agg.setdefault(app, {})
                per_app[title] = per_app.get(title, 0) + int(dur)
            else:
                other_entry: dict = {"dur": int(dur)}
                other_entry.update(
                    {k: v for k, v in data.items() if k not in ("app", "title")},
                )
                misc.append(other_entry)

        # Merge tiny titles (< MERGE_SHORT_TITLE_SEC) into "other" per app.
        for app, titles in agg.items():
            small_titles = [t for t, d in titles.items() if d < MERGE_SHORT_TITLE_SEC]
            if small_titles:
                other_total = sum(titles.pop(t) for t in small_titles)
                titles["other"] = titles.get("other", 0) + other_total

        # Desired structure: per app → {title: dur, ...}
        out_obj: dict[str, dict[str, int] | list] = {
            app: titles for app, titles in agg.items()
        }

        if misc:
            out_obj["_other"] = misc  # reserved key for non-window items

        if out_obj:
            events_by_bucket[bid] = out_obj

    return events_by_bucket, ts_to


# ─ Compaction to fit size limit ──────────────────────────────────────────────

_AW_SAFETY = 200  # bytes kept below MAX_PAYLOAD to leave space for queue metadata


def _ensure_aw_size(ev_dict: dict) -> None:
    """Mutate *ev_dict* (activitywatch event) merging smallest title entries
    into an "other" bucket until its encoded size fits below
    ``MAX_PAYLOAD - _AW_SAFETY`` bytes.
    """

    threshold = MAX_PAYLOAD - _AW_SAFETY

    def _cur_size() -> int:
        return len(_make_body([ev_dict]))

    if _cur_size() <= threshold:
        return

    # Build list of (dur, bucket, app, title) for candidate merges.
    items: list[tuple[int, str, str, str]] = []
    events_by_bucket: dict = ev_dict.get("events", {})
    for bucket_id, bucket_data in events_by_bucket.items():
        if not isinstance(bucket_data, dict):
            continue
        for app, titles in bucket_data.items():
            if not isinstance(titles, dict):
                continue
            for title, dur in titles.items():
                if title == "other":
                    continue  # can't merge further
                if isinstance(dur, int):
                    items.append((dur, bucket_id, app, title))

    # Sort by ascending duration so we sacrifice least significant entries first.
    items.sort()

    for dur, bucket_id, app, title in items:
        bdata = events_by_bucket[bucket_id][app]
        # Remove specific title.
        del bdata[title]
        # Aggregate into "other".
        bdata["other"] = bdata.get("other", 0) + dur

        if _cur_size() <= threshold:
            break

    # Final check – if still oversized, log warning and leave as-is; flush()
    if _cur_size() > threshold:
        log.warning(
            "AW payload still %d bytes after compaction (limit %d)",
            _cur_size(),
            threshold,
        )


# Handle any helper CLI flags *now* (after _collect_aw_events is available but
# still before the heavy resident initialisation below).
_run_cli_helpers()

# ─ startup notice ────────────────────────────────────────────────────────────

log.info("AW snapshot trigger: run `kill -USR1 %d` to send immediately", os.getpid())


def _aw_poll(_: int) -> bool:
    global aw_cur

    ts_from = aw_cur
    events_by_bucket, ts_to = _collect_aw_events(ts_from)
    aw_cur = ts_to  # advance watermark

    if events_by_bucket:
        ev_payload = {
            "event": "activitywatch",
            "since": int(ts_from.timestamp()),
            "until": int(ts_to.timestamp()),
            "events": events_by_bucket,
        }

        _ensure_aw_size(ev_payload)

        _q(**ev_payload)

        total_dur = sum(
            dur
            for bucket in events_by_bucket.values()
            if isinstance(bucket, dict)
            for app_map in bucket.values()
            if isinstance(app_map, dict)
            for dur in app_map.values()
            if isinstance(dur, int)
        )

        log.debug(
            "AW: queued durations=%d s, buckets=%d, size=%d bytes",
            total_dur,
            len(events_by_bucket),
            len(_make_body([ev_payload])),
        )
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
        if (sid and s_id == sid) or u == uid:
            matches.append(path)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise RuntimeError("multiple sessions – set XDG_SESSION_ID")
    raise RuntimeError("no sessions – set XDG_SESSION_ID")


session = bus.get(".login1", _find_session())
session.onLock = lambda *_: emit("locked")
# Replace simple lambdas with richer handlers.

session.onUnlock = lambda *_: emit("unlocked")


def _on_prepare_for_sleep(down: bool):
    if down:
        # Pre-suspend – emit event and send AW snapshot for the period up to now.
        emit("suspending")
        _send_aw_snapshot()
    else:
        emit("resumed")


mgr.onPrepareForSleep = _on_prepare_for_sleep


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
# SIGUSR1 – immediate AW snapshot


def _sigusr1_handler(signum, frame):  # pragma: no cover
    # Schedule on mainloop to avoid doing heavy work in signal context.
    GLib.idle_add(lambda: (_send_aw_snapshot() or False))


signal.signal(signal.SIGUSR1, _sigusr1_handler)
loop.run()
