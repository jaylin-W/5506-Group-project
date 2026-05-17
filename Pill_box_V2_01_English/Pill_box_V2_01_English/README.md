# Pill box V2.01 English Version

This is the English version of **Pill box V2.01**.

## Features

- Flask + SQLite web application
- Register, login, logout, and profile pages
- Personal supplement schedule management
- Users can select supplement names, intake time, and allowed time window
- Users can set a dose quantity for each supplement schedule
- Intake time options are spaced every 30 minutes
- Allowed time windows are spaced every 5 minutes
- Four auto-rotating advertisement cards on the home page
- Advertisement cards have no buttons and no redirects
- Hidden editor page for editing website text content
- Advertisement card text can also be edited from the hidden editor page
- Persistent SQLite storage at the project-level `instance/app.db`
- Face recognition failure alert with password unlock page and PWA notification support
- Registration now collects a separate pill box unlock password and a simple security question
- Profile page supports updating the security question, pill box unlock password, and product unlock code

## Run the Project

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open the website:

```text
http://127.0.0.1:5000
```

## Hidden Editor Page

Default editor URL:

```text
http://127.0.0.1:5000/pillbox-v2-editor-201
```

Default editor password:

```text
admin123
```

You can change these values in `.env`:

```text
HOST_PASSWORD=your-editor-password
EDITOR_ROUTE=your-hidden-editor-route
```

## Database

The SQLite database is created automatically at the project root:

```text
instance/app.db
```

You can override the location with:

```text
DATABASE_PATH=instance/app.db
```

Main tables:

```text
user
content_block
supplement_schedule
```

The demo product unlock code format is:

```text
5506xxx
```

The current demo product code is:

```text
5506123
```

Universal test activation code for repeated new-user face enrollment:

```text
5506DEV
```

Use `5506DEV` when you want to register many fresh test users and run first-time face enrollment with the same ESP32S3 camera. Formal product codes remain unique, but `5506DEV` may be reused by multiple test accounts.

For future pill box hardware integration, POST a face recognition failure to:

```text
/api/face-unlock/failure
```

If `DEVICE_API_TOKEN` is set, include it as `X-Device-Token` and send `product_code`, `username`, or `user_id` in the JSON body.

## ESP32 Face Unlock Integration

The Arduino sketch `face_recognition_unlock_servo.ino` can link the pill box hardware to this website.

Update these values in the sketch before uploading:

```cpp
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* SERVER_BASE_URL = "https://your-ngrok-url.ngrok-free.dev";
const char* DEVICE_API_TOKEN = "5506-local-device-token";
const char* PRODUCT_CODE = "5506DEV";
const char* DEVICE_ID = "xiao-esp32s3-sense-5506123";
```

The same device token must exist in `.env`:

```text
DEVICE_API_TOKEN=5506-local-device-token
```

Hardware flow:

```text
Due schedule -> ESP32 buzzer prompts the user
Face success or website PIN unlock -> ESP32 unlocks servo and enters DISPENSING
DISPENSING waits up to 600 seconds for the IR sensor to count the configured Dose Quantity
Dose Quantity reached -> ESP32 POSTs /api/device/reminder-complete and locks the servo
Timeout or insufficient quantity -> ESP32 POSTs /api/device/reminder-timeout, website marks the record missed, and servo locks
Face failure -> ESP32 POSTs /api/face-unlock/failure with product_code 5506123
After 3 failures -> website sends phone Web Push notification
User enters pill box unlock password on website -> ESP32 polls /api/face-unlock/device-status and enters DISPENSING
```

Face enrollment flow:

```text
User links product code 5506123 on Profile
User clicks Start Face Enrollment
Website opens a guided enrollment page
ESP32 polls /api/face-enrollment/device-command
ESP32 runs recognition.enroll(name) for several samples while the user rotates the product camera
ESP32 uploads each JPEG sample with photo_index and device_photo_id
Website stores the enrollment status and the face_photo records in SQLite
Each face_photo links photo_id, session_id, user_id, username, photo_index, and device_photo_id
```

## Do Not Upload These to GitHub

```text
venv/
instance/
.env
*.db
__pycache__/
```
