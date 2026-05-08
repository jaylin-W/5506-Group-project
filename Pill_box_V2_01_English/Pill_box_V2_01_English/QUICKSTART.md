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

The SQLite database is created automatically at:

```text
instance/app.db
```

Main tables:

```text
user
content_block
supplement_schedule
```

## Do Not Upload These to GitHub

```text
venv/
instance/
.env
*.db
__pycache__/
```
