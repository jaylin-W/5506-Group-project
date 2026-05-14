# Pill box V2.01 English Version

This is the English version of **Pill box V2.01**.

## Features

- Flask + SQLite web application
- Register, login, logout, and profile pages
- Personal supplement schedule management
- Users can select supplement names, intake time, and allowed time window
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

For future pill box hardware integration, POST a face recognition failure to:

```text
/api/face-unlock/failure
```

If `DEVICE_API_TOKEN` is set, include it as `X-Device-Token` and send `username` or `user_id` in the JSON body.

## Do Not Upload These to GitHub

```text
venv/
instance/
.env
*.db
__pycache__/
```
