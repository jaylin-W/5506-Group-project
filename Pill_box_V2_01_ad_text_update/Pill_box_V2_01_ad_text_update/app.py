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

# ===== 基础配置 =====
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
    "鱼油",
    "维生素A",
    "维生素B族",
    "维生素C",
    "维生素D",
    "维生素E",
    "钙片",
    "铁片",
    "锌片",
    "镁片",
    "叶酸",
    "益生菌",
    "胶原蛋白",
    "辅酶Q10",
    "褪黑素",
    "蛋白粉",
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
    "home_hero_title": "智能保健品药盒，让每日健康管理更简单",
    "home_hero_subtitle": (
        "本系统用于展示一款面向家庭、学生、上班族和老年用户的智能保健品药盒。"
        "它可以帮助用户记录补充计划、提醒按时服用、减少漏服和重复服用的情况。"
    ),
    "home_feature_1_title": "智能提醒",
    "home_feature_1_body": "根据用户设置的保健品服用时间，通过页面、设备或移动端提醒用户按时服用。",
    "home_feature_2_title": "分类存储",
    "home_feature_2_body": "药盒可按早、中、晚或不同保健品类型进行分区管理，方便用户快速查找。",
    "home_feature_3_title": "健康档案",
    "home_feature_3_body": "用户可以在个人页面维护年龄、健康目标等信息，为后续个性化管理提供基础。",
    "promo_1_badge": "限时折扣",
    "promo_1_title": "维生素C 活力补给季",
    "promo_1_subtitle": "果味营养专区 · 低至 7 折",
    "promo_1_desc": "适合日常营养补充与忙碌人群活力支持，页面展示为广告卡片，不含跳转按钮。",
    "promo_2_badge": "会员专享",
    "promo_2_title": "深海鱼油 精选优惠",
    "promo_2_subtitle": "高纯度鱼油软胶囊 · 第二件半价",
    "promo_2_desc": "为关注日常心脑健康的用户准备的活动展示卡片，强调高端与清爽海洋感。",
    "promo_3_badge": "组合优惠",
    "promo_3_title": "益生菌舒护组合",
    "promo_3_subtitle": "肠道轻养计划 · 满 99 减 20",
    "promo_3_desc": "适合搭配轻营养、清爽饮食场景展示，版面以柔和绿色为主，更有健康氛围。",
    "promo_4_badge": "新客推荐",
    "promo_4_title": "复合维生素 每日营养盒",
    "promo_4_subtitle": "多彩营养组合 · 新客立减 15 元",
    "promo_4_desc": "适合学生、上班族与家庭用户的基础补充展示卡片，整体视觉更加明亮柔和。",

    "about_intro_title": "关于智能保健品药盒",
    "about_intro_body": (
        "智能保健品药盒的核心目标是帮助用户建立稳定、清晰、可持续的健康补充习惯。"
        "传统药盒只能提供简单收纳功能，而智能药盒可以结合提醒、记录和账户系统，"
        "让用户更容易掌握自己的保健品服用情况。"
    ),
}


def get_db_connection():
    try:
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.DatabaseError as e:
        logger.error(f"数据库连接失败: {e}")
        raise


def validate_username(username):
    if not username or len(username) < 3 or len(username) > 20:
        return False, "用户名长度需要 3-20 位字符。"
    if not re.match(r"^[a-zA-Z0-9_-]+$", username):
        return False, "用户名只能包含字母、数字、下划线和连字符。"
    return True, None


def validate_email_format(email):
    try:
        valid = validate_email(email.strip().lower(), check_deliverability=False)
        return True, valid.email
    except EmailNotValidError as e:
        return False, str(e)


def validate_password(password):
    if len(password) < 6:
        return False, "密码长度至少需要 6 位。"
    return True, None


def validate_age(age_str):
    if not age_str or age_str.strip() == "":
        return True, None
    try:
        age = int(age_str)
        if age < 0 or age > 150:
            return False, "年龄必须是 0-150 之间的数字。"
        return True, age
    except ValueError:
        return False, "年龄必须是数字。"


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
login_manager.login_message = "请先登录后再访问个人页面。"
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
    """从数据库内容块中读取 4 个广告卡片文字，并和广告背景图组合。"""
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
            logger.info(f"Host 管理员登录成功: {request.remote_addr}")
            flash("编辑页面登录成功。", "success")
            return redirect(url_for("host"))
        logger.warning(f"Host 管理员登录失败: {request.remote_addr}")
        flash("管理密码错误。", "danger")
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
            logger.info("编辑页面内容已更新")
            flash("固定板块内容已保存，主页和关于页面已更新。", "success")
        except sqlite3.DatabaseError as e:
            logger.error(f"保存编辑内容失败: {e}")
            flash("保存失败，请稍后重试。", "danger")
        finally:
            conn.close()
        return redirect(url_for("host"))

    blocks = get_content_blocks()
    return render_template("host.html", blocks=blocks, editor_path=app.config["EDITOR_ROUTE"])


app.add_url_rule(f"/{app.config['EDITOR_ROUTE']}", endpoint="host", view_func=host, methods=["GET", "POST"])


@app.route(f"/{app.config['EDITOR_ROUTE']}/logout")
def host_logout():
    session.pop("host_logged_in", None)
    flash("已退出编辑页面。", "info")
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
            flash(f"邮箱格式无效：{result}", "danger")
            return redirect(url_for("register"))
        email = result

        if not password:
            flash("请填写密码。", "danger")
            return redirect(url_for("register"))

        valid, msg = validate_password(password)
        if not valid:
            flash(msg, "danger")
            return redirect(url_for("register"))

        if password != confirm_password:
            flash("两次输入的密码不一致。", "danger")
            return redirect(url_for("register"))

        conn = get_db_connection()
        existing_user = conn.execute(
            "SELECT * FROM user WHERE username = ? OR email = ?",
            (username, email),
        ).fetchone()

        if existing_user:
            conn.close()
            flash("用户名或邮箱已经被注册。", "danger")
            return redirect(url_for("register"))

        password_hash = generate_password_hash(password)
        try:
            conn.execute(
                "INSERT INTO user (username, email, password_hash) VALUES (?, ?, ?)",
                (username, email, password_hash),
            )
            conn.commit()
            logger.info(f"新用户注册: {username}")
        except sqlite3.DatabaseError as e:
            logger.error(f"用户注册失败: {e}")
            flash("注册失败，请稍后重试。", "danger")
            return redirect(url_for("register"))
        finally:
            conn.close()

        flash("注册成功，请登录。", "success")
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
            flash("请填写账号和密码。", "danger")
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
            logger.warning(f"登录失败尝试: {account}")
            flash("账号或密码错误。", "danger")
            return redirect(url_for("login"))

        login_user(user)
        logger.info(f"用户登录: {user.username}")
        flash("登录成功。", "success")

        next_page = request.args.get("next")
        if next_page and is_safe_url(next_page):
            return redirect(next_page)
        return redirect(url_for("profile"))

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("你已经退出登录。", "info")
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
                logger.info(f"用户资料已更新: {current_user.username}")
            except sqlite3.DatabaseError as e:
                logger.error(f"更新用户资料失败: {e}")
                flash("更新失败，请稍后重试。", "danger")
                return redirect(url_for("profile"))
            finally:
                conn.close()

            current_user.age = age_value
            current_user.health_goal = health_goal_value
            flash("个人资料已更新。", "success")
            return redirect(url_for("profile"))

        if form_type == "schedule":
            supplement_name = request.form.get("supplement_name", "").strip()
            take_time = request.form.get("take_time", "").strip()
            time_window = request.form.get("time_window", "").strip()
            note = request.form.get("note", "").strip()

            if supplement_name not in SUPPLEMENT_OPTIONS:
                flash("请选择有效的保健品名称。", "danger")
                return redirect(url_for("profile"))
            if take_time not in TIME_OPTIONS:
                flash("请选择有效的服用时间。", "danger")
                return redirect(url_for("profile"))
            try:
                time_window_value = int(time_window)
            except ValueError:
                flash("请选择有效的允许误差区间。", "danger")
                return redirect(url_for("profile"))
            if time_window_value not in WINDOW_OPTIONS:
                flash("请选择有效的允许误差区间。", "danger")
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
                logger.info(f"用户 {current_user.username} 添加服用计划: {supplement_name} {take_time}")
            except sqlite3.DatabaseError as e:
                logger.error(f"添加服用计划失败: {e}")
                flash("添加计划失败，请稍后重试。", "danger")
                return redirect(url_for("profile"))
            finally:
                conn.close()

            flash("保健品服用计划已添加。", "success")
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
        logger.info(f"用户 {current_user.username} 删除服用计划: {schedule_id}")
    except sqlite3.DatabaseError as e:
        logger.error(f"删除服用计划失败: {e}")
        flash("删除失败，请稍后重试。", "danger")
        return redirect(url_for("profile"))
    finally:
        conn.close()

    flash("服用计划已删除。", "info")
    return redirect(url_for("profile"))


@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404


@app.errorhandler(403)
def forbidden_error(error):
    return render_template('403.html'), 403


@app.errorhandler(500)
def internal_error(error):
    logger.error(f"服务器内部错误: {error}")
    return render_template('500.html'), 500


if __name__ == "__main__":
    app.run(debug=True)
