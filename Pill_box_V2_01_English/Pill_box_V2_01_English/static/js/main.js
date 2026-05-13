document.addEventListener("DOMContentLoaded", function () {
    const promoCarousel = document.querySelector("#promoCarousel");
    if (promoCarousel && window.bootstrap) {
        new bootstrap.Carousel(promoCarousel, {
            interval: 3200,
            ride: "carousel",
            pause: false,
            touch: true,
            wrap: true,
        });
    }

    const profileSummary = document.querySelector("[data-profile-summary]");
    const profileEditor = document.querySelector("[data-profile-editor]");
    const profileEditToggle = document.querySelector("[data-profile-edit-toggle]");
    const profileEditCancel = document.querySelector("[data-profile-edit-cancel]");

    const setProfileEditMode = (isEditing) => {
        if (!profileSummary || !profileEditor || !profileEditToggle) {
            return;
        }

        profileSummary.classList.toggle("d-none", isEditing);
        profileEditor.classList.toggle("d-none", !isEditing);
        profileEditToggle.setAttribute("aria-pressed", String(isEditing));
        profileEditToggle.title = isEditing ? "Close edit mode" : "Edit account information";
    };

    if (profileEditToggle) {
        profileEditToggle.addEventListener("click", () => {
            const isEditing = profileEditor && !profileEditor.classList.contains("d-none");
            setProfileEditMode(!isEditing);
        });
    }

    if (profileEditCancel) {
        profileEditCancel.addEventListener("click", () => setProfileEditMode(false));
    }

    document.querySelectorAll("[data-password-reveal]").forEach((button) => {
        button.addEventListener("click", () => {
            const passwordLine = button.closest(".password-line");
            const secret = passwordLine ? passwordLine.querySelector("[data-password-mask]") : null;
            if (!secret) {
                return;
            }

            const isVisible = secret.dataset.visible === "true";
            secret.textContent = isVisible ? secret.dataset.passwordMask : secret.dataset.passwordMessage;
            secret.dataset.visible = String(!isVisible);
            button.title = isVisible ? "Show password status" : "Hide password status";
            button.setAttribute("aria-label", button.title);
        });
    });

    const faceStatusUrl = document.body.dataset.faceStatusUrl;
    const unlockUrl = document.body.dataset.faceUnlockUrl || "/unlock";
    const faceAlert = document.querySelector("[data-face-alert]");
    const faceAlertMessage = document.querySelector("[data-face-alert-message]");
    const notificationButtons = document.querySelectorAll("[data-enable-face-notifications]");
    const testNotificationButtons = document.querySelectorAll("[data-send-test-notification]");
    const notificationStatuses = document.querySelectorAll("[data-face-notification-status]");
    let serviceWorkerRegistration = null;

    const setNotificationStatus = (message) => {
        notificationStatuses.forEach((status) => {
            status.textContent = message;
        });
    };

    const base64UrlToUint8Array = (base64UrlData) => {
        const padding = "=".repeat((4 - base64UrlData.length % 4) % 4);
        const base64 = (base64UrlData + padding).replace(/-/g, "+").replace(/_/g, "/");
        const rawData = atob(base64);
        const buffer = new Uint8Array(rawData.length);
        for (let i = 0; i < rawData.length; i += 1) {
            buffer[i] = rawData.charCodeAt(i);
        }
        return buffer;
    };

    const registerServiceWorker = async () => {
        if (!window.isSecureContext) {
            setNotificationStatus("Phone notifications need HTTPS or localhost.");
            return null;
        }

        if (!("serviceWorker" in navigator)) {
            setNotificationStatus("Service Worker is not supported here.");
            return null;
        }

        try {
            serviceWorkerRegistration = await navigator.serviceWorker.register("/service-worker.js");
            return serviceWorkerRegistration;
        } catch (error) {
            console.warn("Service worker registration failed", error);
            setNotificationStatus("Service Worker registration failed.");
            return null;
        }
    };

    const updateNotificationButtons = () => {
        notificationButtons.forEach((button) => {
            button.classList.remove("d-none");
        });
        testNotificationButtons.forEach((button) => {
            button.classList.remove("d-none");
        });

        if (!window.isSecureContext) {
            setNotificationStatus("HTTPS is required for background phone alerts.");
            return;
        }

        if (!("Notification" in window)) {
            setNotificationStatus("Notifications are not supported on this browser.");
            return;
        }

        notificationButtons.forEach((button) => {
            button.classList.toggle("d-none", Notification.permission === "granted");
        });
    };

    const requestNotificationPermission = async () => {
        if (!window.isSecureContext) {
            setNotificationStatus("Phone notifications need HTTPS. The page alert still works.");
            return "denied";
        }

        if (!("Notification" in window)) {
            setNotificationStatus("Notifications are not supported on this browser.");
            return "denied";
        }

        if (Notification.permission === "default") {
            await Notification.requestPermission();
        }
        updateNotificationButtons();
        setNotificationStatus(`Notification permission: ${Notification.permission}`);
        return Notification.permission;
    };

    const subscribeToPushMessages = async () => {
        const permission = await requestNotificationPermission();
        if (permission !== "granted") {
            return null;
        }

        const registration = serviceWorkerRegistration || (await registerServiceWorker());
        if (!registration || !registration.pushManager) {
            setNotificationStatus("Push Manager is not supported here.");
            return null;
        }

        const keyResponse = await fetch("/api/push/public-key", {
            credentials: "same-origin",
            headers: { Accept: "application/json" },
        });
        const keyData = await keyResponse.json();
        if (!keyData.configured || !keyData.publicKey) {
            setNotificationStatus("Server Web Push is not configured yet.");
            return null;
        }

        let subscription = await registration.pushManager.getSubscription();
        if (!subscription) {
            subscription = await registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: base64UrlToUint8Array(keyData.publicKey),
            });
        }

        await fetch("/api/push/subscribe", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(subscription),
        });

        setNotificationStatus("Push subscription saved. Server can now notify this device.");
        return subscription;
    };

    const showFaceFailureNotification = async (status, force = false) => {
        if (!window.isSecureContext) {
            setNotificationStatus("Phone notifications need HTTPS or an installed PWA.");
            return;
        }

        if (!("Notification" in window)) {
            setNotificationStatus("Notifications are not supported on this browser.");
            return;
        }

        if (Notification.permission !== "granted") {
            const permission = await requestNotificationPermission();
            if (permission !== "granted") {
                return;
            }
        }

        const failureKey = status.last_face_failure_at || String(status.failed_attempts);
        const storageKey = `faceFailureNotification:${failureKey}`;
        if (!force && sessionStorage.getItem(storageKey)) {
            return;
        }

        const options = {
            body: status.notification_body,
            tag: "face-unlock-required",
            requireInteraction: true,
            vibrate: [100, 50, 100],
            data: { url: status.unlock_url || unlockUrl },
            actions: [
                { action: "unlock", title: "Open" },
                { action: "close", title: "Close" },
            ],
        };

        const registration = serviceWorkerRegistration || (await registerServiceWorker());
        if (registration && registration.showNotification) {
            await registration.showNotification(status.notification_title, options);
        } else {
            const notification = new Notification(status.notification_title, options);
            notification.onclick = () => {
                window.focus();
                window.location.href = status.unlock_url || unlockUrl;
            };
        }

        sessionStorage.setItem(storageKey, "shown");
        setNotificationStatus("Test notification sent.");
    };

    const renderFaceAlert = (status) => {
        if (!faceAlert) {
            return;
        }

        faceAlert.classList.toggle("d-none", !status.unlock_required);
        if (faceAlertMessage) {
            faceAlertMessage.textContent = status.notification_title + ", " + status.notification_body;
        }
    };

    const checkFaceUnlockStatus = async () => {
        if (!faceStatusUrl) {
            return;
        }

        try {
            const response = await fetch(faceStatusUrl, {
                headers: { Accept: "application/json" },
                credentials: "same-origin",
            });

            if (!response.ok) {
                return;
            }

            const status = await response.json();
            renderFaceAlert(status);
            if (status.unlock_required) {
                await showFaceFailureNotification(status);
            }
        } catch (error) {
            console.warn("Face unlock status check failed", error);
        }
    };

    notificationButtons.forEach((button) => {
        button.addEventListener("click", subscribeToPushMessages);
    });

    testNotificationButtons.forEach((button) => {
        button.addEventListener("click", async () => {
            const subscription = await subscribeToPushMessages();
            if (!subscription) {
                return;
            }

            const response = await fetch("/api/push/test", {
                method: "POST",
                credentials: "same-origin",
                headers: { "Content-Type": "application/json" },
            });
            const result = await response.json();
            if (result.configured && result.sent > 0) {
                setNotificationStatus("Server push sent. You can close the app and trigger again.");
                return;
            }

            setNotificationStatus("Server push was not sent. Showing foreground notification instead.");
            await showFaceFailureNotification({
                    notification_title: "目前面部识别已失败3次",
                    notification_body: "请进入网站，输入解锁密码。",
                    unlock_url: unlockUrl,
                    failed_attempts: 3,
                    last_face_failure_at: String(Date.now()),
                },
                true
            );
        });
    });

    registerServiceWorker().then(() => {
        updateNotificationButtons();
        checkFaceUnlockStatus();
        if (faceStatusUrl) {
            window.setInterval(checkFaceUnlockStatus, 15000);
        }
    });

    console.log("Pill box V2.01 page loaded");
});
