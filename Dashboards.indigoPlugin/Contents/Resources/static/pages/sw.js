// Filename:    sw.js
// Description: Minimal service worker for the Dashboards alert rules.
//              Exists so notifications can be raised via
//              registration.showNotification() (required on Android Chrome)
//              and so tapping a notification brings the dashboard forward.
//              No caching, no push subscription — alerts are raised by an
//              open page itself (dashboards-alerts.js, loaded by the hub, the
//              room pages, Energy and Alerts since 3.46.0; see alerts.html
//              for the honest small print). Code unchanged since 1.0.
// Author:      CliveS & Claude Fable 5
// Date:        11-06-2026
// Version:     1.0

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

self.addEventListener("notificationclick", event => {
    event.notification.close();
    event.waitUntil((async () => {
        const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
        for (const c of all) {
            if (c.url.includes("/public/dashboards/") && "focus" in c) return c.focus();
        }
        return self.clients.openWindow("index.html");
    })());
});
