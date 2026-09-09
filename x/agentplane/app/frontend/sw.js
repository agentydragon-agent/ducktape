self.addEventListener("push", (event) => {
  if (!event.data) return;
  const message = event.data.json();
  if (message.kind === "retract") {
    event.waitUntil(
      self.registration.showNotification(message.outcome, {
        tag: message.action_id,
        silent: true,
        requireInteraction: false,
        data: message,
      })
    );
    return;
  }
  event.waitUntil(
    self.registration.showNotification(`${message.action_group} / ${message.action_name}`, {
      body: "Action requires approval",
      tag: message.action_id,
      requireInteraction: true,
      actions: [
        { action: "approve", title: "Approve" },
        { action: "deny", title: "Deny" },
        { action: "details", title: "Details" },
      ],
      data: message,
    })
  );
});
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const message = event.notification.data;
  if (!message || message.kind !== "show") return;
  if (event.action !== "approve" && event.action !== "deny") {
    event.waitUntil(self.clients.openWindow("/#/actions"));
    return;
  }
  event.waitUntil(
    fetch(`/push/decision/${encodeURIComponent(message.action_id)}`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        verdict: event.action === "approve" ? "allow" : "deny",
        expected_version: message.version,
        idempotency_key: crypto.randomUUID(),
        decision_note: null,
      }),
    }).then((response) => {
      if (!response.ok) return self.clients.openWindow("/#/actions");
    })
  );
});

self.addEventListener("install", (event) => event.waitUntil(self.skipWaiting()));
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
