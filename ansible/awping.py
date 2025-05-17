#!/usr/bin/env python3
import datetime, json, os, socket, sys, requests

WEBHOOK = "https://webhook.agentydragon.com/"
HOSTCHK = ("agentydragon.com", 443)   # change if you move the inbox

try:
    socket.create_connection(HOSTCHK, 2)    # 2-second timeout
except OSError:
    print("offline")
    sys.exit(0)                             # offline → silent exit

SINCE = (datetime.datetime.utcnow() - datetime.timedelta(minutes=5)).isoformat() + "Z"

# TODO: also add URL watchers etc
buckets = requests.get("http://localhost:5600/api/0/buckets").json()
all_events = []
for bid in buckets:
    ev = requests.get(f"http://localhost:5600/api/0/buckets/{bid}/events",
                      params={"start": SINCE}, timeout=3).json()
    if ev:
        all_events.extend([{"bucket": bid, "data": e} for e in ev])

payload = {"host": os.uname().nodename, "since": SINCE, "events": all_events}
out = requests.post(WEBHOOK, json=payload, timeout=3)
print(out.text)
out.raise_for_status()
print("sent:")
print(json.dumps(payload, indent=2))
