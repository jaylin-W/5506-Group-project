self.addEventListener("install", (event) => {
    event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
    event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
    const fallback = {
        title: "\u76ee\u524d\u9762\u90e8\u8bc6\u522b\u5df2\u5931\u8d253\u6b21",
        body: "\u8bf7\u8fdb\u5165\u7f51\u7ad9\uff0c\u8f93\u5165\u89e3\u9501\u5bc6\u7801\u3002",
        url: "/unlock",
        interaction: true,
    };

    let data = fallback;
    if (event.data) {
        try {
            data = event.data.json();
        } catch (error) {
            data = { ...fallback, body: event.data.text() };
        }
    }

    const options = {
        body: data.body || fallback.body,
        tag: "face-unlock-required",
        requireInteraction: data.interaction !== false,
        vibrate: [100, 50, 100],
        data: { url: data.url || fallback.url },
        actions: [
            { action: "unlock", title: "Open" },
            { action: "close", title: "Close" },
        ],
    };

    event.waitUntil(self.registration.showNotification(data.title || fallback.title, options));
});

self.addEventListener("notificationclick", (event) => {
    event.notification.close();

    if (event.action === "close") {
        return;
    }

    const targetUrl = event.notification.data && event.notification.data.url
        ? event.notification.data.url
        : "/unlock";

    event.waitUntil(
        self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
            for (const client of clientList) {
                if ("focus" in client) {
                    client.navigate(targetUrl);
                    return client.focus();
                }
            }

            if (self.clients.openWindow) {
                return self.clients.openWindow(targetUrl);
            }

            return null;
        })
    );
});
