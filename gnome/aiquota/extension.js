import GLib from "gi://GLib";
import GObject from "gi://GObject";
import Gio from "gi://Gio";
import St from "gi://St";
import Clutter from "gi://Clutter";
import Soup from "gi://Soup";
import Secret from "gi://Secret";

import { Extension } from "resource:///org/gnome/shell/extensions/extension.js";
import * as Main from "resource:///org/gnome/shell/ui/main.js";
import * as PanelMenu from "resource:///org/gnome/shell/ui/panelMenu.js";
import * as PopupMenu from "resource:///org/gnome/shell/ui/popupMenu.js";

const CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage";
const CLAUDE_TOKEN_URL = "https://platform.claude.com/v1/oauth/token";
const CLAUDE_OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e";
const CLAUDE_OAUTH_SCOPES = [
  "user:profile",
  "user:inference",
  "user:sessions:claude_code",
  "user:mcp_servers",
  "user:file_upload",
];
const CODEX_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage";
const ZAI_QUOTA_URL = "https://api.z.ai/api/monitor/usage/quota/limit";
const POLL_INTERVAL_SECONDS = 120;
const STALE_AFTER_SECONDS = 5 * 60;
const TOKEN_EXPIRY_SKEW_SECONDS = 30;

// Pace deviation thresholds, in signed percentage points (used% − expected%).
const PACE_COOL_BELOW = -10;
const PACE_WARN_ABOVE = 5;
const PACE_HOT_ABOVE = 15;
const SHORT_WIN_HOT_PERCENT = 85;
const STABLE_FRACTION = 0.05;

// Window total lengths. Codex returns `limit_window_seconds`; Claude does not.
const CLAUDE_SHORT_W = 5 * 3600;
const CLAUDE_LONG_W = 7 * 86400;
// z.ai: 5h rolling quota (GLM-5.1 burns at 3× during peak hours 14:00–18:00 UTC+8,
// currently 1× off-peak through end of June). The 7d window always has nextResetTime.
// The 5h window frequently lacks nextResetTime (especially at 0% usage), so pace math
// degrades gracefully to usedPercent-only display.
const ZAI_SHORT_W = 5 * 3600;
const ZAI_LONG_W = 7 * 86400;

const CODEX_KEYRING_SCHEMA = new Secret.Schema("org.freedesktop.Secret.Generic", Secret.SchemaFlags.DONT_MATCH_NAME, {
  service: Secret.SchemaAttributeType.STRING,
  username: Secret.SchemaAttributeType.STRING,
});

const TINT_CLASSES = [
  "quota-cool",
  "quota-ok",
  "quota-warn",
  "quota-hot",
  "quota-unknown",
  "quota-stale",
  "quota-error",
];
const TINT_RANK = { unknown: 0, stale: 0, ok: 1, cool: 1, warn: 2, hot: 3 };

// Per-provider enable flags are read from ~/.config/aiquota/config.json.
// Missing file or missing key → provider is shown (default on).
function readExtensionConfig() {
  const path = `${GLib.get_home_dir()}/.config/aiquota/config.json`;
  try {
    const [ok, bytes] = GLib.file_get_contents(path);
    if (!ok) return {};
    return JSON.parse(decodeBytes(bytes));
  } catch {
    return {};
  }
}

function decodeBytes(bytes) {
  return new TextDecoder().decode(typeof bytes.get_data === "function" ? bytes.get_data() : bytes);
}

function errorMessage(error) {
  return error?.message ?? String(error);
}

function formatUtcTimestamp(ms) {
  const date = new Date(ms);
  if (Number.isNaN(date.getTime())) return String(ms);
  return date
    .toISOString()
    .replace(/:\d{2}\.\d{3}Z$/, "Z")
    .replace("T", " ");
}

function objectSummary(value) {
  if (value == null) return String(value);
  if (typeof value !== "object" || Array.isArray(value)) return typeof value;
  const keys = Object.keys(value);
  return keys.length ? `keys: ${keys.join(", ")}` : "empty object";
}

function messageStatus(message) {
  if (typeof message.get_status === "function") return message.get_status();
  return message.status_code ?? 0;
}

function isHttpErrorStatus(status) {
  return status !== 0 && (status < 200 || status >= 300);
}

function httpErrorMessage(status, body, rawBody) {
  const statusLabel = status === 0 ? "error" : status;
  const apiError = body?.error;
  if (apiError?.message) {
    return `HTTP ${statusLabel} ${apiError.type ?? "error"}: ${apiError.message}`;
  }
  if (body?.message) return `HTTP ${statusLabel}: ${body.message}`;
  const bodyPreview = rawBody ? `: ${rawBody.slice(0, 160)}` : "";
  return `HTTP ${statusLabel}${bodyPreview}`;
}

class HttpResponseError extends Error {
  constructor(status, body, rawBody) {
    super(httpErrorMessage(status, body, rawBody));
    this.name = "HttpResponseError";
    this.status = status;
    this.body = body;
    this.rawBody = rawBody;
  }
}

function parseScopes(scopeString, fallback) {
  if (typeof scopeString !== "string") return fallback ?? [];
  return scopeString.split(/\s+/).filter(Boolean);
}

function formatDuration(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return "?";
  const s = Math.max(0, Math.round(seconds));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d${h}h`;
  if (h > 0) return `${h}h${m}m`;
  return `${m}m`;
}

function parseClaudeResetAtMs(timestamp, label) {
  if (typeof timestamp !== "string") return null;
  const ms = new Date(timestamp).getTime();
  if (!Number.isFinite(ms)) return null;
  return ms;
}

function codexResetAtMsFromResetAfter(node, label) {
  const resetAfterSeconds = Number(node?.reset_after_seconds ?? NaN);
  if (!Number.isFinite(resetAfterSeconds) || resetAfterSeconds < 0) {
    throw new Error(`${label} window missing reset_after_seconds`);
  }
  return Date.now() + resetAfterSeconds * 1000;
}

function withLiveReset(state) {
  if (!state?.resetAtMs) return state;
  return {
    ...state,
    resetSeconds: Math.max(0, (state.resetAtMs - Date.now()) / 1000),
  };
}

function isStaleFetch(lastFetch) {
  return lastFetch != null && (Date.now() - lastFetch) / 1000 > STALE_AFTER_SECONDS;
}

function formatFreshness(lastFetch) {
  if (lastFetch == null) return "no successful refresh yet";
  const ageSeconds = Math.max(0, (Date.now() - lastFetch) / 1000);
  const age = ageSeconds < 60 ? `${Math.round(ageSeconds)}s` : formatDuration(ageSeconds);
  return `${isStaleFetch(lastFetch) ? "stale, " : ""}updated ${age} ago`;
}

// Pure pace computation. See DESIGN.md ("Pace math") for derivation.
function computePace({ usedPercent, resetSeconds, windowSeconds }) {
  if (usedPercent == null || resetSeconds == null || windowSeconds == null || windowSeconds <= 0) {
    return null;
  }
  const elapsedSecs = windowSeconds - resetSeconds;
  const elapsedFrac = elapsedSecs / windowSeconds;
  const expectedPercent = elapsedFrac * 100;
  const deviation = usedPercent - expectedPercent;
  let projectedAtReset = null;
  let secondsToExhaust = null;
  if (elapsedSecs > 0 && usedPercent > 0) {
    const ratePerSec = usedPercent / elapsedSecs;
    secondsToExhaust = (100 - usedPercent) / ratePerSec;
    projectedAtReset = usedPercent + ratePerSec * resetSeconds;
  }
  const stable = elapsedFrac > STABLE_FRACTION && elapsedFrac < 1 - STABLE_FRACTION;
  return { elapsedFrac, deviation, projectedAtReset, secondsToExhaust, stable };
}

function tintFor({ pace, usedPercent, isShort }) {
  if (usedPercent == null) return "unknown";
  if (isShort && usedPercent >= SHORT_WIN_HOT_PERCENT) return "hot";
  if (!pace || !pace.stable) {
    if (usedPercent >= 95) return "hot";
    if (usedPercent >= 80) return "warn";
    return "ok";
  }
  if (pace.deviation >= PACE_HOT_ABOVE) return "hot";
  if (pace.deviation >= PACE_WARN_ABOVE) return "warn";
  if (pace.deviation <= PACE_COOL_BELOW) return "cool";
  return "ok";
}

// Hot short window always wins (urgent throttle). Otherwise take the worse of
// the two tints, with the long window's "ok"/"cool" as the default.
function bindingTint(shortTint, longTint) {
  if (shortTint === "hot") return "hot";
  return TINT_RANK[shortTint] > TINT_RANK[longTint] ? shortTint : longTint;
}

function formatPace(pace) {
  if (!pace || !pace.stable) return null;
  const sign = pace.deviation >= 0 ? "+" : "−";
  return `${sign}${Math.abs(Math.round(pace.deviation))}%`;
}

function formatForecast(pace, resetSeconds) {
  if (!pace || !pace.stable || pace.projectedAtReset == null) return null;
  const projected = pace.projectedAtReset;
  if (projected > 100.5) {
    const shortfall = resetSeconds - pace.secondsToExhaust;
    return `exhausts ~${formatDuration(shortfall)} before reset`;
  }
  if (projected < 95) {
    return `leaves ~${Math.round(100 - projected)}% unused at reset`;
  }
  return "on pace";
}

function formatCompactDollars(cents) {
  const dollars = cents / 100;
  if (dollars >= 1000) {
    const k = dollars / 1000;
    return `$${k >= 10 ? Math.round(k) : Math.round(k * 10) / 10}k`;
  }
  return `$${Math.round(dollars)}`;
}

function formatExtraUsage(extra) {
  if (!extra || !extra.is_enabled) return null;
  const used = extra.used_credits / 100;
  const limit = extra.monthly_limit / 100;
  const pct = Math.round(extra.utilization);
  return `extra $${Math.round(used)}/$${Math.round(limit)} (${pct}%)`;
}

function clamp01(value) {
  if (value == null || !Number.isFinite(value)) return null;
  return Math.max(0, Math.min(1, value));
}

function elapsedFraction(state) {
  if (state?.resetSeconds == null || state?.windowSeconds == null || state.windowSeconds <= 0) return null;
  return clamp01((state.windowSeconds - state.resetSeconds) / state.windowSeconds);
}

function windowFromClaude(node, label, windowSeconds) {
  if (!node) return null;
  const resetAtMs = parseClaudeResetAtMs(node.resets_at, label);
  return {
    usedPercent: node.utilization ?? null,
    resetAtMs,
    resetSeconds: resetAtMs == null ? null : Math.max(0, (resetAtMs - Date.now()) / 1000),
    windowSeconds,
  };
}

function windowFromCodex(node, label) {
  if (!node) return null;
  const windowSeconds = Number(node.limit_window_seconds ?? NaN);
  if (!Number.isFinite(windowSeconds) || windowSeconds <= 0) {
    throw new Error(`${label} window missing limit_window_seconds`);
  }
  const resetAtMs = codexResetAtMsFromResetAfter(node, label);
  return {
    usedPercent: node.used_percent ?? null,
    resetAtMs,
    resetSeconds: resetAtMs == null ? null : Math.max(0, (resetAtMs - Date.now()) / 1000),
    windowSeconds,
  };
}

function windowFromZai(node, windowSeconds) {
  if (!node) return null;
  const usedPercent = node.percentage ?? null;
  const resetAtMs = node.nextResetTime ?? null;
  return {
    usedPercent,
    resetAtMs,
    resetSeconds: resetAtMs == null ? null : Math.max(0, (resetAtMs - Date.now()) / 1000),
    windowSeconds,
  };
}

function emptyProviderState() {
  return { short: null, long: null, lastFetch: null, error: null, extraUsage: null };
}

// Descriptor for each provider. All runtime state (UI elements, fetch state)
// is attached at init time and referenced by id.
const PROVIDER_DEFS = [
  { id: "claude", label: "Claude", iconFile: "claude-symbolic.svg" },
  { id: "codex", label: "Codex", iconFile: "openai-symbolic.svg" },
  { id: "zai", label: "z.ai", iconFile: "zai-symbolic.svg" },
];

const QuotaIndicator = GObject.registerClass(
  class QuotaIndicator extends PanelMenu.Button {
    _init(extension) {
      super._init(0.0, "AI Quota Tracker", false);

      this._iconsDir = `${extension.path}/icons`;
      this._settings = extension.getSettings();
      this._httpSession = new Soup.Session();
      this._popupTickId = null;

      const fixturePath = GLib.getenv("AI_QUOTA_FIXTURE");
      if (fixturePath) {
        // Provider visibility derived from which keys are present in the fixture.
        const [ok, bytes] = GLib.file_get_contents(fixturePath);
        if (!ok) throw new Error(`fixture not readable: ${fixturePath}`);
        const fixtureData = JSON.parse(decodeBytes(bytes));
        const shows = {};
        for (const { id } of PROVIDER_DEFS) shows[id] = id in fixtureData;
        this._initUI(shows);
        this._loadFixtureData(fixtureData);
        this._exportTestInterface();
        return;
      }

      const cfg = readExtensionConfig();
      const shows = {};
      for (const { id } of PROVIDER_DEFS) shows[id] = cfg[`show${id.charAt(0).toUpperCase()}${id.slice(1)}`] !== false;
      this._initUI(shows);
      this._refresh();
      this._timerId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, POLL_INTERVAL_SECONDS, () => {
        this._refresh();
        return GLib.SOURCE_CONTINUE;
      });
    }

    // Set up per-provider state, build panel + popup, wire menu open handler.
    _initUI(shows) {
      // _providers: array of enabled provider descriptors with their runtime state and UI refs.
      this._providers = PROVIDER_DEFS.filter(({ id }) => shows[id]).map((def) => ({
        ...def,
        state: emptyProviderState(),
        icon: null,
        paceLabel: null,
        header: null,
        shortRow: null,
        longRow: null,
      }));

      this._buildPanel();
      this._buildPopup();
      this._menuOpenId = this.menu.connect("open-state-changed", (_menu, open) => {
        if (open) {
          this._renderPopup();
          this._startPopupTick();
        } else {
          this._stopPopupTick();
        }
      });
    }

    _loadFixtureData(data) {
      const provider = (node) => ({
        short: node?.short ?? null,
        long: node?.long ?? null,
        lastFetch: node?.lastFetch != null ? Date.now() : null,
        error: node?.error ?? null,
        extraUsage: node?.extraUsage ?? null,
      });
      for (const p of this._providers) p.state = provider(data[p.id]);
      this._renderPanel();
      this._renderPopup();
    }

    _exportTestInterface() {
      // Session-bus interface used only by the golden render tests
      // (AI_QUOTA_FIXTURE gates the entire path). The test driver
      // launches gnome-shell once per session and then swaps fixtures /
      // toggles the menu via this surface, so renders get amortized
      // over a single shell process.
      //   Reload(path)         — load fixture state from JSON, re-render.
      //   OpenMenu / CloseMenu — toggle popup, no animation.
      //   GetMenuGeometry      — screen-space (x,y,w,h) bounding box of
      //                          the open menu, for precise screenshot crop.
      this._testIface = Gio.DBusExportedObject.wrapJSObject(
        '<node><interface name="works.allegedly.AiQuotaTest">' +
          '<method name="Reload"><arg type="s" direction="in" name="path"/></method>' +
          '<method name="OpenMenu"/>' +
          '<method name="CloseMenu"/>' +
          '<method name="GetMenuGeometry"><arg type="(iiii)" direction="out" name="rect"/></method>' +
          "</interface></node>",
        {
          Reload: (path) => {
            const [ok, bytes] = GLib.file_get_contents(path);
            if (!ok) throw new Error(`fixture not readable: ${path}`);
            this._loadFixtureData(JSON.parse(decodeBytes(bytes)));
          },
          OpenMenu: () => this.menu.open(false),
          CloseMenu: () => this.menu.close(false),
          GetMenuGeometry: () => {
            const actor = this.menu.actor;
            const [x, y] = actor.get_transformed_position();
            const [w, h] = actor.get_transformed_size();
            return [Math.round(x), Math.round(y), Math.round(w), Math.round(h)];
          },
        }
      );
      this._testIface.export(Gio.DBus.session, "/works/allegedly/AiQuotaTest");
      this._testBusOwnerId = Gio.bus_own_name(
        Gio.BusType.SESSION,
        "works.allegedly.AiQuotaTest",
        Gio.BusNameOwnerFlags.NONE,
        null,
        null,
        null
      );
    }

    _unexportTestInterface() {
      if (this._testBusOwnerId) {
        Gio.bus_unown_name(this._testBusOwnerId);
        this._testBusOwnerId = 0;
      }
      if (this._testIface) {
        this._testIface.unexport();
        this._testIface = null;
      }
    }

    _buildPanel() {
      const box = new St.BoxLayout({
        style_class: "quota-indicator",
        y_align: Clutter.ActorAlign.CENTER,
      });
      for (const p of this._providers) {
        p.icon = this._makeIcon(p.iconFile);
        p.paceLabel = new St.Label({ style_class: "quota-pace", y_align: Clutter.ActorAlign.CENTER });
        const provBox = new St.BoxLayout({ style_class: "quota-provider", y_align: Clutter.ActorAlign.CENTER });
        provBox.add_child(p.icon);
        provBox.add_child(p.paceLabel);
        box.add_child(provBox);
      }
      this.add_child(box);
    }

    _makeIcon(filename) {
      return new St.Icon({
        gicon: Gio.icon_new_for_string(`${this._iconsDir}/${filename}`),
        style_class: "quota-icon",
        y_align: Clutter.ActorAlign.CENTER,
      });
    }

    _buildPopup() {
      for (const p of this._providers) {
        p.header = new PopupMenu.PopupSeparatorMenuItem(p.label);
        p.shortRow = this._makeQuotaRow("5h");
        p.longRow = this._makeQuotaRow("7d");
        this.menu.addMenuItem(p.header);
        this.menu.addMenuItem(p.shortRow);
        this.menu.addMenuItem(p.longRow);
        p.header.label.add_style_class_name("quota-popup-header");
      }
    }

    _makeQuotaRow(label) {
      const item = new PopupMenu.PopupBaseMenuItem({ reactive: false, can_focus: false });
      item.add_style_class_name("quota-popup-bar-item");

      const content = new St.BoxLayout({
        style_class: "quota-popup-bar-content",
        vertical: true,
        x_expand: true,
      });
      item._summaryLabel = new St.Label({
        text: `${label}: no data`,
        style_class: "quota-popup-row",
        x_expand: true,
      });
      item._bars = new St.BoxLayout({
        style_class: "quota-bars",
        vertical: true,
        x_expand: true,
      });

      const timeBar = this._makeQuotaBar("quota-bar-time");
      const usageBar = this._makeQuotaBar("quota-unknown");
      item._timeFill = timeBar.fill;
      item._usageFill = usageBar.fill;

      item._bars.add_child(timeBar.track);
      item._bars.add_child(usageBar.track);
      content.add_child(item._summaryLabel);
      content.add_child(item._bars);
      item.add_child(content);
      return item;
    }

    _makeQuotaBar(fillClass) {
      const track = new St.BoxLayout({ style_class: "quota-bar-track", x_expand: true });

      const fill = new St.Widget({ style_class: `quota-bar-fill ${fillClass}` });
      fill._quotaFraction = null;
      fill._quotaTrack = track;
      fill.set_width(0);
      track.connect("notify::allocation", () => this._applyBarFill(fill));
      track.add_child(fill);
      return { track, fill };
    }

    _readClaudeAuth() {
      const path = `${GLib.get_home_dir()}/.claude/.credentials.json`;
      try {
        const [ok, bytes] = GLib.file_get_contents(path);
        if (!ok) return { error: `${path}: not readable` };
        const creds = JSON.parse(decodeBytes(bytes));
        const token = creds?.claudeAiOauth?.accessToken ?? null;
        if (!token) return { error: `${path}: missing claudeAiOauth.accessToken` };

        const refreshToken = creds?.claudeAiOauth?.refreshToken ?? null;
        const expiresAt = Number(creds?.claudeAiOauth?.expiresAt ?? NaN);
        if (Number.isFinite(expiresAt) && expiresAt - Date.now() <= TOKEN_EXPIRY_SKEW_SECONDS * 1000) {
          if (!refreshToken) {
            return { error: `access token expired ${formatUtcTimestamp(expiresAt)} and no refreshToken is stored` };
          }
          return { creds, expired: true, path, refreshToken, token };
        }

        return { creds, expired: false, path, refreshToken, token };
      } catch (error) {
        return { error: `${path}: ${errorMessage(error)}` };
      }
    }

    _readCodexAuth() {
      // File-based auth (~/.codex/auth.json) — Codex CLI writes this when
      // Secret Service is unavailable (common on headless/NixOS setups).
      try {
        const path = `${GLib.get_home_dir()}/.codex/auth.json`;
        const [ok, bytes] = GLib.file_get_contents(path);
        if (ok) {
          const auth = JSON.parse(decodeBytes(bytes));
          const token = auth?.tokens?.access_token ?? null;
          const accountId = auth?.tokens?.account_id ?? null;
          if (token) return { token, accountId };
        }
      } catch {
        // fall through to keyring
      }
      try {
        const results = Secret.password_search_sync(
          CODEX_KEYRING_SCHEMA,
          { service: "Codex Auth" },
          Secret.SearchFlags.UNLOCK | Secret.SearchFlags.LOAD_SECRETS,
          null
        );
        if (!results?.length) return null;
        const token = results[0].get_secret()?.get_text() ?? null;
        return token ? { token, accountId: null } : null;
      } catch {
        return null;
      }
    }

    _readZaiAuth() {
      const path = this._settings.get_string("zai-api-key-path");
      if (!path) return { error: "zai-api-key-path not configured" };
      try {
        const [ok, bytes] = GLib.file_get_contents(path);
        if (!ok) return { error: `${path}: not readable` };
        const key = decodeBytes(bytes).trim();
        if (!key) return { error: `${path}: empty` };
        return { token: key };
      } catch (error) {
        return { error: `${path}: ${errorMessage(error)}` };
      }
    }

    _providerById(id) {
      return this._providers.find((p) => p.id === id) ?? null;
    }

    _fetchAsync(url, headers, onSuccess, onError) {
      const msg = Soup.Message.new("GET", url);
      for (const [k, v] of Object.entries(headers)) msg.request_headers.append(k, v);
      this._sendAsync(msg, onSuccess, onError);
    }

    _postJsonAsync(url, body, onSuccess, onError) {
      const msg = Soup.Message.new("POST", url);
      const encoded = new TextEncoder().encode(JSON.stringify(body));
      msg.set_request_body_from_bytes("application/json", new GLib.Bytes(encoded));
      this._sendAsync(msg, onSuccess, onError);
    }

    _sendAsync(msg, onSuccess, onError) {
      this._httpSession.send_and_read_async(msg, GLib.PRIORITY_DEFAULT, null, (session, result) => {
        try {
          const bytes = session.send_and_read_finish(result);
          const text = decodeBytes(bytes);
          const status = messageStatus(msg);
          let json = null;
          try {
            json = JSON.parse(text);
          } catch (error) {
            if (isHttpErrorStatus(status)) {
              throw new HttpResponseError(status, null, text);
            }
            throw error;
          }
          if (isHttpErrorStatus(status) || json?.error) {
            throw new HttpResponseError(status, json, text);
          }
          onSuccess(json);
        } catch (error) {
          onError(error);
        } finally {
          this._renderPanel();
          this._renderPopup();
        }
      });
    }

    _saveClaudeAuth(path, creds) {
      const ok = GLib.file_set_contents(path, JSON.stringify(creds, null, 2));
      if (!ok) throw new Error(`${path}: write failed`);
      Gio.File.new_for_path(path).set_attribute_uint32("unix::mode", 0o600, Gio.FileQueryInfoFlags.NONE, null);
    }

    _refreshClaudeToken(auth) {
      this._postJsonAsync(
        CLAUDE_TOKEN_URL,
        {
          grant_type: "refresh_token",
          refresh_token: auth.refreshToken,
          client_id: CLAUDE_OAUTH_CLIENT_ID,
          scope: CLAUDE_OAUTH_SCOPES.join(" "),
        },
        (data) => {
          const accessToken = data.access_token ?? null;
          const expiresIn = Number(data.expires_in ?? NaN);
          if (!accessToken || !Number.isFinite(expiresIn)) {
            throw new Error(`unexpected token refresh response (${objectSummary(data)})`);
          }

          auth.creds.claudeAiOauth = {
            ...(auth.creds.claudeAiOauth ?? {}),
            accessToken,
            refreshToken: data.refresh_token ?? auth.refreshToken,
            expiresAt: Date.now() + expiresIn * 1000,
            scopes: parseScopes(data.scope, auth.creds.claudeAiOauth?.scopes),
          };
          this._saveClaudeAuth(auth.path, auth.creds);
          auth.refreshToken = auth.creds.claudeAiOauth.refreshToken;
          this._fetchClaude(accessToken, auth, false);
        },
        (error) => {
          const p = this._providerById("claude");
          if (p) p.state.error = `token refresh failed: ${errorMessage(error)}`;
        }
      );
    }

    _fetchClaude(token, auth, allowRefresh = true) {
      const p = this._providerById("claude");
      this._fetchAsync(
        CLAUDE_USAGE_URL,
        {
          Authorization: `Bearer ${token}`,
          "anthropic-beta": "oauth-2025-04-20",
        },
        (data) => {
          if (data.five_hour == null && data.seven_day == null) {
            throw new Error(`unexpected response (${objectSummary(data)})`);
          }
          p.state.short = windowFromClaude(data.five_hour, "5h", CLAUDE_SHORT_W);
          p.state.long = windowFromClaude(data.seven_day, "7d", CLAUDE_LONG_W);
          p.state.extraUsage = data.extra_usage ?? null;
          p.state.lastFetch = Date.now();
          p.state.error = null;
        },
        (error) => {
          if (allowRefresh && auth?.refreshToken && error?.status === 401) {
            this._refreshClaudeToken(auth);
          } else if (p) {
            p.state.error = errorMessage(error);
          }
        }
      );
    }

    _fetchCodex({ token, accountId }) {
      const p = this._providerById("codex");
      const headers = {
        Authorization: `Bearer ${token}`,
        "User-Agent": "codex_cli_rs/0.125.0 (Linux; x86_64) gnome-shell-extension",
      };
      if (accountId) headers["ChatGPT-Account-Id"] = accountId;
      this._fetchAsync(
        CODEX_USAGE_URL,
        headers,
        (data) => {
          if (data.rate_limit?.primary_window == null && data.rate_limit?.secondary_window == null) {
            throw new Error(`unexpected response (${objectSummary(data)})`);
          }
          p.state.short = windowFromCodex(data.rate_limit?.primary_window, "5h");
          p.state.long = windowFromCodex(data.rate_limit?.secondary_window, "7d");
          p.state.lastFetch = Date.now();
          p.state.error = null;
        },
        (error) => {
          if (p) p.state.error = errorMessage(error);
        }
      );
    }

    _fetchZai(token) {
      const p = this._providerById("zai");
      this._fetchAsync(
        ZAI_QUOTA_URL,
        { Authorization: `Bearer ${token}` },
        (data) => {
          if (!Array.isArray(data?.data?.limits)) {
            throw new Error(`unexpected response (${objectSummary(data)})`);
          }
          const limits = data.data.limits;
          const shortLimit = limits.find((l) => l.type === "TOKENS_LIMIT" && l.unit === 3);
          const longLimit = limits.find((l) => l.type === "TOKENS_LIMIT" && l.unit === 6);
          p.state.short = windowFromZai(shortLimit, ZAI_SHORT_W);
          p.state.long = windowFromZai(longLimit, ZAI_LONG_W);
          p.state.lastFetch = Date.now();
          p.state.error = null;
        },
        (error) => {
          if (p) p.state.error = errorMessage(error);
        }
      );
    }

    _setTint(icon, paceLabel, tint) {
      for (const cls of TINT_CLASSES) {
        icon.remove_style_class_name(cls);
        paceLabel.remove_style_class_name(cls);
      }
      icon.add_style_class_name(`quota-${tint}`);
      paceLabel.add_style_class_name(`quota-${tint}`);
    }

    _renderPanel() {
      for (const p of this._providers) this._renderProvider(p.state, p.icon, p.paceLabel);
    }

    _renderProvider(state, icon, paceLabel) {
      if (state.error) {
        this._setTint(icon, paceLabel, "error");
        paceLabel.set_text("!");
        return;
      }
      if (state.short == null && state.long == null) {
        this._setTint(icon, paceLabel, "unknown");
        paceLabel.set_text("");
        return;
      }
      const stale = isStaleFetch(state.lastFetch);
      const shortState = withLiveReset(state.short);
      const longState = withLiveReset(state.long);
      const shortPace = shortState ? computePace(shortState) : null;
      const longPace = longState ? computePace(longState) : null;
      const shortTint = shortState
        ? tintFor({ pace: shortPace, usedPercent: shortState.usedPercent, isShort: true })
        : "unknown";
      const longTint = longState
        ? tintFor({ pace: longPace, usedPercent: longState.usedPercent, isShort: false })
        : "unknown";
      const extraActive = state.extraUsage?.is_enabled === true;
      const tint = extraActive ? "hot" : (stale ? "stale" : bindingTint(shortTint, longTint));
      this._setTint(icon, paceLabel, tint);
      const paceText = formatPace(longPace) ?? "";
      const extraActive = state.extraUsage?.is_enabled === true;
      if (extraActive) {
        paceLabel.set_text(`${formatCompactDollars(state.extraUsage.used_credits)} ⚡`);
      } else {
        paceLabel.set_text(paceText);
      }
    }

    _renderPopup() {
      for (const p of this._providers) {
        const inExtraRegime = p.state.extraUsage?.is_enabled === true;
        this._renderProviderHeader(p.header, p.label, p.state);
        if (inExtraRegime) {
          p.shortRow.visible = false;
          p.longRow.visible = true;
          const live = withLiveReset(p.state.long);
          const reset = live ? `↻${formatDuration(live.resetSeconds)}` : "";
          p.longRow._summaryLabel.set_text(`7d reset: ${reset}`);
          this._setBarFill(p.longRow._timeFill, null);
          this._setBarFill(p.longRow._usageFill, null);
          this._setBarTint(p.longRow._usageFill, "unknown");
        } else {
          p.shortRow.visible = true;
          p.longRow.visible = true;
          this._renderPopupRow(p.shortRow, "5h", p.state.short);
          this._renderPopupRow(p.longRow, "7d", p.state.long);
        }
      }
    }

    _renderProviderHeader(item, title, state) {
      item.label.remove_style_class_name("quota-popup-header-error");
      item.label.remove_style_class_name("quota-popup-header-stale");

      const parts = [title];
      if (state.error) {
        const prefix = state.short == null && state.long == null ? "error" : "last refresh failed";
        parts.push(`${prefix}: ${state.error}`);
        item.label.add_style_class_name("quota-popup-header-error");
      } else if (isStaleFetch(state.lastFetch)) {
        item.label.add_style_class_name("quota-popup-header-stale");
      }
      const extraStr = formatExtraUsage(state.extraUsage);
      if (extraStr) parts.push(extraStr);
      parts.push(formatFreshness(state.lastFetch));
      item.label.set_text(parts.join(" · "));
    }

    _renderPopupRow(item, label, state) {
      if (state == null) {
        item._summaryLabel.set_text(`${label}: no data`);
        this._setBarFill(item._timeFill, null);
        this._setBarFill(item._usageFill, null);
        this._setBarTint(item._usageFill, "unknown");
        return;
      }
      const liveState = withLiveReset(state);
      const pace = computePace(liveState);
      const used = liveState.usedPercent != null ? `${Math.round(liveState.usedPercent)}%` : "?";
      const reset = `↻${formatDuration(liveState.resetSeconds)}`;
      const paceStr = formatPace(pace);
      const forecast = formatForecast(pace, liveState.resetSeconds);
      const parts = [used, reset];
      if (paceStr) parts.push(`Δ${paceStr}`);
      if (forecast) parts.push(forecast);
      item._summaryLabel.set_text(`${label}: ${parts.join("  ")}`);

      this._setBarFill(item._timeFill, elapsedFraction(liveState));
      this._setBarFill(item._usageFill, liveState.usedPercent == null ? null : liveState.usedPercent / 100);
      this._setBarTint(item._usageFill, tintFor({ pace, usedPercent: liveState.usedPercent, isShort: label === "5h" }));
    }

    _setBarFill(fill, fraction) {
      fill._quotaFraction = clamp01(fraction);
      this._applyBarFill(fill);
    }

    _applyBarFill(fill) {
      const fraction = fill._quotaFraction;
      if (fraction == null) {
        fill.set_width(0);
        return;
      }
      const box = fill._quotaTrack.get_allocation_box();
      const trackWidth = box.x2 - box.x1;
      if (!(trackWidth > 0)) return;
      fill.set_width(Math.round(trackWidth * fraction));
    }

    _setBarTint(fill, tint) {
      for (const cls of TINT_CLASSES) fill.remove_style_class_name(cls);
      fill.add_style_class_name(`quota-${tint}`);
    }

    _startPopupTick() {
      if (this._popupTickId) return;
      this._popupTickId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 1, () => {
        if (!this.menu.isOpen) {
          this._popupTickId = null;
          return GLib.SOURCE_REMOVE;
        }
        this._renderPopup();
        return GLib.SOURCE_CONTINUE;
      });
    }

    _stopPopupTick() {
      if (!this._popupTickId) return;
      GLib.source_remove(this._popupTickId);
      this._popupTickId = null;
    }

    _refresh() {
      const claudeP = this._providerById("claude");
      if (claudeP) {
        const claudeAuth = this._readClaudeAuth();
        if (claudeAuth.token) {
          if (claudeAuth.expired) {
            this._refreshClaudeToken(claudeAuth);
          } else {
            this._fetchClaude(claudeAuth.token, claudeAuth);
          }
        } else {
          claudeP.state.error = claudeAuth.error;
        }
      }

      const codexP = this._providerById("codex");
      if (codexP) {
        const codexAuth = this._readCodexAuth();
        if (codexAuth) {
          this._fetchCodex(codexAuth);
        }
      }

      const zaiP = this._providerById("zai");
      if (zaiP) {
        const zaiAuth = this._readZaiAuth();
        if (zaiAuth.token) {
          this._fetchZai(zaiAuth.token);
        } else {
          zaiP.state.error = zaiAuth.error;
        }
      }

      this._renderPanel();
      this._renderPopup();
    }

    destroy() {
      this._unexportTestInterface();
      this._stopPopupTick();
      if (this._menuOpenId) {
        this.menu.disconnect(this._menuOpenId);
        this._menuOpenId = null;
      }
      if (this._timerId) {
        GLib.source_remove(this._timerId);
        this._timerId = null;
      }
      this._httpSession.abort();
      super.destroy();
    }
  }
);

export default class QuotaExtension extends Extension {
  enable() {
    this._indicator = new QuotaIndicator(this);
    Main.panel.addToStatusArea(this.uuid, this._indicator);
  }

  disable() {
    this._indicator?.destroy();
    this._indicator = null;
  }
}
