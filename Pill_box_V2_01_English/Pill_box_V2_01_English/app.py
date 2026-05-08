from flask import Flask, render_template, redirect, url_for, flash, request, session
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
import sqlite3
import os
import re
import logging
from urllib.parse import urlparse, urljoin

from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

# ===== Basic configuration =====
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
app.config["HOST_PASSWORD"] = os.environ.get("HOST_PASSWORD", "admin123")
app.config["EDITOR_ROUTE"] = os.environ.get("EDITOR_ROUTE", "pillbox-v2-editor-201")
app.config["PROJECT_NAME"] = "Pill box V2"
app.config["PROJECT_VERSION"] = "2.01"

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

INSTANCE_PATH = Path(app.instance_path)
INSTANCE_PATH.mkdir(parents=True, exist_ok=True)
DATABASE_ENV = os.environ.get("DATABASE_PATH")
DATABASE = Path(DATABASE_ENV) if DATABASE_ENV else INSTANCE_PATH / "app.db"

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


def init_db():
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            age INTEGER,
            health_goal TEXT
        )
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
    for key, value in DEFAULT_CONTENT_BLOCKS.items():
        conn.execute(
            "INSERT OR IGNORE INTO content_block (block_key, block_value) VALUES (?, ?)",
            (key, value),
        )
    conn.commit()
    conn.close()


class User(UserMixin):
    def __init__(self, id, username, email, password_hash, age=None, health_goal=None):
        self.id = id
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.age = age
        self.health_goal = health_goal

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
        )

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


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
        try:
            conn.execute(
                "INSERT INTO user (username, email, password_hash) VALUES (?, ?, ?)",
                (username, email, password_hash),
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

    return render_template("register.html")


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


@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        form_type = request.form.get("form_type")

        if form_type == "profile":
            age = request.form.get("age", "").strip()
            health_goal = request.form.get("health_goal", "").strip()
            valid, age_value = validate_age(age)
            if not valid:
                flash(age_value, "danger")
                return redirect(url_for("profile"))
            health_goal_value = health_goal or None
            conn = get_db_connection()
            try:
                conn.execute(
                    "UPDATE user SET age = ?, health_goal = ? WHERE id = ?",
                    (age_value, health_goal_value, current_user.id),
                )
                conn.commit()
                logger.info(f"User profile updated: {current_user.username}")
            except sqlite3.DatabaseError as e:
                logger.error(f"Failed to update user profile: {e}")
                flash("Update failed. Please try again later.", "danger")
                return redirect(url_for("profile"))
            finally:
                conn.close()

            current_user.age = age_value
            current_user.health_goal = health_goal_value
            flash("Profile updated successfully.", "success")
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
