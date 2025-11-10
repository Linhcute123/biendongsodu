import os
import json
import sqlite3
import threading
import time
from datetime import datetime

import requests
from flask import (
    Flask,
    render_template_string,
    request,
    redirect,
    url_for,
    session,
    flash,
    Response,
)

# =======================================
# CẤU HÌNH
# =======================================
APP_TITLE = "Balance Watcher Pro"

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
SECRET_KEY = os.getenv("SECRET_KEY", ADMIN_PASSWORD)

DATA_DIR = "/data" if os.path.isdir("/data") else "."
DB_PATH = os.path.join(DATA_DIR, "balance_watcher.db")

app = Flask(__name__)
app.secret_key = SECRET_KEY

db_lock = threading.Lock()
watcher_thread = None
watcher_running = False

# Các từ khóa có thể xuất hiện trong JSON nhiều web khác nhau
BALANCE_KEYWORDS = [
    "balance",
    "so_du",
    "sodu",
    "sodư",
    "amount",
    "money",
    "money_balance",
    "wallet",
    "wallet_balance",
    "available",
    "available_balance",
    "current_balance",
    "remain",
    "remaining",
    "remain_balance",
    "remaining_balance",
    "credit",
    "fund",
    "funds",
]


# =======================================
# DB
# =======================================
def init_db():
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY,
                poll_interval INTEGER DEFAULT 30,
                threshold REAL DEFAULT 100000
            )
            """
        )

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS sites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                api_url TEXT NOT NULL,
                last_balance REAL,
                chat_id TEXT NOT NULL,
                bot_token TEXT NOT NULL
            )
            """
        )

        c.execute("SELECT id FROM settings WHERE id=1")
        if not c.fetchone():
            c.execute(
                "INSERT INTO settings (id, poll_interval, threshold) VALUES (1, 30, 100000)"
            )

        conn.commit()


def get_settings():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT poll_interval, threshold FROM settings WHERE id=1")
        row = c.fetchone()
        if not row:
            return 30, 100000
        return int(row[0]), float(row[1])


def update_settings(poll_interval: int, threshold: float):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE settings SET poll_interval=?, threshold=? WHERE id=1",
            (poll_interval, threshold),
        )
        conn.commit()


def get_all_sites():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, name, api_url, last_balance, chat_id, bot_token FROM sites"
        )
        return c.fetchall()


def get_site(site_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, name, api_url, last_balance, chat_id, bot_token "
            "FROM sites WHERE id=?",
            (site_id,),
        )
        return c.fetchone()


def upsert_site(site_id, name, api_url, chat_id, bot_token):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        if site_id:
            c.execute(
                """
                UPDATE sites
                SET name=?, api_url=?, chat_id=?, bot_token=?
                WHERE id=?
                """,
                (name, api_url, chat_id, bot_token, site_id),
            )
        else:
            c.execute(
                """
                INSERT INTO sites (name, api_url, chat_id, bot_token)
                VALUES (?,?,?,?)
                """,
                (name, api_url, chat_id, bot_token),
            )
        conn.commit()


def delete_site(site_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("DELETE FROM sites WHERE id=?", (site_id,))
        conn.commit()


def update_last_balance(site_id: int, balance: float):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE sites SET last_balance=? WHERE id=?", (balance, site_id))
        conn.commit()


# =======================================
# TELEGRAM + FORMAT
# =======================================
def send_telegram_message(msg: str, chat_id: str, bot_token: str):
    if not chat_id or not bot_token:
        return
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        requests.post(
            url,
            data={
                "chat_id": chat_id,
                "text": msg,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
    except Exception as e:
        print("Telegram error:", e)


def format_ts():
    # HH:MM DD/MM/YYYY
    return datetime.now().strftime("%H:%M %d/%m/%Y")


def fmt_money(v: float) -> str:
    return f"{v:,.0f}đ"


# =======================================
# TÌM SỐ DƯ TRONG JSON TỔNG QUÁT
# =======================================
def try_parse_float(x):
    try:
        return float(x)
    except Exception:
        return None


def find_balance_in_obj(obj):
    """
    Quét đệ quy toàn bộ JSON:
    - Nếu key chứa từ khóa BALANCE_KEYWORDS và value là số/chuỗi số -> trả về.
    - Nếu không, tiếp tục đi sâu vào dict/list.
    """
    # dict
    if isinstance(obj, dict):
        # Ưu tiên key match trực tiếp
        for k, v in obj.items():
            key_lower = str(k).lower()
            if any(kw in key_lower for kw in BALANCE_KEYWORDS):
                fv = try_parse_float(v)
                if fv is not None:
                    return fv

        # Nếu chưa thấy, duyệt sâu
        for v in obj.values():
            found = find_balance_in_obj(v)
            if found is not None:
                return found

    # list
    elif isinstance(obj, list):
        for item in obj:
            found = find_balance_in_obj(item)
            if found is not None:
                return found

    # cái khác bỏ qua
    return None


def get_balance_from_api(url: str):
    """
    Hỗ trợ nhiều dạng JSON thực tế:
    - { "balance": 12345 }
    - { "data": { "so_du": "12345" } }
    - { "wallet": { "available_balance": 12345 } }
    - { "money": { "current": 12345 } }
    - { "result": { "funds": { "remain": "12345.0" } } }
    v.v...
    Chỉ cần ở đâu đó có key chứa từ khóa trong BALANCE_KEYWORDS.
    """
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        balance = find_balance_in_obj(data)
        if balance is None:
            print("Không tìm được trường số dư hợp lệ trong JSON:", data)
            return None
        return float(balance)
    except Exception as e:
        print("Lỗi lấy số dư:", e)
        return None


# =======================================
# WORKER THEO DÕI
# =======================================
def watcher_loop():
    global watcher_running
    print("[Watcher] Started")
    watcher_running = True

    while watcher_running:
        poll_interval, threshold = get_settings()
        sites = get_all_sites()

        for site in sites:
            site_id, name, api_url, last_balance, chat_id, bot_token = site

            balance = get_balance_from_api(api_url)
            if balance is None:
                continue

            # Biến động tăng / giảm
            if last_balance is not None:
                diff = balance - last_balance

                # Thanh toán / trừ tiền
                if diff < -1e-6:
                    msg = (
                        f"🔻 *THANH TOÁN TẠI {name}*\n\n"
                        f"💳 Nội dung: Thanh toán / trừ số dư\n"
                        f"➖ Biến động: *-{fmt_money(abs(diff))}*\n"
                        f"💰 Số dư cuối: *{fmt_money(balance)}*\n"
                        f"🕒 {format_ts()}"
                    )
                    send_telegram_message(msg, chat_id, bot_token)

                # Nhận tiền / nạp tiền
                elif diff > 1e-6:
                    msg = (
                        f"💰 *NHẬN TIỀN TẠI {name}*\n\n"
                        f"📥 Nội dung: Nạp tiền vào tài khoản\n"
                        f"➕ Biến động: *+{fmt_money(diff)}*\n"
                        f"💰 Số dư cuối: *{fmt_money(balance)}*\n"
                        f"🕒 {format_ts()}"
                    )
                    send_telegram_message(msg, chat_id, bot_token)

            # Cảnh báo số dư thấp: chỉ khi vừa rơi từ trên ngưỡng xuống dưới
            if balance < threshold and (last_balance is None or last_balance >= threshold):
                warn = (
                    f"⚠️ *CẢNH BÁO SỐ DƯ THẤP - {name}*\n\n"
                    f"🔥 Số dư hiện tại: *{fmt_money(balance)}*\n"
                    f"❗ Ngưỡng cảnh báo chung: *{fmt_money(threshold)}*\n"
                    f"👉 Vui lòng nạp thêm để tránh gián đoạn dịch vụ.\n"
                    f"🕒 {format_ts()}"
                )
                send_telegram_message(warn, chat_id, bot_token)

            update_last_balance(site_id, balance)

        time.sleep(max(poll_interval, 5))

    print("[Watcher] Stopped")


# =======================================
# AUTH
# =======================================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        pw = request.form.get("password", "")
        if pw == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        flash("Sai mật khẩu!", "danger")

    return render_template_string(
        """
        <html>
        <head><title>Đăng nhập - {{title}}</title></head>
        <body style="font-family:Arial;background:#111;color:#eee;">
            <div style="width:320px;margin:100px auto;padding:24px;border-radius:10px;background:#1d1d1d;">
                <h2 style="margin-top:0;text-align:center;">🔐 {{title}}</h2>
                <form method="POST">
                    <input type="password" name="password" placeholder="Mật khẩu admin"
                           style="width:100%;padding:10px;border-radius:6px;border:1px solid #444;background:#111;color:#eee;"
                           required>
                    <button type="submit"
                            style="margin-top:14px;width:100%;padding:10px;border:none;border-radius:6px;background:#0d6efd;color:#fff;font-weight:bold;cursor:pointer;">
                        Đăng nhập
                    </button>
                </form>
            </div>
        </body>
        </html>
        """,
        title=APP_TITLE,
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


def require_login():
    return bool(session.get("logged_in"))


# =======================================
# DASHBOARD + CONFIG + SITES
# =======================================
@app.route("/")
def root():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    if not require_login():
        return redirect(url_for("login"))

    poll_interval, threshold = get_settings()
    sites = get_all_sites()
    global watcher_running

    return render_template_string(
        """
        <html>
        <head><title>{{title}}</title></head>
        <body style="font-family:Arial;background:#0f0f10;color:#f5f5f5;">
            <div style="max-width:1000px;margin:20px auto;">
                <h1>{{title}}</h1>
                <p>Trạng thái watcher:
                    {% if watcher_running %}
                        ✅ Đang chạy
                    {% else %}
                        ⏹ Đang dừng
                    {% endif %}
                </p>

                <h3>⚙️ Cấu hình chung</h3>
                <form method="POST" action="{{url_for('update_config')}}">
                    <label>Chu kỳ quét (giây):</label><br>
                    <input type="number" name="poll_interval" value="{{poll_interval}}" min="5"
                           style="padding:6px;border-radius:4px;border:1px solid #444;background:#111;color:#eee;" required><br><br>

                    <label>Ngưỡng cảnh báo số dư thấp (đ, áp dụng chung):</label><br>
                    <input type="number" name="threshold" value="{{threshold}}" min="0"
                           style="padding:6px;border-radius:4px;border:1px solid #444;background:#111;color:#eee;" required><br><br>

                    <button type="submit"
                            style="padding:8px 16px;border:none;border-radius:4px;background:#0d6efd;color:#fff;cursor:pointer;font-weight:bold;">
                        💾 Lưu cấu hình
                    </button>
                </form>

                <p style="margin-top:15px;">
                    {% if not watcher_running %}
                        <a href="{{url_for('start_watcher')}}" style="margin-right:10px;">▶️ Bắt đầu theo dõi</a>
                    {% else %}
                        <a href="{{url_for('stop_watcher')}}" style="margin-right:10px;">⏹ Dừng theo dõi</a>
                    {% endif %}
                    <a href="{{url_for('backup')}}" style="margin-right:10px;">🧩 Backup JSON</a>
                    <a href="{{url_for('restore')}}" style="margin-right:10px;">♻️ Restore</a>
                    <a href="{{url_for('logout')}}">🚪 Đăng xuất</a>
                </p>

                <hr style="border-color:#333;">

                <h3>🌐 Danh sách website theo dõi</h3>
                <table width="100%" cellspacing="0" cellpadding="6"
                       style="border-collapse:collapse;font-size:14px;">
                    <tr style="background:#181818;">
                        <th align="left">Tên</th>
                        <th align="left">API URL</th>
                        <th align="left">Số dư cache</th>
                        <th align="left">Chat ID</th>
                        <th align="left">Thao tác</th>
                    </tr>
                    {% for s in sites %}
                    <tr style="border-top:1px solid #222;">
                        <td>{{s[1]}}</td>
                        <td style="font-size:11px;color:#aaa;">{{s[2]}}</td>
                        <td>{% if s[3] is not none %}{{"{:,.0f}".format(s[3])}}đ{% else %}-{% endif %}</td>
                        <td style="font-size:11px;color:#aaa;">{{s[4]}}</td>
                        <td>
                            <a href="{{url_for('edit_site', site_id=s[0])}}">✏️ Sửa</a> |
                            <a href="{{url_for('delete_site_route', site_id=s[0])}}" onclick="return confirm('Xoá site này?');">🗑 Xoá</a>
                        </td>
                    </tr>
                    {% endfor %}
                </table>

                <p style="margin-top:10px;">
                    <a href="{{url_for('edit_site', site_id=0)}}">➕ Thêm website mới</a>
                </p>

                {% with messages = get_flashed_messages(with_categories=true) %}
                  {% if messages %}
                    <div style="margin-top:20px;">
                      {% for category, msg in messages %}
                        <div style="padding:8px 10px;border-radius:4px;margin-bottom:6px;
                                    background:#222;color:#fff;border-left:4px solid
                                    {% if category == 'success' %}#28a745{% elif category == 'danger' %}#dc3545{% else %}#0d6efd{% endif %};">
                            {{msg}}
                        </div>
                      {% endfor %}
                    </div>
                  {% endif %}
                {% endwith %}
            </div>
        </body>
        </html>
        """,
        title=APP_TITLE,
        poll_interval=poll_interval,
        threshold=int(threshold),
        sites=sites,
        watcher_running=watcher_running,
    )


@app.route("/config", methods=["POST"])
def update_config():
    if not require_login():
        return redirect(url_for("login"))

    try:
        poll_interval = int(request.form.get("poll_interval", "30"))
        threshold = float(request.form.get("threshold", "100000"))
        if poll_interval < 5:
            poll_interval = 5
        update_settings(poll_interval, threshold)
        flash("Đã lưu cấu hình chung.", "success")
    except Exception as e:
        print(e)
        flash("Lỗi lưu cấu hình.", "danger")

    return redirect(url_for("dashboard"))


@app.route("/site/edit/<int:site_id>", methods=["GET", "POST"])
def edit_site(site_id):
    if not require_login():
        return redirect(url_for("login"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        api_url = request.form.get("api_url", "").strip()
        chat_id = request.form.get("chat_id", "").strip()
        bot_token = request.form.get("bot_token", "").strip()

        if not (name and api_url and chat_id and bot_token):
            flash("Vui lòng nhập đầy đủ thông tin.", "danger")
            return redirect(request.url)

        upsert_site(site_id if site_id != 0 else None, name, api_url, chat_id, bot_token)
        flash("Đã lưu website.", "success")
        return redirect(url_for("dashboard"))

    site = get_site(site_id) if site_id != 0 else None

    return render_template_string(
        """
        <html>
        <head><title>{{ 'Sửa' if site else 'Thêm' }} site - {{title}}</title></head>
        <body style="font-family:Arial;background:#0f0f10;color:#f5f5f5;">
            <div style="max-width:600px;margin:30px auto;">
                <h2>{{ 'Sửa website' if site else 'Thêm website mới' }}</h2>
                <form method="POST">
                    <label>Tên hiển thị:</label><br>
                    <input type="text" name="name" value="{{site[1] if site else ''}}" required
                           style="width:100%;padding:8px;border-radius:4px;border:1px solid:#444;background:#111;color:#eee;"><br><br>

                    <label>API URL trả về JSON số dư:</label><br>
                    <input type="text" name="api_url" value="{{site[2] if site else ''}}" required
                           style="width:100%;padding:8px;border-radius:4px;border:1px solid:#444;background:#111;color:#eee;"><br><br>

                    <label>Telegram Chat ID:</label><br>
                    <input type="text" name="chat_id" value="{{site[4] if site else ''}}" required
                           style="width:100%;padding:8px;border-radius:4px;border:1px solid:#444;background:#111;color:#eee;"><br><br>

                    <label>Telegram Bot Token:</label><br>
                    <input type="text" name="bot_token" value="{{site[5] if site else ''}}" required
                           style="width:100%;padding:8px;border-radius:4px;border:1px solid:#444;background:#111;color:#eee;"><br><br>

                    <button type="submit"
                            style="padding:8px 16px;border:none;border-radius:4px;background:#0d6efd;color:#fff;cursor:pointer;font-weight:bold;">
                        💾 Lưu
                    </button>
                    <a href="{{url_for('dashboard')}}" style="margin-left:10px;color:#ccc;">Hủy</a>
                </form>
            </div>
        </body>
        </html>
        """,
        title=APP_TITLE,
        site=site,
    )


@app.route("/site/delete/<int:site_id>")
def delete_site_route(site_id):
    if not require_login():
        return redirect(url_for("login"))
    delete_site(site_id)
    flash("Đã xoá website.", "info")
    return redirect(url_for("dashboard"))


# =======================================
# BACKUP / RESTORE JSON
# =======================================
def export_backup_json():
    poll_interval, threshold = get_settings()
    sites = get_all_sites()
    data = {
        "settings": {
            "poll_interval": poll_interval,
            "threshold": threshold,
        },
        "sites": [
            {
                "name": s[1],
                "api_url": s[2],
                "last_balance": s[3],
                "chat_id": s[4],
                "bot_token": s[5],
            }
            for s in sites
        ],
        "version": 1,
    }
    return data


def import_backup_json(data: dict):
    if not isinstance(data, dict):
        raise ValueError("Backup JSON không hợp lệ")

    settings = data.get("settings", {})
    sites = data.get("sites", [])

    poll_interval = int(settings.get("poll_interval", 30))
    threshold = float(settings.get("threshold", 100000))

    with db_lock, sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()

        # cập nhật settings
        c.execute(
            "UPDATE settings SET poll_interval=?, threshold=? WHERE id=1",
            (poll_interval, threshold),
        )

        # xoá hết sites cũ
        c.execute("DELETE FROM sites")

        # thêm sites mới
        for s in sites:
            name = s.get("name")
            api_url = s.get("api_url")
            chat_id = s.get("chat_id")
            bot_token = s.get("bot_token")
            last_balance = s.get("last_balance", None)

            if not (name and api_url and chat_id and bot_token):
                continue

            c.execute(
                """
                INSERT INTO sites (name, api_url, last_balance, chat_id, bot_token)
                VALUES (?,?,?,?,?)
                """,
                (name, api_url, last_balance, chat_id, bot_token),
            )

        conn.commit()


@app.route("/backup")
def backup():
    if not require_login():
        return redirect(url_for("login"))

    data = export_backup_json()
    content = json.dumps(data, ensure_ascii=False, indent=2)
    return Response(
        content,
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=balance_watcher_backup.json"},
    )


@app.route("/restore", methods=["GET", "POST"])
def restore():
    if not require_login():
        return redirect(url_for("login"))

    if request.method == "POST":
        raw = None

        file = request.files.get("file")
        if file and file.filename:
            raw = file.read().decode("utf-8", errors="ignore")
        else:
            raw = request.form.get("json_data", "").strip()

        if not raw:
            flash("Vui lòng chọn file hoặc dán nội dung JSON.", "danger")
            return redirect(url_for("restore"))

        try:
            data = json.loads(raw)
            import_backup_json(data)
            flash("Khôi phục dữ liệu từ backup thành công.", "success")
            return redirect(url_for("dashboard"))
        except Exception as e:
            print("Restore error:", e)
            flash("Backup JSON không hợp lệ.", "danger")
            return redirect(url_for("restore"))

    # GET: form restore
    return render_template_string(
        """
        <html>
        <head><title>Restore - {{title}}</title></head>
        <body style="font-family:Arial;background:#0f0f10;color:#f5f5f5;">
            <div style="max-width:700px;margin:30px auto;">
                <h2>♻️ Restore từ file backup JSON</h2>
                <p>Dữ liệu hiện tại sẽ bị ghi đè bằng dữ liệu trong file JSON.</p>
                <form method="POST" enctype="multipart/form-data">
                    <p><b>Chọn file JSON:</b></p>
                    <input type="file" name="file" accept="application/json"
                           style="color:#fff;"><br><br>

                    <p><b>Hoặc dán nội dung JSON:</b></p>
                    <textarea name="json_data" rows="10"
                              style="width:100%;padding:8px;border-radius:4px;border:1px solid:#444;background:#111;color:#eee;"></textarea><br><br>

                    <button type="submit"
                            style="padding:8px 16px;border:none;border-radius:4px;background:#dc3545;color:#fff;cursor:pointer;font-weight:bold;"
                            onclick="return confirm('Xác nhận ghi đè dữ liệu từ backup?');">
                        ♻️ Thực hiện restore
                    </button>
                    <a href="{{url_for('dashboard')}}" style="margin-left:10px;color:#ccc;">Hủy</a>
                </form>

                {% with messages = get_flashed_messages(with_categories=true) %}
                  {% if messages %}
                    <div style="margin-top:20px;">
                      {% for category, msg in messages %}
                        <div style="padding:8px 10px;border-radius:4px;margin-bottom:6px;
                                    background:#222;color:#fff;border-left:4px solid
                                    {% if category == 'success' %}#28a745{% elif category == 'danger' %}#dc3545{% else %}#0d6efd{% endif %};">
                            {{msg}}
                        </div>
                      {% endfor %}
                    </div>
                  {% endif %}
                {% endwith %}
            </div>
        </body>
        </html>
        """,
        title=APP_TITLE,
    )


# =======================================
# START / STOP WATCHER
# =======================================
@app.route("/start")
def start_watcher():
    if not require_login():
        return redirect(url_for("login"))

    global watcher_thread, watcher_running
    if not watcher_running:
        watcher_thread = threading.Thread(target=watcher_loop, daemon=True)
        watcher_thread.start()
        flash("Đã bắt đầu theo dõi số dư.", "success")
    else:
        flash("Watcher đang chạy rồi.", "info")
    return redirect(url_for("dashboard"))


@app.route("/stop")
def stop_watcher():
    if not require_login():
        return redirect(url_for("login"))

    global watcher_running
    watcher_running = False
    flash("Đã yêu cầu dừng watcher.", "info")
    return redirect(url_for("dashboard"))


# =======================================
# MAIN
# =======================================
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
