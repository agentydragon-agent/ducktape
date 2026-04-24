// Event-sourced state sync.
//
// Reads:  GET /state -> {state, last_event_id, etag}. Cached in IndexedDB so
//         the PWA can render something instantly on cold load.
// Writes: POST /events with a batch of events and an If-Match ETag. On 412
//         (another device wrote in the meantime) we pull the server copy and
//         the UI reconciles. On network failure we don't queue — the caller
//         decides whether to retry; losing an emit here just means the action
//         didn't happen from the server's perspective, which for a casino app
//         is fine (user retries the action).
//
// There is no PUT /state — the server is the source of truth and is only
// mutated by appending events. The only reason IDB still exists here is
// offline cold-load cache; it is NOT authoritative.

import { get as idbGet, set as idbSet } from "idb-keyval";

const STATE_CACHE_KEY = "state-cache-v2";
const ETAG_CACHE_KEY = "etag-cache-v2";

export const BACKEND_STATE_URL = "/state";
export const BACKEND_EVENTS_URL = "/events";

export async function loadState() {
  try {
    const response = await fetch(BACKEND_STATE_URL, { credentials: "same-origin" });
    if (response.ok) {
      const body = await response.json();
      await idbSet(STATE_CACHE_KEY, body);
      await idbSet(ETAG_CACHE_KEY, body.etag);
      return body;
    }
  } catch (e) {
    // Offline or backend down — fall back to IDB cache.
  }
  return (await idbGet(STATE_CACHE_KEY)) ?? null;
}

/** POST a batch of events. Returns the new authoritative snapshot.
 *
 * `events` is an array of `{type, ts_ms, payload}` objects.
 * `etag` is the client's last-known ETag; send null to skip If-Match
 * (useful on first launch when no prior state exists, but then concurrent
 * writes from another device can blind-overwrite — the server treats a
 * missing If-Match as "I accept any current state").
 */
export async function appendEvents(events, etag) {
  const headers = { "Content-Type": "application/json" };
  if (etag) headers["If-Match"] = etag;
  const response = await fetch(BACKEND_EVENTS_URL, {
    method: "POST",
    credentials: "same-origin",
    headers,
    body: JSON.stringify(events),
  });
  if (response.status === 412) {
    // Stale ETag — another device wrote since our last read. Pull remote
    // and let the caller reconcile (typically by refreshing local state
    // and asking the user to retry, or auto-retrying with fresh ETag).
    const fresh = await loadState();
    throw new StaleStateError(fresh);
  }
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`append failed: HTTP ${response.status} ${body}`);
  }
  const body = await response.json();
  await idbSet(STATE_CACHE_KEY, body);
  await idbSet(ETAG_CACHE_KEY, body.etag);
  return body;
}

export class StaleStateError extends Error {
  constructor(fresh) {
    super("state stale; caller should reconcile");
    this.name = "StaleStateError";
    this.fresh = fresh;
  }
}
