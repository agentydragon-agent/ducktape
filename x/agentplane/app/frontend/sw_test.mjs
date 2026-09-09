import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

const listeners = new Map();
const requests = [];
const windows = [];
const notices = [];
const self = {
  addEventListener: (kind, handler) => listeners.set(kind, handler),
  registration: { showNotification: async (title, options) => notices.push({ title, ...options }) },
  clients: { openWindow: async (url) => windows.push(url), claim: async () => {} },
  skipWaiting: async () => {},
};
runInNewContext(readFileSync(process.env.SW_SOURCE, "utf8"), {
  self,
  fetch: async (url, options) => {
    requests.push({ url, options });
    return { ok: true };
  },
  crypto: { randomUUID: () => "test-intent" },
});
const message = { kind: "show", action_id: "request", action_group: "group", action_name: "echo", version: 1 };
async function click(action) {
  let work;
  listeners.get("notificationclick")({
    action,
    notification: { data: message, close() {} },
    waitUntil: (promise) => {
      work = promise;
    },
  });
  await work;
}
await click("");
assert.equal(requests.length, 0, "body tap must never decide");
assert.deepEqual(windows, ["/#/actions"]);
await click("approve");
assert.equal(JSON.parse(requests[0].options.body).verdict, "allow");
assert.equal(JSON.parse(requests[0].options.body).expected_version, 1);
assert.equal(requests[0].options.credentials, "include");
await click("deny");
assert.equal(JSON.parse(requests[1].options.body).verdict, "deny");
let work;
listeners.get("push")({
  data: { json: () => ({ kind: "retract", action_id: "request", outcome: "denied" }) },
  waitUntil: (promise) => {
    work = promise;
  },
});
await work;
assert.equal(notices[0].tag, "request");
assert.equal(notices[0].actions, undefined, "resolved notice offers no decisions");
