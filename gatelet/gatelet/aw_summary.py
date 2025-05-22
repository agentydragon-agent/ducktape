#!/usr/bin/env python3
"""ActivityWatch quick-look reporter.

This small utility fetches recent events directly from ActivityWatch
buckets and prints a short summary. It mirrors the implementation used
by Gatelet for its dashboard view.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Tuple

from aw_client import ActivityWatchClient


def pick_buckets(client: ActivityWatchClient) -> Tuple[List[str], List[str], List[str]]:
    """Return lists of window, web, and afk bucket IDs."""
    buckets = client.get_buckets()
    window_bk = [b for b in buckets if b.startswith("aw-watcher-window")]
    web_bk = [b for b in buckets if b.startswith("aw-watcher-web")]
    afk_bk = [b for b in buckets if b.startswith("aw-watcher-afk")]
    return window_bk, web_bk, afk_bk


def iter_events(
    client: ActivityWatchClient, bucket_ids: List[str], start: datetime, end: datetime
):
    """Yield events from all buckets in [start, end)."""
    for bid in bucket_ids:
        for ev in client.get_events(bid, start=start, end=end):
            yield ev


def summarize(minutes: int | None = 30, *, day: date | None = None) -> None:  # noqa: PLR0912 - clarity over brevity
    now = datetime.now(timezone.utc)

    if day:
        start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        label = day.isoformat()
    else:
        start = now - timedelta(minutes=minutes or 15)
        end = now
        label = f"last {round((end - start).total_seconds() / 60)} min"

    client = ActivityWatchClient("aw-summary")
    client.connect()

    window_bk, web_bk, afk_bk = pick_buckets(client)

    app_secs: Dict[str, float] = defaultdict(float)
    url_secs: Dict[str, float] = defaultdict(float)
    afk_secs = 0.0
    active_secs = 0.0

    for ev in iter_events(client, window_bk, start, end):
        dur = ev.get("duration", 0)
        if isinstance(dur, timedelta):
            dur = dur.total_seconds()
        app = ev["data"].get("app", "unknown-app")
        app_secs[app] += dur

    for ev in iter_events(client, web_bk, start, end):
        dur = ev.get("duration", 0)
        if isinstance(dur, timedelta):
            dur = dur.total_seconds()
        url = ev["data"].get("url")
        if url:
            url_secs[url] += dur

    for ev in iter_events(client, afk_bk, start, end):
        dur = ev.get("duration", 0)
        if isinstance(dur, timedelta):
            dur = dur.total_seconds()
        status = ev["data"].get("status", "unknown")
        if status == "afk":
            afk_secs += dur
        else:
            active_secs += dur

    print(
        f"\nActivityWatch summary for {label} ({start.isoformat()} → {end.isoformat()})\n"
    )

    tot_secs = active_secs + afk_secs

    def pct(x: float) -> str:
        return f"{100 * x / tot_secs:5.1f}%" if tot_secs else "n/a"

    print("AFK vs Active")
    print(f"  Active : {active_secs / 60:6.1f} min  ({pct(active_secs)})")
    print(f"  AFK    : {afk_secs / 60:6.1f} min  ({pct(afk_secs)})\n")

    print("Top applications")
    for app, secs in sorted(app_secs.items(), key=lambda kv: kv[1], reverse=True)[:10]:
        print(f"  {secs / 60:6.1f} min  {app}")

    print("\nTop URLs")
    for url, secs in sorted(url_secs.items(), key=lambda kv: kv[1], reverse=True)[:10]:
        print(f"  {secs / 60:6.1f} min  {url}")

    # TODO: test with actual web watcher events when available


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="ActivityWatch quick summary")
    ap.add_argument(
        "--day", metavar="YYYY-MM-DD", help="daily summary for given date (UTC)"
    )
    ap.add_argument(
        "--mins",
        type=int,
        default=15,
        help="rolling window length in minutes (ignored if --day)",
    )
    args = ap.parse_args()

    chosen_day = date.fromisoformat(args.day) if args.day else None
    summarize(None if chosen_day else args.mins, day=chosen_day)
