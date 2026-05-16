from flask import Flask, render_template, redirect, url_for, flash, request, session, jsonify, send_from_directory, send_file
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    login_required,
    current_user,
)
from flask_wtf.csrf import CSRFError, CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from email_validator import validate_email, EmailNotValidError
from pathlib import Path
from datetime import datetime, timezone, timedelta
from io import BytesIO
import sqlite3
import os
import re
import random
import json
import logging
from urllib.parse import urlparse, urljoin

try:
    from pywebpush import WebPushException, webpush
except ImportError:
    WebPushException = None
    webpush = None

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")

app = Flask(__name__)

# ===== Basic configuration =====
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
app.config["HOST_PASSWORD"] = os.environ.get("HOST_PASSWORD", "admin123")
app.config["EDITOR_ROUTE"] = os.environ.get("EDITOR_ROUTE", "pillbox-v2-editor-201")
app.config["PROJECT_NAME"] = "Pill box V2"
app.config["PROJECT_VERSION"] = "2.01"
try:
    FACE_FAILURE_THRESHOLD = max(1, int(os.environ.get("FACE_FAILURE_THRESHOLD", "3")))
except ValueError:
    FACE_FAILURE_THRESHOLD = 3
app.config["FACE_FAILURE_THRESHOLD"] = FACE_FAILURE_THRESHOLD
app.config["DEVICE_API_TOKEN"] = os.environ.get("DEVICE_API_TOKEN")
app.config["VAPID_PUBLIC_KEY"] = os.environ.get("VAPID_PUBLIC_KEY")
app.config["VAPID_PRIVATE_KEY"] = os.environ.get("VAPID_PRIVATE_KEY")
app.config["VAPID_CLAIMS_SUB"] = os.environ.get("VAPID_CLAIMS_SUB", "mailto:admin@example.com")
app.config["FACE_ENROLLMENT_REQUESTED_SAMPLES"] = 3
app.config["FACE_ENROLLMENT_WINDOW_MINUTES"] = 5
app.config["FACE_ENROLLMENT_MAX_PHOTO_BYTES"] = 700 * 1024
try:
    DISPENSE_TIMEOUT_SECONDS = max(60, int(os.environ.get("DISPENSE_TIMEOUT_SECONDS", "600")))
except ValueError:
    DISPENSE_TIMEOUT_SECONDS = 600
app.config["DISPENSE_TIMEOUT_SECONDS"] = DISPENSE_TIMEOUT_SECONDS

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

csrf = CSRFProtect(app)


def get_rate_limit_key():
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if request.remote_addr in {"127.0.0.1", "::1"} and forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return get_remote_address()


limiter = Limiter(
    app=app,
    key_func=get_rate_limit_key,
    default_limits=["200 per day", "50 per hour"]
)

APP_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = APP_ROOT.parents[1]
INSTANCE_PATH = PROJECT_ROOT / "instance"
INSTANCE_PATH.mkdir(parents=True, exist_ok=True)
DATABASE_ENV = os.environ.get("DATABASE_PATH")
if DATABASE_ENV:
    configured_database = Path(DATABASE_ENV).expanduser()
    DATABASE = configured_database if configured_database.is_absolute() else PROJECT_ROOT / configured_database
else:
    DATABASE = INSTANCE_PATH / "app.db"
DATABASE.parent.mkdir(parents=True, exist_ok=True)

SUPPLEMENT_OPTIONS = [
    "Fish Oil",
    "Vitamin A",
    "Vitamin B Complex",
    "Vitamin C",
    "Vitamin D",
    "Vitamin E",
    "Calcium Tablet",
    "Iron Tablet",
    "Zinc Tablet",
    "Magnesium Tablet",
    "Folic Acid",
    "Probiotics",
    "Collagen",
    "Coenzyme Q10",
    "Melatonin",
    "Protein Powder",
]

TIME_OPTIONS = [
    f"{hour:02d}:{minute:02d}"
    for hour in range(24)
    for minute in (0, 30)
]

WINDOW_OPTIONS = list(range(5, 65, 5))
DOSE_QUANTITY_OPTIONS = list(range(1, 11))

PRODUCT_CODE_EXAMPLE = "5506xxx"
DEFAULT_PRODUCT_CODE = "5506123"
DEFAULT_DEVICE_ID = f"xiao-esp32s3-sense-{DEFAULT_PRODUCT_CODE}"

SECURITY_QUESTIONS = [
    ("math_1_plus_1", "1 + 1 = ?"),
    ("math_2_plus_3", "2 + 3 = ?"),
    ("math_5_minus_2", "5 - 2 = ?"),
    ("math_3_times_2", "3 x 2 = ?"),
    ("math_10_divide_2", "10 / 2 = ?"),
]
SECURITY_QUESTION_LABELS = dict(SECURITY_QUESTIONS)

PROMO_AD_IMAGES = [
    "promo_vitamin_c.png",
    "promo_fish_oil.png",
    "promo_gut_health.png",
    "promo_multivitamin.png",
]

DEFAULT_CONTENT_BLOCKS = {
    "home_hero_title": "Smart Supplement Pill Box Makes Daily Health Management Easier",
    "home_hero_subtitle": (
        "This system presents a smart supplement pill box designed for families, students, office workers, and older adults."
        "It helps users record supplement schedules, receive timely reminders, and reduce missed or repeated doses."
    ),
    "home_feature_1_title": "Smart Reminders",
    "home_feature_1_body": "Based on the user’s supplement schedule, the system reminds users to take their supplements on time through the website, device, or mobile interface.",
    "home_feature_2_title": "Organized Storage",
    "home_feature_2_body": "The pill box can organize supplements by morning, noon, evening, or supplement type, making them easier to find and manage.",
    "home_feature_3_title": "Health Profile",
    "home_feature_3_body": "Users can maintain age, health goals, and other basic information on their profile page to support future personalized management.",
    "promo_1_badge": "Limited-Time Deal",
    "promo_1_title": "Vitamin C Energy Boost Season",
    "promo_1_subtitle": "Fruity Nutrition Picks · Up to 30% Off",
    "promo_1_desc": "A promotional card for daily nutrition support and busy lifestyles. Display only, with no button or redirect.",
    "promo_2_badge": "Member Exclusive",
    "promo_2_title": "Deep-Sea Fish Oil Special Offer",
    "promo_2_subtitle": "High-Purity Fish Oil Softgels · Second Item Half Price",
    "promo_2_desc": "A premium ocean-inspired promotion card for users interested in daily heart and brain wellness support.",
    "promo_3_badge": "Bundle Offer",
    "promo_3_title": "Probiotic Care Bundle",
    "promo_3_subtitle": "Gut Wellness Plan · Save 20 on Orders Over 99",
    "promo_3_desc": "A soft green wellness-themed card for light nutrition and digestive health support.",
    "promo_4_badge": "New Customer Pick",
    "promo_4_title": "Daily Multivitamin Nutrition Box",
    "promo_4_subtitle": "Colorful Nutrition Set · New Customers Save 15",
    "promo_4_desc": "A bright and friendly basic supplement promotion card for students, office workers, and families.",

    "about_intro_title": "About the Smart Supplement Pill Box",
    "about_intro_body": (
        "The core goal of the smart supplement pill box is to help users build stable, clear, and sustainable supplement habits."
        "Traditional pill boxes only provide basic storage, while a smart pill box combines reminders, records, and account features, "
        "making it easier for users to manage their supplement routines."
    ),
}


def get_db_connection():
    try:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.DatabaseError as e:
        logger.error(f"Database connection failed: {e}")
        raise


def validate_username(username):
    if not username or len(username) < 3 or len(username) > 20:
        return False, "Username must be 3–20 characters long."
    if not re.match(r"^[a-zA-Z0-9_-]+$", username):
        return False, "Username can only contain letters, numbers, underscores, and hyphens."
    return True, None


def validate_email_format(email):
    try:
        valid = validate_email(email.strip().lower(), check_deliverability=False)
        return True, valid.email
    except EmailNotValidError as e:
        return False, str(e)


def validate_password(password):
    if len(password) < 6:
        return False, "Password must be at least 6 characters long."
    return True, None


def validate_unlock_password(password):
    if len(password) < 4:
        return False, "Pill box unlock password must be at least 4 characters long."
    return True, None


def normalize_security_answer(answer):
    return " ".join(answer.strip().lower().split())


def validate_security_question(question_key):
    if question_key not in SECURITY_QUESTION_LABELS:
        return False, "Please select a valid security question."
    return True, None


def validate_security_answer(answer):
    normalized_answer = normalize_security_answer(answer)
    if not normalized_answer:
        return False, "Please enter the answer to your security question."
    if len(normalized_answer) > 100:
        return False, "Security answer must be 100 characters or fewer."
    return True, normalized_answer


def validate_product_code(product_code):
    normalized_code = product_code.strip().upper()
    if not normalized_code:
        return True, None
    if not re.match(r"^5506[A-Z0-9]{3}$", normalized_code):
        return False, f"Product unlock code must match the format {PRODUCT_CODE_EXAMPLE}, for example {DEFAULT_PRODUCT_CODE}."
    return True, normalized_code


def validate_device_id(device_id):
    normalized_id = device_id.strip()
    if not normalized_id:
        return True, None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{2,63}", normalized_id):
        return False, "Device ID must be 3-64 characters and may only contain letters, numbers, hyphens, and underscores."
    return True, normalized_id


def get_security_questions(randomize=False):
    questions = SECURITY_QUESTIONS.copy()
    if randomize:
        random.shuffle(questions)
    return questions


def validate_age(age_str):
    if not age_str or age_str.strip() == "":
        return True, None
    try:
        age = int(age_str)
        if age < 0 or age > 150:
            return False, "Age must be a number between 0 and 150."
        return True, age
    except ValueError:
        return False, "Age must be a number."


def validate_dose_quantity(quantity_str):
    try:
        quantity = int(quantity_str)
    except (TypeError, ValueError):
        return False, "Please select a valid dose quantity."
    if quantity not in DOSE_QUANTITY_OPTIONS:
        return False, "Dose quantity must be between 1 and 10."
    return True, quantity


def ensure_column(conn, table_name, column_name, column_sql):
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in columns:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")


def init_db():
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            unlock_password_hash TEXT,
            security_question TEXT,
            security_answer_hash TEXT,
            product_code TEXT,
            device_id TEXT,
            age INTEGER,
            health_goal TEXT,
            face_failed_attempts INTEGER NOT NULL DEFAULT 0,
            unlock_required INTEGER NOT NULL DEFAULT 0,
            last_face_failure_at TEXT,
            last_unlock_at TEXT
        )
        """
    )
    ensure_column(conn, "user", "unlock_password_hash", "unlock_password_hash TEXT")
    ensure_column(conn, "user", "security_question", "security_question TEXT")
    ensure_column(conn, "user", "security_answer_hash", "security_answer_hash TEXT")
    ensure_column(conn, "user", "product_code", "product_code TEXT")
    ensure_column(conn, "user", "device_id", "device_id TEXT")
    ensure_column(conn, "user", "face_failed_attempts", "face_failed_attempts INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "user", "unlock_required", "unlock_required INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "user", "last_face_failure_at", "last_face_failure_at TEXT")
    ensure_column(conn, "user", "last_unlock_at", "last_unlock_at TEXT")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_user_product_code
        ON user(product_code)
        WHERE product_code IS NOT NULL
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_user_device_id
        ON user(device_id)
        WHERE device_id IS NOT NULL
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS content_block (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            block_key TEXT UNIQUE NOT NULL,
            block_value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS supplement_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            supplement_name TEXT NOT NULL,
            take_time TEXT NOT NULL,
            time_window INTEGER NOT NULL,
            dose_quantity INTEGER NOT NULL DEFAULT 1,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES user(id)
        )
        """
    )
    ensure_column(conn, "supplement_schedule", "dose_quantity", "dose_quantity INTEGER NOT NULL DEFAULT 1")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS push_subscription (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            endpoint TEXT UNIQUE NOT NULL,
            subscription_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES user(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS face_enrollment_session (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_code TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            person_name TEXT NOT NULL,
            requested_samples INTEGER NOT NULL DEFAULT 3,
            captured_samples INTEGER NOT NULL DEFAULT 0,
            message TEXT,
            device_id TEXT,
            photo_mime TEXT,
            photo_data BLOB,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            completed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES user(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS device_reminder_event (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            schedule_id INTEGER NOT NULL,
            reminder_key TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            device_id TEXT,
            target_quantity INTEGER NOT NULL DEFAULT 1,
            taken_quantity INTEGER NOT NULL DEFAULT 0,
            triggered_at TEXT NOT NULL,
            completed_at TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES user(id),
            FOREIGN KEY (schedule_id) REFERENCES supplement_schedule(id)
        )
        """
    )
    ensure_column(conn, "device_reminder_event", "target_quantity", "target_quantity INTEGER NOT NULL DEFAULT 1")
    ensure_column(conn, "device_reminder_event", "taken_quantity", "taken_quantity INTEGER NOT NULL DEFAULT 0")
    conn.execute(
        """
        UPDATE user
        SET device_id = ?
        WHERE product_code = ?
          AND (device_id IS NULL OR device_id = '')
          AND NOT EXISTS (
              SELECT 1 FROM user WHERE device_id = ?
          )
        """,
        (DEFAULT_DEVICE_ID, DEFAULT_PRODUCT_CODE, DEFAULT_DEVICE_ID),
    )
    for key, value in DEFAULT_CONTENT_BLOCKS.items():
        conn.execute(
            "INSERT OR IGNORE INTO content_block (block_key, block_value) VALUES (?, ?)",
            (key, value),
        )
    conn.commit()
    conn.close()


class User(UserMixin):
    def __init__(
        self,
        id,
        username,
        email,
        password_hash,
        age=None,
        health_goal=None,
        unlock_password_hash=None,
        security_question=None,
        security_answer_hash=None,
        product_code=None,
        device_id=None,
        face_failed_attempts=0,
        unlock_required=0,
        last_face_failure_at=None,
        last_unlock_at=None,
    ):
        self.id = id
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.age = age
        self.health_goal = health_goal
        self.unlock_password_hash = unlock_password_hash
        self.security_question = security_question
        self.security_answer_hash = security_answer_hash
        self.product_code = product_code
        self.device_id = device_id
        self.face_failed_attempts = face_failed_attempts or 0
        self.unlock_required = bool(unlock_required)
        self.last_face_failure_at = last_face_failure_at
        self.last_unlock_at = last_unlock_at

    @staticmethod
    def from_row(row):
        if row is None:
            return None
        return User(
            id=row["id"],
            username=row["username"],
            email=row["email"],
            password_hash=row["password_hash"],
            age=row["age"],
            health_goal=row["health_goal"],
            unlock_password_hash=row["unlock_password_hash"],
            security_question=row["security_question"],
            security_answer_hash=row["security_answer_hash"],
            product_code=row["product_code"],
            device_id=row["device_id"],
            face_failed_attempts=row["face_failed_attempts"],
            unlock_required=row["unlock_required"],
            last_face_failure_at=row["last_face_failure_at"],
            last_unlock_at=row["last_unlock_at"],
        )

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def check_unlock_password(self, password):
        if self.unlock_password_hash:
            return check_password_hash(self.unlock_password_hash, password)
        return self.check_password(password)


login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in before accessing your profile page."
login_manager.login_message_category = "warning"


@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM user WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return User.from_row(row)


def get_content_blocks():
    conn = get_db_connection()
    rows = conn.execute("SELECT block_key, block_value FROM content_block").fetchall()
    conn.close()
    blocks = DEFAULT_CONTENT_BLOCKS.copy()
    for row in rows:
        blocks[row["block_key"]] = row["block_value"]
    return blocks




def get_promo_ads(blocks):
    """Read the four advertisement card text blocks from the database and combine them with background images."""
    ads = []
    for index, image in enumerate(PROMO_AD_IMAGES, start=1):
        ads.append(
            {
                "image": image,
                "badge": blocks.get(f"promo_{index}_badge", ""),
                "title": blocks.get(f"promo_{index}_title", ""),
                "subtitle": blocks.get(f"promo_{index}_subtitle", ""),
                "desc": blocks.get(f"promo_{index}_desc", ""),
            }
        )
    return ads


def get_user_schedules(user_id):
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT id, supplement_name, take_time, time_window, dose_quantity, note, created_at
        FROM supplement_schedule
        WHERE user_id = ?
        ORDER BY take_time ASC, id DESC
        """,
        (user_id,),
    ).fetchall()
    conn.close()
    return rows


def local_now():
    return datetime.now().astimezone()


def parse_take_time_minutes(take_time):
    try:
        hour, minute = take_time.split(":", 1)
        return int(hour) * 60 + int(minute)
    except (AttributeError, ValueError):
        return None


def circular_minute_distance(left, right):
    distance = abs(left - right)
    return min(distance, 24 * 60 - distance)


def minutes_until_window_start(now_minutes, schedule):
    scheduled_minutes = parse_take_time_minutes(schedule["take_time"])
    if scheduled_minutes is None:
        return None
    start_minutes = (scheduled_minutes - int(schedule["time_window"])) % (24 * 60)
    return (start_minutes - now_minutes) % (24 * 60)


def serialize_schedule_for_device(row, now=None):
    now = now or local_now()
    scheduled_minutes = parse_take_time_minutes(row["take_time"])
    now_minutes = now.hour * 60 + now.minute
    minutes_from_target = None
    is_due = False
    if scheduled_minutes is not None:
        minutes_from_target = circular_minute_distance(now_minutes, scheduled_minutes)
        is_due = minutes_from_target <= int(row["time_window"])

    reminder_key = f"{row['id']}:{now.date().isoformat()}:{row['take_time']}"
    window_start_minutes = (scheduled_minutes - int(row["time_window"])) % (24 * 60) if scheduled_minutes is not None else None
    window_end_minutes = (scheduled_minutes + int(row["time_window"])) % (24 * 60) if scheduled_minutes is not None else None
    return {
        "schedule_id": row["id"],
        "reminder_key": reminder_key,
        "supplement_name": row["supplement_name"],
        "take_time": row["take_time"],
        "time_window": row["time_window"],
        "dose_quantity": row["dose_quantity"],
        "note": row["note"],
        "is_due": is_due,
        "minutes_from_target": minutes_from_target,
        "window_start": f"{window_start_minutes // 60:02d}:{window_start_minutes % 60:02d}" if window_start_minutes is not None else None,
        "window_end": f"{window_end_minutes // 60:02d}:{window_end_minutes % 60:02d}" if window_end_minutes is not None else None,
    }


def get_device_reminder_event(user_id, reminder_key):
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT id, status, completed_at, target_quantity, taken_quantity
        FROM device_reminder_event
        WHERE user_id = ? AND reminder_key = ?
        """,
        (user_id, reminder_key),
    ).fetchone()
    conn.close()
    return row


def record_device_reminder_event(user_id, reminder, device_id=None):
    now = utc_now_iso()
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO device_reminder_event
            (user_id, schedule_id, reminder_key, status, device_id, target_quantity, taken_quantity, triggered_at, updated_at)
            VALUES (?, ?, ?, 'pending', ?, ?, 0, ?, ?)
            ON CONFLICT(reminder_key) DO UPDATE SET
                device_id = COALESCE(excluded.device_id, device_reminder_event.device_id),
                target_quantity = excluded.target_quantity,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                reminder["schedule_id"],
                reminder["reminder_key"],
                device_id,
                reminder["dose_quantity"],
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def record_medication_dispensed(user_id, reminder_key, device_id=None, count=1):
    now = utc_now_iso()
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT id, target_quantity, taken_quantity
            FROM device_reminder_event
            WHERE user_id = ? AND reminder_key = ?
            """,
            (user_id, reminder_key),
        ).fetchone()
        if row is None:
            return None

        taken_quantity = min(row["target_quantity"], (row["taken_quantity"] or 0) + max(1, count))
        status = "completed" if taken_quantity >= row["target_quantity"] else "dispensing"
        completed_at = now if status == "completed" else None
        conn.execute(
            """
            UPDATE device_reminder_event
            SET status = ?,
                taken_quantity = ?,
                completed_at = COALESCE(?, completed_at),
                updated_at = ?,
                device_id = COALESCE(?, device_id)
            WHERE id = ?
            """,
            (status, taken_quantity, completed_at, now, device_id, row["id"]),
        )
        conn.commit()
        return {
            "reminder_key": reminder_key,
            "target_quantity": row["target_quantity"],
            "taken_quantity": taken_quantity,
            "completed": status == "completed",
        }
    finally:
        conn.close()


def complete_device_reminder_event(user_id, reminder_key, device_id=None, taken_quantity=None):
    now = utc_now_iso()
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT target_quantity, taken_quantity
            FROM device_reminder_event
            WHERE user_id = ? AND reminder_key = ?
            """,
            (user_id, reminder_key),
        ).fetchone()
        if row is None:
            return False
        try:
            final_taken = row["taken_quantity"] if taken_quantity is None else max(0, int(taken_quantity))
        except (TypeError, ValueError):
            final_taken = row["taken_quantity"]
        final_taken = max(final_taken, row["target_quantity"])
        cursor = conn.execute(
            """
            UPDATE device_reminder_event
            SET status = 'completed',
                taken_quantity = ?,
                completed_at = COALESCE(completed_at, ?),
                updated_at = ?,
                device_id = COALESCE(?, device_id)
            WHERE user_id = ? AND reminder_key = ?
            """,
            (final_taken, now, now, device_id, user_id, reminder_key),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def timeout_device_reminder_event(user_id, reminder_key, device_id=None, taken_quantity=None):
    now = utc_now_iso()
    conn = get_db_connection()
    try:
        try:
            final_taken = max(0, int(taken_quantity or 0))
        except (TypeError, ValueError):
            final_taken = 0
        cursor = conn.execute(
            """
            UPDATE device_reminder_event
            SET status = 'missed',
                taken_quantity = MAX(taken_quantity, ?),
                completed_at = COALESCE(completed_at, ?),
                updated_at = ?,
                device_id = COALESCE(?, device_id)
            WHERE user_id = ? AND reminder_key = ?
            """,
            (final_taken, now, now, device_id, user_id, reminder_key),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_device_reminder_state(user_id, device_id=None):
    now = local_now()
    schedules = [serialize_schedule_for_device(row, now) for row in get_user_schedules(user_id)]
    due_schedules = [schedule for schedule in schedules if schedule["is_due"]]
    due_schedules.sort(key=lambda schedule: (schedule["minutes_from_target"], schedule["take_time"], schedule["schedule_id"]))

    active_reminder = None
    if due_schedules:
        candidate = due_schedules[0]
        event = get_device_reminder_event(user_id, candidate["reminder_key"])
        if event is None or event["status"] not in ("completed", "missed"):
            record_device_reminder_event(user_id, candidate, device_id)
            event = get_device_reminder_event(user_id, candidate["reminder_key"])
            if event is not None:
                candidate["target_quantity"] = event["target_quantity"]
                candidate["taken_quantity"] = event["taken_quantity"]
                candidate["event_status"] = event["status"]
            active_reminder = candidate

    face_status = get_face_unlock_status(user_id)
    device_action = "idle"
    if face_status and face_status.get("unlock_required"):
        device_action = "wait_for_pin"
    elif active_reminder:
        device_action = "ring_reminder"

    next_reminder = None
    seconds_until_next_window = None
    if schedules:
        next_reminder = sorted(
            schedules,
            key=lambda schedule: (
                minutes_until_window_start(now.hour * 60 + now.minute, schedule) if minutes_until_window_start(now.hour * 60 + now.minute, schedule) is not None else 24 * 60,
                schedule["take_time"],
                schedule["schedule_id"],
            ),
        )[0]
        until_minutes = minutes_until_window_start(now.hour * 60 + now.minute, next_reminder)
        if until_minutes is not None:
            seconds_until_next_window = max(0, until_minutes * 60 - now.second)

    state = {
        "device_action": device_action,
        "server_time": now.isoformat(timespec="seconds"),
        "active_reminder": active_reminder,
        "next_reminder": next_reminder,
        "seconds_until_next_window": seconds_until_next_window,
        "sleep_recommended": device_action == "idle" and seconds_until_next_window is not None and seconds_until_next_window > 60,
        "dispense_timeout_seconds": app.config["DISPENSE_TIMEOUT_SECONDS"],
        "schedules": schedules,
        "face_unlock": face_status,
    }
    if active_reminder:
        state.update(
            {
                "reminder_key": active_reminder["reminder_key"],
                "schedule_id": active_reminder["schedule_id"],
                "supplement_name": active_reminder["supplement_name"],
                "take_time": active_reminder["take_time"],
                "time_window": active_reminder["time_window"],
                "dose_quantity": active_reminder["dose_quantity"],
                "target_quantity": active_reminder.get("target_quantity", active_reminder["dose_quantity"]),
                "taken_quantity": active_reminder.get("taken_quantity", 0),
                "dispense_timeout_seconds": app.config["DISPENSE_TIMEOUT_SECONDS"],
            }
        )
    return state


def utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_face_unlock_status(user_id):
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT face_failed_attempts, unlock_required, last_face_failure_at, last_unlock_at
        FROM user
        WHERE id = ?
        """,
        (user_id,),
    ).fetchone()
    conn.close()

    if row is None:
        return None

    failed_attempts = row["face_failed_attempts"] or 0
    threshold = app.config["FACE_FAILURE_THRESHOLD"]
    return {
        "failed_attempts": failed_attempts,
        "failure_threshold": threshold,
        "unlock_required": bool(row["unlock_required"]) or failed_attempts >= threshold,
        "last_face_failure_at": row["last_face_failure_at"],
        "last_unlock_at": row["last_unlock_at"],
        "notification_title": f"目前面部识别已失败{threshold}次",
        "notification_body": "请进入网站，输入解锁密码。",
        "page_alert_title": "请输入密码解锁药盒",
    }


def record_face_failure(user_id):
    conn = get_db_connection()
    should_notify = False
    try:
        row = conn.execute(
            "SELECT face_failed_attempts, unlock_required FROM user WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None

        threshold = app.config["FACE_FAILURE_THRESHOLD"]
        was_unlock_required = bool(row["unlock_required"])
        failed_attempts = (row["face_failed_attempts"] or 0) + 1
        unlock_required = 1 if failed_attempts >= threshold else row["unlock_required"]
        should_notify = failed_attempts >= threshold and not was_unlock_required
        conn.execute(
            """
            UPDATE user
            SET face_failed_attempts = ?, unlock_required = ?, last_face_failure_at = ?
            WHERE id = ?
            """,
            (failed_attempts, unlock_required, utc_now_iso(), user_id),
        )
        conn.commit()
    finally:
        conn.close()

    status = get_face_unlock_status(user_id)
    if status is not None:
        status["should_notify"] = should_notify
        status["device_action"] = "wait_for_pin" if status["unlock_required"] else "retry_face"
    return status


def reset_face_unlock_status(user_id):
    conn = get_db_connection()
    try:
        conn.execute(
            """
            UPDATE user
            SET face_failed_attempts = 0, unlock_required = 0, last_unlock_at = ?
            WHERE id = ?
            """,
            (utc_now_iso(), user_id),
        )
        conn.commit()
    finally:
        conn.close()


def find_user_id_from_payload(payload):
    user_id = payload.get("user_id")
    username = (payload.get("username") or "").strip()
    product_code = (payload.get("product_code") or "").strip().upper()
    device_id = (payload.get("device_id") or "").strip()

    conn = get_db_connection()
    try:
        row = None
        if device_id:
            row = conn.execute("SELECT id FROM user WHERE device_id = ?", (device_id,)).fetchone()
        if row is None and user_id:
            row = conn.execute("SELECT id FROM user WHERE id = ?", (user_id,)).fetchone()
        if row is None and username:
            row = conn.execute("SELECT id FROM user WHERE username = ?", (username,)).fetchone()
        if row is None and product_code:
            row = conn.execute("SELECT id FROM user WHERE product_code = ?", (product_code,)).fetchone()
    finally:
        conn.close()

    return row["id"] if row else None


def resolve_device_request_user(payload):
    configured_token = app.config["DEVICE_API_TOKEN"]
    provided_token = request.headers.get("X-Device-Token") or payload.get("device_token")

    if configured_token:
        if provided_token != configured_token:
            return None, ("Invalid device token.", 403)

        user_id = find_user_id_from_payload(payload)
        if user_id is None and current_user.is_authenticated:
            user_id = current_user.id
    elif current_user.is_authenticated:
        user_id = current_user.id
    else:
        return None, ("Login required or configure DEVICE_API_TOKEN for the pill box device.", 401)

    if user_id is None:
        return None, ("User not found. Send product_code, username, or user_id with the device request.", 404)

    return user_id, None


def get_device_payload():
    payload = request.get_json(silent=True) or {}
    if not payload:
        payload = {}

    product_code = request.headers.get("X-Product-Code") or request.args.get("product_code")
    device_id = request.headers.get("X-Device-Id") or request.args.get("device_id")
    if product_code and not payload.get("product_code"):
        payload["product_code"] = product_code
    if device_id and not payload.get("device_id"):
        payload["device_id"] = device_id
    return payload


def create_face_enrollment_session(user):
    now = utc_now_iso()
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=app.config["FACE_ENROLLMENT_WINDOW_MINUTES"])).replace(microsecond=0).isoformat()
    person_name = re.sub(r"[^A-Za-z0-9_-]+", "_", user.username).strip("_") or f"user_{user.id}"

    conn = get_db_connection()
    try:
        conn.execute(
            """
            UPDATE face_enrollment_session
            SET status = 'expired', updated_at = ?
            WHERE user_id = ? AND status IN ('pending', 'started')
            """,
            (now, user.id),
        )
        cursor = conn.execute(
            """
            INSERT INTO face_enrollment_session
            (user_id, product_code, status, person_name, requested_samples, captured_samples, created_at, updated_at, expires_at)
            VALUES (?, ?, 'pending', ?, ?, 0, ?, ?, ?)
            """,
            (
                user.id,
                user.product_code,
                person_name,
                app.config["FACE_ENROLLMENT_REQUESTED_SAMPLES"],
                now,
                now,
                expires_at,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_face_enrollment_session(session_id, user_id=None):
    conn = get_db_connection()
    try:
        if user_id is None:
            row = conn.execute(
                "SELECT * FROM face_enrollment_session WHERE id = ?",
                (session_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM face_enrollment_session WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
    finally:
        conn.close()
    return row


def serialize_face_enrollment_session(row):
    has_photo = bool(row["photo_data"])
    return {
        "id": row["id"],
        "status": row["status"],
        "product_code": row["product_code"],
        "person_name": row["person_name"],
        "requested_samples": row["requested_samples"],
        "captured_samples": row["captured_samples"],
        "message": row["message"],
        "device_id": row["device_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "expires_at": row["expires_at"],
        "completed_at": row["completed_at"],
        "has_photo": has_photo,
        "photo_url": url_for("face_enrollment_photo", session_id=row["id"]) if has_photo else None,
    }


def get_active_face_enrollment_for_user(user_id):
    now = utc_now_iso()
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT *
            FROM face_enrollment_session
            WHERE user_id = ? AND status IN ('pending', 'started') AND expires_at > ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id, now),
        ).fetchone()
    finally:
        conn.close()
    return row


def get_latest_face_enrollment_for_user(user_id):
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT *
            FROM face_enrollment_session
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    finally:
        conn.close()
    return row


def mark_face_enrollment_started(row, device_id=None):
    now = utc_now_iso()
    conn = get_db_connection()
    try:
        conn.execute(
            """
            UPDATE face_enrollment_session
            SET status = 'started', device_id = COALESCE(?, device_id), updated_at = ?
            WHERE id = ? AND status IN ('pending', 'started')
            """,
            (device_id, now, row["id"]),
        )
        conn.commit()
    finally:
        conn.close()


def update_face_enrollment_result(session_id, user_id, status, captured_samples=0, message=None, device_id=None):
    now = utc_now_iso()
    completed_at = now if status in ("completed", "failed", "expired") else None
    conn = get_db_connection()
    try:
        conn.execute(
            """
            UPDATE face_enrollment_session
            SET status = ?,
                captured_samples = ?,
                message = ?,
                device_id = COALESCE(?, device_id),
                updated_at = ?,
                completed_at = COALESCE(?, completed_at)
            WHERE id = ? AND user_id = ?
            """,
            (status, captured_samples, message, device_id, now, completed_at, session_id, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def save_face_enrollment_photo(session_id, user_id, photo_data, photo_mime, device_id=None):
    now = utc_now_iso()
    conn = get_db_connection()
    try:
        conn.execute(
            """
            UPDATE face_enrollment_session
            SET photo_data = ?,
                photo_mime = ?,
                device_id = COALESCE(?, device_id),
                updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (photo_data, photo_mime, device_id, now, session_id, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def save_push_subscription(user_id, subscription):
    endpoint = subscription.get("endpoint")
    if not endpoint:
        return False, "Push subscription endpoint is missing."

    subscription_json = json.dumps(subscription, separators=(",", ":"))
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO push_subscription (user_id, endpoint, subscription_json)
            VALUES (?, ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET
                user_id = excluded.user_id,
                subscription_json = excluded.subscription_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, endpoint, subscription_json),
        )
        conn.commit()
    finally:
        conn.close()

    return True, None


def delete_push_subscription(endpoint):
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM push_subscription WHERE endpoint = ?", (endpoint,))
        conn.commit()
    finally:
        conn.close()


def get_push_subscriptions(user_id):
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT endpoint, subscription_json
        FROM push_subscription
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchall()
    conn.close()
    return rows


def count_push_subscriptions(user_id):
    conn = get_db_connection()
    count = conn.execute(
        "SELECT COUNT(*) FROM push_subscription WHERE user_id = ?",
        (user_id,),
    ).fetchone()[0]
    conn.close()
    return count


def can_send_web_push():
    return bool(webpush and app.config["VAPID_PUBLIC_KEY"] and app.config["VAPID_PRIVATE_KEY"])


def send_web_push_notification(user_id, status):
    subscriptions = get_push_subscriptions(user_id)
    logger.info(
        "Web Push requested for user_id=%s subscriptions=%s configured=%s",
        user_id,
        len(subscriptions),
        can_send_web_push(),
    )
    if not can_send_web_push():
        logger.info("Web Push skipped: pywebpush or VAPID keys are not configured.")
        return {"sent": 0, "configured": False, "subscriptions": len(subscriptions)}

    payload = json.dumps(
        {
            "title": status["notification_title"],
            "body": status["notification_body"],
            "url": url_for("unlock_pill_box"),
            "interaction": True,
        },
        ensure_ascii=False,
    )
    sent_count = 0

    for row in subscriptions:
        try:
            webpush(
                subscription_info=json.loads(row["subscription_json"]),
                data=payload,
                vapid_private_key=app.config["VAPID_PRIVATE_KEY"],
                vapid_claims={"sub": app.config["VAPID_CLAIMS_SUB"]},
            )
            sent_count += 1
        except WebPushException as e:
            logger.warning(f"Web Push failed for {row['endpoint']}: {e}")
            if getattr(e, "response", None) and e.response.status_code in (404, 410):
                delete_push_subscription(row["endpoint"])
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            logger.warning(f"Invalid stored push subscription: {e}")
            delete_push_subscription(row["endpoint"])

    logger.info("Web Push completed for user_id=%s sent=%s subscriptions=%s", user_id, sent_count, len(subscriptions))
    return {"sent": sent_count, "configured": True, "subscriptions": len(subscriptions)}


def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc


@app.context_processor
def inject_global_data():
    return {
        "project_name": app.config["PROJECT_NAME"],
        "project_version": app.config["PROJECT_VERSION"],
    }


init_db()


@app.route("/")
def index():
    blocks = get_content_blocks()
    promo_ads = get_promo_ads(blocks)
    return render_template("index.html", blocks=blocks, promo_ads=promo_ads)


@app.route("/service-worker.js")
def service_worker():
    response = send_from_directory(app.static_folder, "sw.js", mimetype="application/javascript")
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.route("/about")
def about():
    blocks = get_content_blocks()
    return render_template("about.html", blocks=blocks)


@limiter.limit("5 per minute", methods=["POST"])
def host():
    if request.method == "POST" and request.form.get("action") == "login":
        password = request.form.get("host_password", "")
        if password == app.config["HOST_PASSWORD"]:
            session["host_logged_in"] = True
            logger.info(f"Editor admin login successful: {request.remote_addr}")
            flash("Editor page login successful.", "success")
            return redirect(url_for("host"))
        logger.warning(f"Editor admin login failed: {request.remote_addr}")
        flash("Incorrect editor password.", "danger")
        return redirect(url_for("host"))

    if not session.get("host_logged_in"):
        return render_template("host_login.html")

    if request.method == "POST" and request.form.get("action") == "save_content":
        conn = get_db_connection()
        try:
            for key in DEFAULT_CONTENT_BLOCKS.keys():
                value = request.form.get(key, "").strip() or DEFAULT_CONTENT_BLOCKS[key]
                conn.execute(
                    """
                    INSERT INTO content_block (block_key, block_value)
                    VALUES (?, ?)
                    ON CONFLICT(block_key) DO UPDATE SET block_value = excluded.block_value
                    """,
                    (key, value),
                )
            conn.commit()
            logger.info("Editor content updated")
            flash("Content blocks have been saved. The home and about pages have been updated.", "success")
        except sqlite3.DatabaseError as e:
            logger.error(f"Failed to save editor content: {e}")
            flash("Save failed. Please try again later.", "danger")
        finally:
            conn.close()
        return redirect(url_for("host"))

    blocks = get_content_blocks()
    return render_template("host.html", blocks=blocks, editor_path=app.config["EDITOR_ROUTE"])


app.add_url_rule(f"/{app.config['EDITOR_ROUTE']}", endpoint="host", view_func=host, methods=["GET", "POST"])


@app.route(f"/{app.config['EDITOR_ROUTE']}/logout")
def host_logout():
    session.pop("host_logged_in", None)
    flash("You have logged out of the editor page.", "info")
    return redirect(url_for("index"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("profile"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        normalized_username = username.lower()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        unlock_password = request.form.get("unlock_password", "")
        confirm_unlock_password = request.form.get("confirm_unlock_password", "")
        security_question = request.form.get("security_question", "").strip()
        security_answer = request.form.get("security_answer", "")
        product_code = request.form.get("product_code", "")

        valid, msg = validate_username(username)
        if not valid:
            flash(msg, "danger")
            return redirect(url_for("register"))

        valid, result = validate_email_format(email)
        if not valid:
            flash(f"Invalid email format: {result}", "danger")
            return redirect(url_for("register"))
        email = result

        if not password:
            flash("Please enter a password.", "danger")
            return redirect(url_for("register"))

        valid, msg = validate_password(password)
        if not valid:
            flash(msg, "danger")
            return redirect(url_for("register"))

        if password != confirm_password:
            flash("The two passwords do not match.", "danger")
            return redirect(url_for("register"))

        if not unlock_password:
            flash("Please enter a pill box unlock password.", "danger")
            return redirect(url_for("register"))

        valid, msg = validate_unlock_password(unlock_password)
        if not valid:
            flash(msg, "danger")
            return redirect(url_for("register"))

        if unlock_password != confirm_unlock_password:
            flash("The two pill box unlock passwords do not match.", "danger")
            return redirect(url_for("register"))

        valid, msg = validate_security_question(security_question)
        if not valid:
            flash(msg, "danger")
            return redirect(url_for("register"))

        valid, security_answer_value = validate_security_answer(security_answer)
        if not valid:
            flash(security_answer_value, "danger")
            return redirect(url_for("register"))

        valid, product_code_value = validate_product_code(product_code)
        if not valid:
            flash(product_code_value, "danger")
            return redirect(url_for("register"))

        device_id_value = f"xiao-esp32s3-sense-{product_code_value}" if product_code_value else None

        conn = get_db_connection()
        existing_user = conn.execute(
            "SELECT * FROM user WHERE lower(username) = ? OR lower(email) = ?",
            (normalized_username, email.lower()),
        ).fetchone()

        if existing_user:
            conn.close()
            flash("Username or email is already registered.", "danger")
            return redirect(url_for("register"))

        password_hash = generate_password_hash(password)
        unlock_password_hash = generate_password_hash(unlock_password)
        security_answer_hash = generate_password_hash(security_answer_value)
        try:
            conn.execute(
                """
                INSERT INTO user
                (username, email, password_hash, unlock_password_hash, security_question, security_answer_hash, product_code, device_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    username,
                    email,
                    password_hash,
                    unlock_password_hash,
                    security_question,
                    security_answer_hash,
                    product_code_value,
                    device_id_value,
                ),
            )
            user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()
            logger.info(f"New user registered: {username}")
        except sqlite3.IntegrityError:
            flash("This product serial number is already linked to another account.", "danger")
            return redirect(url_for("register"))
        except sqlite3.DatabaseError as e:
            logger.error(f"User registration failed: {e}")
            flash("Registration failed. Please try again later.", "danger")
            return redirect(url_for("register"))
        finally:
            conn.close()

        if product_code_value:
            user = User(
                id=user_id,
                username=username,
                email=email,
                password_hash=password_hash,
                unlock_password_hash=unlock_password_hash,
                security_question=security_question,
                security_answer_hash=security_answer_hash,
                product_code=product_code_value,
                device_id=device_id_value,
            )
            login_user(user)
            session_id = create_face_enrollment_session(user)
            flash("Registration successful. Please complete first face enrollment.", "success")
            return redirect(url_for("face_enrollment_page", session_id=session_id))

        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template(
        "register.html",
        security_questions=get_security_questions(randomize=True),
        product_code_example=PRODUCT_CODE_EXAMPLE,
        default_product_code=DEFAULT_PRODUCT_CODE,
    )


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("profile"))

    if request.method == "POST":
        account = request.form.get("account", "").strip()
        normalized_account = account.lower()
        password = request.form.get("password", "")

        if not account or not password:
            flash("Please enter your account and password.", "danger")
            return redirect(url_for("login"))

        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT * FROM user WHERE lower(username) = ? OR lower(email) = ?",
                (normalized_account, normalized_account),
            ).fetchone()
        finally:
            conn.close()

        user = User.from_row(row)
        if not user or not user.check_password(password):
            logger.warning(f"Failed login attempt: {account}")
            flash("Incorrect account or password.", "danger")
            return redirect(url_for("login"))

        login_user(user)
        logger.info(f"User logged in: {user.username}")
        flash("Login successful.", "success")

        next_page = request.args.get("next")
        if next_page and is_safe_url(next_page):
            return redirect(next_page)
        return redirect(url_for("profile"))

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have logged out.", "info")
    return redirect(url_for("index"))


@app.route("/api/face-unlock/status")
@limiter.limit("10000 per hour", override_defaults=True)
@login_required
def face_unlock_status():
    status = get_face_unlock_status(current_user.id)
    status["unlock_url"] = url_for("unlock_pill_box")
    status["device_action"] = "wait_for_pin" if status["unlock_required"] else "retry_face"
    return jsonify(status)


@app.route("/api/push/public-key")
@login_required
def push_public_key():
    return jsonify(
        {
            "publicKey": app.config["VAPID_PUBLIC_KEY"],
            "configured": can_send_web_push(),
            "pywebpushInstalled": webpush is not None,
        }
    )


@app.route("/api/push/subscribe", methods=["POST"])
@csrf.exempt
@login_required
def push_subscribe():
    subscription = request.get_json(silent=True) or {}
    saved, error = save_push_subscription(current_user.id, subscription)
    if not saved:
        return jsonify({"error": error}), 400
    return jsonify({"ok": True, "subscriptions": count_push_subscriptions(current_user.id)})


@app.route("/api/push/test", methods=["POST"])
@csrf.exempt
@login_required
def push_test():
    status = get_face_unlock_status(current_user.id)
    status["unlock_url"] = url_for("unlock_pill_box")
    result = send_web_push_notification(current_user.id, status)
    return jsonify(result)


@app.route("/api/device/reminder-state", methods=["POST"])
@csrf.exempt
@limiter.limit("10000 per hour", override_defaults=True)
def device_reminder_state():
    payload = get_device_payload()
    user_id, error = resolve_device_request_user(payload)
    if error:
        message, status_code = error
        return jsonify({"error": message}), status_code

    state = get_device_reminder_state(user_id, payload.get("device_id"))
    return jsonify(state)


@app.route("/api/device/reminder-complete", methods=["POST"])
@csrf.exempt
@limiter.limit("10000 per hour", override_defaults=True)
def device_reminder_complete():
    payload = get_device_payload()
    user_id, error = resolve_device_request_user(payload)
    if error:
        message, status_code = error
        return jsonify({"error": message}), status_code

    reminder_key = (payload.get("reminder_key") or "").strip()
    if not reminder_key:
        return jsonify({"error": "Missing reminder_key."}), 400

    completed = complete_device_reminder_event(
        user_id,
        reminder_key,
        payload.get("device_id"),
        payload.get("taken_quantity"),
    )
    return jsonify({"ok": completed, "reminder_key": reminder_key})


@app.route("/api/device/medication-dispensed", methods=["POST"])
@csrf.exempt
@limiter.limit("10000 per hour", override_defaults=True)
def device_medication_dispensed():
    payload = get_device_payload()
    user_id, error = resolve_device_request_user(payload)
    if error:
        message, status_code = error
        return jsonify({"error": message}), status_code

    reminder_key = (payload.get("reminder_key") or "").strip()
    if not reminder_key:
        return jsonify({"error": "Missing reminder_key."}), 400

    try:
        count = int(payload.get("count", 1))
    except (TypeError, ValueError):
        count = 1

    result = record_medication_dispensed(user_id, reminder_key, payload.get("device_id"), count)
    if result is None:
        return jsonify({"error": "Reminder event not found."}), 404
    return jsonify(result)


@app.route("/api/device/reminder-timeout", methods=["POST"])
@csrf.exempt
@limiter.limit("10000 per hour", override_defaults=True)
def device_reminder_timeout():
    payload = get_device_payload()
    user_id, error = resolve_device_request_user(payload)
    if error:
        message, status_code = error
        return jsonify({"error": message}), status_code

    reminder_key = (payload.get("reminder_key") or "").strip()
    if not reminder_key:
        return jsonify({"error": "Missing reminder_key."}), 400

    missed = timeout_device_reminder_event(
        user_id,
        reminder_key,
        payload.get("device_id"),
        payload.get("taken_quantity"),
    )
    return jsonify({"ok": missed, "reminder_key": reminder_key, "status": "missed"})


@app.route("/api/face-unlock/failure", methods=["POST"])
@csrf.exempt
def report_face_unlock_failure():
    payload = get_device_payload()
    user_id, error = resolve_device_request_user(payload)
    if error:
        message, status_code = error
        return jsonify({"error": message}), status_code

    status = record_face_failure(user_id)
    if status is None:
        return jsonify({"error": "User not found."}), 404

    status["unlock_url"] = url_for("unlock_pill_box")
    if status.get("should_notify"):
        status["push"] = send_web_push_notification(user_id, status)
    else:
        status["push"] = {"sent": 0, "reason": "failure threshold not reached or already notified"}
    logger.info(
        "Face unlock failure reported: user_id=%s product_code=%s device_id=%s failed_attempts=%s unlock_required=%s push=%s",
        user_id,
        payload.get("product_code"),
        payload.get("device_id"),
        status.get("failed_attempts"),
        status.get("unlock_required"),
        status.get("push"),
    )
    return jsonify(status)


@app.route("/api/face-unlock/device-status", methods=["POST"])
@csrf.exempt
def face_unlock_device_status():
    payload = get_device_payload()
    user_id, error = resolve_device_request_user(payload)
    if error:
        message, status_code = error
        return jsonify({"error": message}), status_code

    status = get_face_unlock_status(user_id)
    if status is None:
        return jsonify({"error": "User not found."}), 404

    status["unlock_url"] = url_for("unlock_pill_box")
    status["server_time"] = utc_now_iso()
    status["device_action"] = "wait_for_pin" if status["unlock_required"] else "retry_face"
    return jsonify(status)


@app.route("/api/face-unlock/success", methods=["POST"])
@csrf.exempt
def report_face_unlock_success():
    payload = get_device_payload()
    user_id, error = resolve_device_request_user(payload)
    if error:
        message, status_code = error
        return jsonify({"error": message}), status_code

    reset_face_unlock_status(user_id)
    status = get_face_unlock_status(user_id)
    status["unlock_url"] = url_for("unlock_pill_box")
    status["device_action"] = "continue"
    return jsonify(status)


@app.route("/face-enrollment/start", methods=["POST"])
@login_required
def start_face_enrollment():
    if not current_user.product_code:
        flash("Please link your product unlock code before starting face enrollment.", "warning")
        return redirect(url_for("profile"))

    session_id = create_face_enrollment_session(current_user)
    flash("Face enrollment request sent. Keep the pill box powered on and follow the camera instructions.", "success")
    return redirect(url_for("face_enrollment_page", session_id=session_id))


@app.route("/face-enrollment/<int:session_id>")
@login_required
def face_enrollment_page(session_id):
    row = get_face_enrollment_session(session_id, current_user.id)
    if row is None:
        flash("Face enrollment session not found.", "danger")
        return redirect(url_for("profile"))

    return render_template(
        "face_enrollment.html",
        enrollment=serialize_face_enrollment_session(row),
    )


@app.route("/api/face-enrollment/<int:session_id>/status")
@login_required
def face_enrollment_status(session_id):
    row = get_face_enrollment_session(session_id, current_user.id)
    if row is None:
        return jsonify({"error": "Face enrollment session not found."}), 404
    return jsonify(serialize_face_enrollment_session(row))


@app.route("/face-enrollment/<int:session_id>/photo")
@login_required
def face_enrollment_photo(session_id):
    row = get_face_enrollment_session(session_id, current_user.id)
    if row is None or not row["photo_data"]:
        return jsonify({"error": "Face enrollment photo not found."}), 404

    return send_file(
        BytesIO(row["photo_data"]),
        mimetype=row["photo_mime"] or "image/jpeg",
        download_name=f"face-enrollment-{session_id}.jpg",
    )


@app.route("/api/face-enrollment/device-command", methods=["POST"])
@csrf.exempt
def face_enrollment_device_command():
    payload = get_device_payload()
    user_id, error = resolve_device_request_user(payload)
    if error:
        message, status_code = error
        return jsonify({"error": message}), status_code

    row = get_active_face_enrollment_for_user(user_id)
    if row is None:
        return jsonify({"command": "idle", "server_time": utc_now_iso()})

    mark_face_enrollment_started(row, payload.get("device_id"))
    return jsonify(
        {
            "command": "enroll",
            "session_id": str(row["id"]),
            "person_name": row["person_name"],
            "requested_samples": row["requested_samples"],
            "expires_at": row["expires_at"],
            "server_time": utc_now_iso(),
        }
    )


@app.route("/api/face-enrollment/device-result", methods=["POST"])
@csrf.exempt
def face_enrollment_device_result():
    payload = get_device_payload()
    user_id, error = resolve_device_request_user(payload)
    if error:
        message, status_code = error
        return jsonify({"error": message}), status_code

    try:
        session_id = int(payload.get("session_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "session_id is required."}), 400

    status = (payload.get("status") or "").strip().lower()
    if status not in ("started", "completed", "failed", "expired"):
        return jsonify({"error": "Invalid enrollment status."}), 400

    captured_samples = payload.get("captured_samples") or 0
    try:
        captured_samples = max(0, int(captured_samples))
    except (TypeError, ValueError):
        captured_samples = 0

    row = get_face_enrollment_session(session_id, user_id)
    if row is None:
        return jsonify({"error": "Face enrollment session not found."}), 404

    update_face_enrollment_result(
        session_id=session_id,
        user_id=user_id,
        status=status,
        captured_samples=captured_samples,
        message=(payload.get("message") or "").strip() or None,
        device_id=payload.get("device_id"),
    )
    updated = get_face_enrollment_session(session_id, user_id)
    return jsonify(serialize_face_enrollment_session(updated))


@app.route("/api/face-enrollment/device-photo/<int:session_id>", methods=["POST"])
@csrf.exempt
def face_enrollment_device_photo(session_id):
    payload = get_device_payload()
    user_id, error = resolve_device_request_user(payload)
    if error:
        message, status_code = error
        return jsonify({"error": message}), status_code

    row = get_face_enrollment_session(session_id, user_id)
    if row is None:
        return jsonify({"error": "Face enrollment session not found."}), 404

    photo_data = request.get_data()
    if not photo_data:
        return jsonify({"error": "Photo body is empty."}), 400
    if len(photo_data) > app.config["FACE_ENROLLMENT_MAX_PHOTO_BYTES"]:
        return jsonify({"error": "Photo is too large."}), 413

    photo_mime = request.headers.get("Content-Type") or "image/jpeg"
    save_face_enrollment_photo(session_id, user_id, photo_data, photo_mime, payload.get("device_id"))
    updated = get_face_enrollment_session(session_id, user_id)
    return jsonify(serialize_face_enrollment_session(updated))


@app.route("/unlock", methods=["GET", "POST"])
@login_required
@limiter.limit("10 per minute", methods=["POST"])
def unlock_pill_box():
    if request.method == "POST":
        unlock_password = request.form.get("unlock_password", "")
        if not current_user.check_unlock_password(unlock_password):
            flash("Incorrect unlock password.", "danger")
            return redirect(url_for("unlock_pill_box"))

        reset_face_unlock_status(current_user.id)
        current_user.face_failed_attempts = 0
        current_user.unlock_required = False
        flash("Pill box unlock confirmed. Face recognition alert has been cleared.", "success")
        return redirect(url_for("profile"))

    face_status = get_face_unlock_status(current_user.id)
    return render_template("unlock.html", face_status=face_status)


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        form_type = request.form.get("form_type")

        if form_type == "profile":
            age = request.form.get("age", "").strip()
            health_goal = request.form.get("health_goal", "").strip()
            login_password = request.form.get("login_password", "")
            confirm_login_password = request.form.get("confirm_login_password", "")
            unlock_password = request.form.get("unlock_password", "")
            confirm_unlock_password = request.form.get("confirm_unlock_password", "")
            security_question = request.form.get("security_question", "").strip()
            security_answer = request.form.get("security_answer", "")
            product_code = request.form.get("product_code", "")
            device_id = request.form.get("device_id", "")
            login_password_updated = False
            unlock_password_updated = False

            valid, age_value = validate_age(age)
            if not valid:
                flash(age_value, "danger")
                return redirect(url_for("profile"))

            password_hash = current_user.password_hash
            if login_password:
                valid, msg = validate_password(login_password)
                if not valid:
                    flash(msg, "danger")
                    return redirect(url_for("profile"))
                if confirm_login_password and login_password != confirm_login_password:
                    flash("The two login passwords do not match.", "danger")
                    return redirect(url_for("profile"))
                password_hash = generate_password_hash(login_password)
                login_password_updated = True
            elif confirm_login_password:
                flash("Please enter the new login password first.", "danger")
                return redirect(url_for("profile"))

            valid, msg = validate_security_question(security_question)
            if not valid:
                flash(msg, "danger")
                return redirect(url_for("profile"))

            security_answer_hash = current_user.security_answer_hash
            if security_answer.strip():
                valid, security_answer_value = validate_security_answer(security_answer)
                if not valid:
                    flash(security_answer_value, "danger")
                    return redirect(url_for("profile"))
                security_answer_hash = generate_password_hash(security_answer_value)
            elif security_question != current_user.security_question:
                flash("Please enter a new security answer when changing the security question.", "danger")
                return redirect(url_for("profile"))

            unlock_password_hash = current_user.unlock_password_hash
            if unlock_password:
                valid, msg = validate_unlock_password(unlock_password)
                if not valid:
                    flash(msg, "danger")
                    return redirect(url_for("profile"))
                if confirm_unlock_password and unlock_password != confirm_unlock_password:
                    flash("The two pill box unlock passwords do not match.", "danger")
                    return redirect(url_for("profile"))
                unlock_password_hash = generate_password_hash(unlock_password)
                unlock_password_updated = True
            elif confirm_unlock_password:
                flash("Please enter the new pill box unlock password first.", "danger")
                return redirect(url_for("profile"))

            valid, product_code_value = validate_product_code(product_code)
            if not valid:
                flash(product_code_value, "danger")
                return redirect(url_for("profile"))
            product_code_changed = bool(product_code_value) and product_code_value != current_user.product_code

            valid, device_id_value = validate_device_id(device_id)
            if not valid:
                flash(device_id_value, "danger")
                return redirect(url_for("profile"))

            health_goal_value = health_goal or None
            conn = get_db_connection()
            try:
                conn.execute(
                    """
                    UPDATE user
                    SET password_hash = ?,
                        age = ?,
                        health_goal = ?,
                        unlock_password_hash = ?,
                        security_question = ?,
                        security_answer_hash = ?,
                        product_code = ?,
                        device_id = ?
                    WHERE id = ?
                    """,
                    (
                        password_hash,
                        age_value,
                        health_goal_value,
                        unlock_password_hash,
                        security_question,
                        security_answer_hash,
                        product_code_value,
                        device_id_value,
                        current_user.id,
                    ),
                )
                conn.commit()
                logger.info(f"User profile updated: {current_user.username}")
            except sqlite3.IntegrityError:
                flash("This product unlock code or device ID is already linked to another account.", "danger")
                return redirect(url_for("profile"))
            except sqlite3.DatabaseError as e:
                logger.error(f"Failed to update user profile: {e}")
                flash("Update failed. Please try again later.", "danger")
                return redirect(url_for("profile"))
            finally:
                conn.close()

            current_user.password_hash = password_hash
            current_user.age = age_value
            current_user.health_goal = health_goal_value
            current_user.unlock_password_hash = unlock_password_hash
            current_user.security_question = security_question
            current_user.security_answer_hash = security_answer_hash
            current_user.product_code = product_code_value
            current_user.device_id = device_id_value
            success_message = "Profile updated successfully."
            if login_password_updated:
                success_message += " Login password updated."
            if unlock_password_updated:
                success_message += " Pill box unlock password updated."
            if product_code_changed:
                session_id = create_face_enrollment_session(current_user)
                flash("Product linked. Please complete first face enrollment before normal medication reminders.", "success")
                return redirect(url_for("face_enrollment_page", session_id=session_id))
            flash(success_message, "success")
            return redirect(url_for("profile"))

        if form_type == "schedule":
            supplement_name = request.form.get("supplement_name", "").strip()
            take_time = request.form.get("take_time", "").strip()
            time_window = request.form.get("time_window", "").strip()
            dose_quantity = request.form.get("dose_quantity", "").strip()
            note = request.form.get("note", "").strip()

            if supplement_name not in SUPPLEMENT_OPTIONS:
                flash("Please select a valid supplement name.", "danger")
                return redirect(url_for("profile"))
            if take_time not in TIME_OPTIONS:
                flash("Please select a valid intake time.", "danger")
                return redirect(url_for("profile"))
            try:
                time_window_value = int(time_window)
            except ValueError:
                flash("Please select a valid allowed time window.", "danger")
                return redirect(url_for("profile"))
            if time_window_value not in WINDOW_OPTIONS:
                flash("Please select a valid allowed time window.", "danger")
                return redirect(url_for("profile"))
            valid, dose_quantity_value = validate_dose_quantity(dose_quantity)
            if not valid:
                flash(dose_quantity_value, "danger")
                return redirect(url_for("profile"))

            conn = get_db_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO supplement_schedule
                    (user_id, supplement_name, take_time, time_window, dose_quantity, note)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (current_user.id, supplement_name, take_time, time_window_value, dose_quantity_value, note or None),
                )
                conn.commit()
                logger.info(f"User {current_user.username} added schedule: {supplement_name} {take_time}")
            except sqlite3.DatabaseError as e:
                logger.error(f"Failed to add supplement schedule: {e}")
                flash("Failed to add schedule. Please try again later.", "danger")
                return redirect(url_for("profile"))
            finally:
                conn.close()

            flash("Supplement schedule added successfully.", "success")
            return redirect(url_for("profile"))

    schedules = get_user_schedules(current_user.id)
    latest_face_enrollment = get_latest_face_enrollment_for_user(current_user.id)
    return render_template(
        "profile.html",
        supplement_options=SUPPLEMENT_OPTIONS,
        time_options=TIME_OPTIONS,
        window_options=WINDOW_OPTIONS,
        dose_quantity_options=DOSE_QUANTITY_OPTIONS,
        schedules=schedules,
        security_questions=get_security_questions(),
        security_question_text=SECURITY_QUESTION_LABELS.get(current_user.security_question),
        product_code_example=PRODUCT_CODE_EXAMPLE,
        default_product_code=DEFAULT_PRODUCT_CODE,
        default_device_id=DEFAULT_DEVICE_ID,
        latest_face_enrollment=serialize_face_enrollment_session(latest_face_enrollment) if latest_face_enrollment else None,
    )


@app.route("/schedule/delete/<int:schedule_id>", methods=["POST"])
@login_required
def delete_schedule(schedule_id):
    conn = get_db_connection()
    try:
        conn.execute(
            "DELETE FROM supplement_schedule WHERE id = ? AND user_id = ?",
            (schedule_id, current_user.id),
        )
        conn.commit()
        logger.info(f"User {current_user.username} deleted schedule: {schedule_id}")
    except sqlite3.DatabaseError as e:
        logger.error(f"Failed to delete supplement schedule: {e}")
        flash("Delete failed. Please try again later.", "danger")
        return redirect(url_for("profile"))
    finally:
        conn.close()

    flash("Schedule deleted.", "info")
    return redirect(url_for("profile"))


@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404


@app.errorhandler(CSRFError)
def csrf_error(error):
    logger.warning(f"CSRF validation failed on {request.path}: {error.description}")
    message = "Your form session expired. Please refresh the page and try again."
    if request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json":
        return jsonify({"error": message}), 400

    flash(message, "warning")
    if request.referrer and is_safe_url(request.referrer):
        return redirect(request.referrer)
    return redirect(url_for("login"))


@app.errorhandler(403)
def forbidden_error(error):
    return render_template('403.html'), 403


@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return render_template('500.html'), 500


if __name__ == "__main__":
    app.run(debug=True)
