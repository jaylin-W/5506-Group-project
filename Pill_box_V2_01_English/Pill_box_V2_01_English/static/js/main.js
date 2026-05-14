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
    const faceUnlockModalElement = document.querySelector("[data-face-unlock-modal]");
    const faceUnlockModalMessage = document.querySelector("[data-face-unlock-modal-message]");
    const notificationButtons = document.querySelectorAll("[data-enable-face-notifications]");
    const testNotificationButtons = document.querySelectorAll("[data-send-test-notification]");
    const notificationStatuses = document.querySelectorAll("[data-face-notification-status]");
    let serviceWorkerRegistration = null;
    let faceUnlockModal = null;
    let faceUnlockStatusReady = false;
    let lastFaceFailureKey = null;
    let faceUnlockEventVisible = false;

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

        if (Notification.permission === "granted") {
            setNotificationStatus("Notification permission granted. Tap Enable Phone Alerts to save or refresh this device.");
        }
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

        const saveResponse = await fetch("/api/push/subscribe", {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(subscription),
        });

        if (!saveResponse.ok) {
            setNotificationStatus("Push subscription could not be saved.");
            return null;
        }

        const saveData = await saveResponse.json();
        const deviceCount = saveData.subscriptions || 1;
        setNotificationStatus(`Push subscription saved. Subscribed devices: ${deviceCount}.`);
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
            icon: "/static/images/promo_multivitamin.png",
            badge: "/static/images/promo_multivitamin.png",
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

    const getFaceFailureKey = (status) => (
        status.last_face_failure_at || `${status.failed_attempts || 0}:${status.unlock_required ? "locked" : "clear"}`
    );

    const shouldRevealFaceUnlock = (status) => {
        const currentKey = getFaceFailureKey(status);

        if (!faceUnlockStatusReady) {
            lastFaceFailureKey = currentKey;
            faceUnlockStatusReady = true;
            return false;
        }

        if (!status.unlock_required) {
            lastFaceFailureKey = currentKey;
            faceUnlockEventVisible = false;
            return false;
        }

        const isNewDeviceFailure = currentKey !== lastFaceFailureKey;
        lastFaceFailureKey = currentKey;
        return isNewDeviceFailure;
    };

    const showFaceUnlockModal = (status) => {
        if (!faceUnlockModalElement || !window.bootstrap) {
            return;
        }

        const failureKey = getFaceFailureKey(status);
        const storageKey = `faceUnlockModal:${failureKey}`;
        if (sessionStorage.getItem(storageKey)) {
            return;
        }

        faceUnlockModal = faceUnlockModal || new bootstrap.Modal(faceUnlockModalElement);
        faceUnlockModal.show();
        sessionStorage.setItem(storageKey, "shown");
    };

    const renderFaceAlert = (status) => {
        if (!faceAlert) {
            return;
        }

        faceAlert.classList.toggle("d-none", !(status.unlock_required && faceUnlockEventVisible));
        if (faceAlertMessage) {
            faceAlertMessage.textContent = status.notification_title + ", " + status.notification_body;
        }
        if (faceUnlockModalMessage) {
            faceUnlockModalMessage.textContent = status.notification_title + ", " + status.notification_body;
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
            const shouldReveal = shouldRevealFaceUnlock(status);
            if (shouldReveal) {
                faceUnlockEventVisible = true;
                showFaceUnlockModal(status);
            }
            renderFaceAlert(status);
            if (shouldReveal) {
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
            const response = await fetch("/api/push/test", {
                method: "POST",
                credentials: "same-origin",
                headers: { "Content-Type": "application/json" },
            });

            if (!response.ok) {
                setNotificationStatus("Please log in before sending a test notification.");
                return;
            }

            const result = await response.json();
            if (result.configured && result.sent > 0) {
                setNotificationStatus(`Server push sent to ${result.sent} subscribed device(s).`);
                return;
            }

            if (result.configured && result.subscriptions === 0) {
                setNotificationStatus("No phone subscription yet. Open the HTTPS link on your phone and tap Enable Phone Alerts first.");
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

    const enrollmentRoot = document.querySelector("[data-face-enrollment-status-url]");
    if (enrollmentRoot) {
        const statusUrl = enrollmentRoot.dataset.faceEnrollmentStatusUrl;
        const statusBadge = document.querySelector("[data-face-enrollment-status]");
        const title = document.querySelector("[data-face-enrollment-title]");
        const message = document.querySelector("[data-face-enrollment-message]");
        const progress = document.querySelector("[data-face-enrollment-progress]");
        const count = document.querySelector("[data-face-enrollment-count]");
        const photoWrap = document.querySelector("[data-face-enrollment-photo-wrap]");
        const photo = document.querySelector("[data-face-enrollment-photo]");

        const titleByStatus = {
            pending: "Waiting for ESP32",
            started: "ESP32 is enrolling your face",
            completed: "Face enrollment complete",
            failed: "Face enrollment failed",
            expired: "Enrollment request expired",
        };

        const renderEnrollment = (data) => {
            const status = data.status || "pending";
            const requested = Math.max(Number(data.requested_samples || 1), 1);
            const captured = Math.max(Number(data.captured_samples || 0), 0);
            const percent = Math.min(100, Math.round((captured / requested) * 100));

            if (statusBadge) {
                statusBadge.textContent = status;
                statusBadge.dataset.status = status;
            }
            if (title) {
                title.textContent = titleByStatus[status] || "Face enrollment";
            }
            if (message) {
                message.textContent = data.message || "Keep your face centered and rotate the camera angle slowly.";
            }
            if (progress) {
                progress.style.width = `${percent}%`;
            }
            if (count) {
                count.textContent = `${captured} / ${requested} samples`;
            }
            if (photoWrap && photo && data.photo_url) {
                photo.src = `${data.photo_url}?t=${encodeURIComponent(data.updated_at || Date.now())}`;
                photoWrap.classList.remove("d-none");
            }

            return status === "completed" || status === "failed" || status === "expired";
        };

        const pollEnrollment = async () => {
            try {
                const response = await fetch(statusUrl, {
                    credentials: "same-origin",
                    headers: { Accept: "application/json" },
                });
                if (!response.ok) {
                    return false;
                }

                const data = await response.json();
                return renderEnrollment(data);
            } catch (error) {
                console.warn("Face enrollment status check failed", error);
                return false;
            }
        };

        pollEnrollment().then((isDone) => {
            if (!isDone) {
                const timer = window.setInterval(async () => {
                    if (await pollEnrollment()) {
                        window.clearInterval(timer);
                    }
                }, 2500);
            }
        });
    }

    console.log("Pill box V2.01 page loaded");
});
