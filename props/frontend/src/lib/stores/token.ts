/**
 * Admin token management - capture from URL, store in localStorage,
 * provide to API client and WebSocket.
 */
import { writable } from "svelte/store";

const STORAGE_KEY = "props_admin_token";

export const needsToken = writable(false);

export function getToken(): string | null {
  return localStorage.getItem(STORAGE_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(STORAGE_KEY, token);
  needsToken.set(false);
}

export function clearToken(): void {
  localStorage.removeItem(STORAGE_KEY);
  needsToken.set(true);
}

/** Capture token from URL query param, store it, and strip from URL. */
export function captureTokenFromUrl(): void {
  const params = new URLSearchParams(window.location.search);
  const token = params.get("token");
  if (token) {
    setToken(token);
    params.delete("token");
    const newSearch = params.toString();
    const newUrl = window.location.pathname + (newSearch ? `?${newSearch}` : "") + window.location.hash;
    history.replaceState(null, "", newUrl);
  }
}

/** Signal that auth failed (401) - shows paste-token UI if no token stored. */
export function onAuthFailed(): void {
  clearToken();
}
