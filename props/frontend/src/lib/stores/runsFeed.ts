/**
 * WebSocket-based store for live runs and jobs feed.
 */
import { writable, derived } from "svelte/store";
import type { RunInfo, JobInfo } from "$lib/api/client";
import { getToken } from "$lib/stores/token";

// State
export const runs = writable<RunInfo[]>([]);
export const jobs = writable<JobInfo[]>([]);
export const connected = writable(false);

// Derived stores
export const activeJobs = derived(jobs, ($jobs) => $jobs.filter((j) => j.status === "running"));

// WebSocket connection (singleton)
let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let started = false;
let reconnectDelay = 1000; // Start at 1s, increase on failures
const MAX_RECONNECT_DELAY = 30000;

function getWsUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const base = `${protocol}//${window.location.host}/api/runs/feed`;
  const token = getToken();
  return token ? `${base}?token=${encodeURIComponent(token)}` : base;
}

function doConnect() {
  if (ws) {
    ws.close();
    ws = null;
  }

  try {
    ws = new WebSocket(getWsUrl());
  } catch (e) {
    console.warn("Failed to create WebSocket:", e);
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    connected.set(true);
    reconnectDelay = 1000; // Reset backoff on successful connection
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === "runs") {
        runs.set(msg.runs);
      } else if (msg.type === "jobs") {
        jobs.set(msg.jobs);
      }
    } catch (e) {
      console.warn("Failed to parse feed message:", e);
    }
  };

  ws.onclose = (event) => {
    connected.set(false);
    ws = null;
    // Don't reconnect on auth failures (4001) or policy violations (1008)
    if (event.code === 4001 || event.code === 1008) {
      console.warn("WebSocket closed due to auth failure, not reconnecting");
      return;
    }
    scheduleReconnect();
  };

  ws.onerror = () => {
    // onclose will be called after this
  };
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    doConnect();
  }, reconnectDelay);
  // Exponential backoff: double delay each time, cap at MAX_RECONNECT_DELAY
  reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
}

/** Start the WebSocket connection. Safe to call multiple times. */
export function startFeed() {
  if (started) return;
  started = true;
  doConnect();
}

/** Stop the WebSocket connection and cleanup. */
export function stopFeed() {
  started = false;
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (ws) {
    ws.close();
    ws = null;
  }
  connected.set(false);
}
