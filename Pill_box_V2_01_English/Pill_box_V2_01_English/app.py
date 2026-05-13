from flask import Flask, render_template, redirect, url_for, flash, request, session, jsonify, send_from_directory
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    login_required,
    current_user,
)
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
from email_validator import validate_email, EmailNotValidError
from pathlib import Path
from datetime import datetime, timezone
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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

csrf = CSRFProtect(app)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
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

PRODUCT_CODE_EXAMPLE = "5506xxx"
DEFAULT_PRODUCT_CODE = "5506123"

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
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES user(id)
        )
        """
    )
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
        SELECT id, supplement_name, take_time, time_window, note, created_at
        FROM supplement_schedule
        WHERE user_id = ?
        ORDER BY take_time ASC, id DESC
        """,
        (user_id,),
    ).fetchall()
    conn.close()
    return rows


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
    try:
        row = conn.execute(
            "SELECT face_failed_attempts, unlock_required FROM user WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None

        failed_attempts = (row["face_failed_attempts"] or 0) + 1
        unlock_required = 1 if failed_attempts >= app.config["FACE_FAILURE_THRESHOLD"] else row["unlock_required"]
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

    return get_face_unlock_status(user_id)


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

    conn = get_db_connection()
    try:
        if user_id:
            row = conn.execute("SELECT id FROM user WHERE id = ?", (user_id,)).fetchone()
        elif username:
            row = conn.execute("SELECT id FROM user WHERE username = ?", (username,)).fetchone()
        else:
            row = None
    finally:
        conn.close()

    return row["id"] if row else None


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


def can_send_web_push():
    return bool(webpush and app.config["VAPID_PUBLIC_KEY"] and app.config["VAPID_PRIVATE_KEY"])


def send_web_push_notification(user_id, status):
    if not can_send_web_push():
        logger.info("Web Push skipped: pywebpush or VAPID keys are not configured.")
        return {"sent": 0, "configured": False}

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

    for row in get_push_subscriptions(user_id):
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

    return {"sent": sent_count, "configured": True}


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
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        unlock_password = request.form.get("unlock_password", "")
        confirm_unlock_password = request.form.get("confirm_unlock_password", "")
        security_question = request.form.get("security_question", "").strip()
        security_answer = request.form.get("security_answer", "")

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

        conn = get_db_connection()
        existing_user = conn.execute(
            "SELECT * FROM user WHERE username = ? OR email = ?",
            (username, email),
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
                (username, email, password_hash, unlock_password_hash, security_question, security_answer_hash)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (username, email, password_hash, unlock_password_hash, security_question, security_answer_hash),
            )
            conn.commit()
            logger.info(f"New user registered: {username}")
        except sqlite3.DatabaseError as e:
            logger.error(f"User registration failed: {e}")
            flash("Registration failed. Please try again later.", "danger")
            return redirect(url_for("register"))
        finally:
            conn.close()

        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html", security_questions=get_security_questions(randomize=True))


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("profile"))

    if request.method == "POST":
        account = request.form.get("account", "").strip()
        password = request.form.get("password", "")

        if not account or not password:
            flash("Please enter your account and password.", "danger")
            return redirect(url_for("login"))

        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT * FROM user WHERE username = ? OR email = ?",
                (account, account.lower()),
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
@login_required
def face_unlock_status():
    status = get_face_unlock_status(current_user.id)
    status["unlock_url"] = url_for("unlock_pill_box")
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
    return jsonify({"ok": True})


@app.route("/api/push/test", methods=["POST"])
@csrf.exempt
@login_required
def push_test():
    status = get_face_unlock_status(current_user.id)
    status["unlock_url"] = url_for("unlock_pill_box")
    result = send_web_push_notification(current_user.id, status)
    return jsonify(result)


@app.route("/api/face-unlock/failure", methods=["POST"])
@csrf.exempt
def report_face_unlock_failure():
    payload = request.get_json(silent=True) or {}
    configured_token = app.config["DEVICE_API_TOKEN"]
    provided_token = request.headers.get("X-Device-Token") or payload.get("device_token")

    if configured_token:
        if provided_token != configured_token:
            return jsonify({"error": "Invalid device token."}), 403
        user_id = find_user_id_from_payload(payload)
        if user_id is None and current_user.is_authenticated:
            user_id = current_user.id
    elif current_user.is_authenticated:
        user_id = current_user.id
    else:
        return jsonify({"error": "Login required or configure DEVICE_API_TOKEN for the pill box device."}), 401

    if user_id is None:
        return jsonify({"error": "User not found. Send username or user_id with the device request."}), 404

    status = record_face_failure(user_id)
    if status is None:
        return jsonify({"error": "User not found."}), 404

    status["unlock_url"] = url_for("unlock_pill_box")
    if status["unlock_required"]:
        status["push"] = send_web_push_notification(user_id, status)
    return jsonify(status)


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
                        product_code = ?
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
                        current_user.id,
                    ),
                )
                conn.commit()
                logger.info(f"User profile updated: {current_user.username}")
            except sqlite3.IntegrityError:
                flash("This product unlock code is already linked to another account.", "danger")
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
            success_message = "Profile updated successfully."
            if login_password_updated:
                success_message += " Login password updated."
            if unlock_password_updated:
                success_message += " Pill box unlock password updated."
            flash(success_message, "success")
            return redirect(url_for("profile"))

        if form_type == "schedule":
            supplement_name = request.form.get("supplement_name", "").strip()
            take_time = request.form.get("take_time", "").strip()
            time_window = request.form.get("time_window", "").strip()
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

            conn = get_db_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO supplement_schedule
                    (user_id, supplement_name, take_time, time_window, note)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (current_user.id, supplement_name, take_time, time_window_value, note or None),
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
    return render_template(
        "profile.html",
        supplement_options=SUPPLEMENT_OPTIONS,
        time_options=TIME_OPTIONS,
        window_options=WINDOW_OPTIONS,
        schedules=schedules,
        security_questions=get_security_questions(),
        security_question_text=SECURITY_QUESTION_LABELS.get(current_user.security_question),
        product_code_example=PRODUCT_CODE_EXAMPLE,
        default_product_code=DEFAULT_PRODUCT_CODE,
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


@app.errorhandler(403)
def forbidden_error(error):
    return render_template('403.html'), 403


@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return render_template('500.html'), 500


if __name__ == "__main__":
    app.run(debug=True)
