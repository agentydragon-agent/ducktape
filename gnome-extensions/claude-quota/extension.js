import GLib from "gi://GLib";
import GObject from "gi://GObject";
import St from "gi://St";
import Clutter from "gi://Clutter";
import Soup from "gi://Soup";
import Secret from "gi://Secret";

import { Extension } from "resource:///org/gnome/shell/extensions/extension.js";
import * as Main from "resource:///org/gnome/shell/ui/main.js";
import * as PanelMenu from "resource:///org/gnome/shell/ui/panelMenu.js";
import * as PopupMenu from "resource:///org/gnome/shell/ui/popupMenu.js";

const CLAUDE_USAGE_URL = "https://api.anthropic.com/api/oauth/usage";
const CODEX_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage";
const POLL_INTERVAL_SECONDS = 120;

// keyring Rust crate (used by Codex CLI) stores entries under the generic schema
// with attributes {service, username}. We search by service only.
const CODEX_KEYRING_SCHEMA = new Secret.Schema("org.freedesktop.Secret.Generic", Secret.SchemaFlags.DONT_MATCH_NAME, {
  service: Secret.SchemaAttributeType.STRING,
  username: Secret.SchemaAttributeType.STRING,
});

function formatDuration(seconds) {
  if (seconds == null || seconds < 0) return "?";
  const s = Math.round(seconds);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d${h}h`;
  if (h > 0) return `${h}h${m}m`;
  return `${m}m`;
}

function secondsUntil(isoTimestamp) {
  if (!isoTimestamp) return null;
  return (new Date(isoTimestamp) - Date.now()) / 1000;
}

const QuotaIndicator = GObject.registerClass(
  class QuotaIndicator extends PanelMenu.Button {
    _init(extension) {
      super._init(0.0, "AI Quota Tracker", false);

      this._label = new St.Label({
        text: "quota…",
        y_align: Clutter.ActorAlign.CENTER,
      });
      this.add_child(this._label);

      this._claudeItem = new PopupMenu.PopupMenuItem("Claude: …", {
        reactive: false,
      });
      this._codexItem = new PopupMenu.PopupMenuItem("Codex: …", {
        reactive: false,
      });
      this.menu.addMenuItem(this._claudeItem);
      this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
      this.menu.addMenuItem(this._codexItem);

      this._httpSession = new Soup.Session();
      this._claudeState = null;
      this._codexState = null;

      this._refresh();
      this._timerId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, POLL_INTERVAL_SECONDS, () => {
        this._refresh();
        return GLib.SOURCE_CONTINUE;
      });
    }

    _readClaudeToken() {
      try {
        const path = `${GLib.get_home_dir()}/.claude/.credentials.json`;
        const [ok, bytes] = GLib.file_get_contents(path);
        if (!ok) return null;
        const creds = JSON.parse(new TextDecoder().decode(bytes));
        return creds?.claudeAiOauth?.accessToken ?? null;
      } catch {
        return null;
      }
    }

    _readCodexAuth() {
      // File-based auth (~/.codex/auth.json) — Codex CLI writes this when
      // Secret Service is unavailable (common on headless/NixOS setups).
      try {
        const path = `${GLib.get_home_dir()}/.codex/auth.json`;
        const [ok, bytes] = GLib.file_get_contents(path);
        if (ok) {
          const auth = JSON.parse(new TextDecoder().decode(bytes));
          const token = auth?.tokens?.access_token ?? null;
          const accountId = auth?.tokens?.account_id ?? null;
          if (token) return { token, accountId };
        }
      } catch {
        // fall through to keyring
      }
      // Fall back to Secret Service keyring (keyring crate, service="Codex Auth")
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

    _fetchAsync(url, headers, onSuccess) {
      const msg = Soup.Message.new("GET", url);
      for (const [k, v] of Object.entries(headers)) msg.request_headers.append(k, v);
      this._httpSession.send_and_read_async(msg, GLib.PRIORITY_DEFAULT, null, (session, result) => {
        try {
          const bytes = session.send_and_read_finish(result);
          const json = JSON.parse(new TextDecoder().decode(bytes.get_data()));
          onSuccess(json);
        } catch {
          // leave state unchanged, show stale data until next poll
        }
        this._updateLabel();
      });
    }

    _fetchClaude(token) {
      this._fetchAsync(
        CLAUDE_USAGE_URL,
        {
          Authorization: `Bearer ${token}`,
          "anthropic-beta": "oauth-2025-04-20",
        },
        (data) => {
          const fh = data.five_hour;
          const sd = data.seven_day;
          this._claudeState = {
            fhPct: fh ? Math.round(fh.utilization) : null,
            fhReset: fh?.resets_at ? secondsUntil(fh.resets_at) : null,
            sdPct: sd ? Math.round(sd.utilization) : null,
            sdReset: sd?.resets_at ? secondsUntil(sd.resets_at) : null,
          };
          const fhStr =
            this._claudeState.fhPct != null
              ? `${this._claudeState.fhPct}% ↻${formatDuration(this._claudeState.fhReset)}`
              : "?";
          const sdStr =
            this._claudeState.sdPct != null
              ? `${this._claudeState.sdPct}% ↻${formatDuration(this._claudeState.sdReset)}`
              : "?";
          this._claudeItem.label.set_text(`Claude  5h: ${fhStr}  7d: ${sdStr}`);
        }
      );
    }

    _fetchCodex({ token, accountId }) {
      const headers = {
        Authorization: `Bearer ${token}`,
        "User-Agent": "codex_cli_rs/0.125.0 (Linux; x86_64) gnome-shell-extension",
      };
      if (accountId) headers["ChatGPT-Account-Id"] = accountId;
      this._fetchAsync(CODEX_USAGE_URL, headers, (data) => {
        const pw = data.rate_limit?.primary_window;
        const sw = data.rate_limit?.secondary_window;
        this._codexState = {
          pwPct: pw?.used_percent ?? null,
          pwReset: pw?.reset_after_seconds ?? null,
          swPct: sw?.used_percent ?? null,
          swReset: sw?.reset_after_seconds ?? null,
        };
        const pwStr =
          this._codexState.pwPct != null
            ? `${this._codexState.pwPct}% ↻${formatDuration(this._codexState.pwReset)}`
            : "?";
        const swStr =
          this._codexState.swPct != null
            ? `${this._codexState.swPct}% ↻${formatDuration(this._codexState.swReset)}`
            : "?";
        this._codexItem.label.set_text(`Codex  primary: ${pwStr}  secondary: ${swStr}`);
      });
    }

    _updateLabel() {
      const c = this._claudeState;
      const o = this._codexState;
      const cStr = c ? `C 5h:${c.fhPct ?? "?"}% 7d:${c.sdPct ?? "?"}%` : "C ?";
      const oStr = o ? `O ${o.pwPct ?? "?"}%↻${formatDuration(o.pwReset)}` : "O ?";
      this._label.set_text(`${cStr} | ${oStr}`);
    }

    _refresh() {
      const claudeToken = this._readClaudeToken();
      if (claudeToken) {
        this._fetchClaude(claudeToken);
      } else {
        this._claudeItem.label.set_text("Claude: no credentials");
      }

      const codexAuth = this._readCodexAuth();
      if (codexAuth) {
        this._fetchCodex(codexAuth);
      } else {
        this._codexItem.label.set_text("Codex: no credentials");
      }

      this._updateLabel();
    }

    destroy() {
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
