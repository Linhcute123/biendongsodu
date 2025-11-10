import os
import json
import threading
import time
from datetime import datetime
from typing import Any, Dict, List

import requests
from flask import (
    Flask,
    request,
    redirect,
    url_for,
    session,
    Response,
    render_template_string,
    flash,
)

from jinja2 import DictLoader, ChoiceLoader

# ----------------------
# Basic Config
# ----------------------
APP_TITLE = "Balance Watcher Universe"
CONFIG_PATH = os.getenv("CONFIG_PATH", "config.json")
STATE_PATH = os.getenv("STATE_PATH", "state.json")
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))  # giây giữa mỗi lần quét

# ĐẶT TRÊN RENDER: ADMIN_PASSWORD & SECRET_KEY
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")  # BẮT BUỘC đổi trên Render
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-change-me")

lock = threading.Lock()

# ----------------------
# Template nền vũ trụ + bản quyền Admin Văn Linh
# ----------------------
BASE_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <title>{{ title or "Balance Watcher Universe" }}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        :root {
            --bg-main: #030018;
            --bg-card: rgba(10, 8, 30, 0.98);
            --bg-input: rgba(15, 15, 40, 0.98);
            --accent: #5b8dff;
            --accent2: #ff5bf1;
            --text-main: #f6f6ff;
            --text-soft: #9aa0c6;
            --danger: #ff4d6a;
            --success: #2ecc71;
            --radius-xl: 22px;
            --shadow-soft: 0 18px 60px rgba(0, 0, 0, 0.55);
            --border-soft: 1px solid rgba(255,255,255,0.06);
            --font-main: system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Text", -system-ui, sans-serif;
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            padding: 0;
            font-family: var(--font-main);
            background: radial-gradient(circle at top, #15163b 0, #030018 40%, #000 100%);
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            align-items: stretch;
            justify-content: center;
        }
        .stars {
            position: fixed;
            inset: 0;
            pointer-events: none;
            background-image:
                radial-gradient(circle at 10% 20%, rgba(255,255,255,0.11) 0, transparent 40%),
                radial-gradient(circle at 90% 10%, rgba(91,141,255,0.18) 0, transparent 55%),
                radial-gradient(circle at 0% 80%, rgba(255,91,241,0.12) 0, transparent 55%);
            opacity: 0.36;
            mix-blend-mode: screen;
            z-index: 0;
        }
        .wrapper {
            position: relative;
            z-index: 2;
            width: 100%;
            max-width: 1180px;
            padding: 32px 18px 32px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .card {
            width: 100%;
            background: linear-gradient(135deg, rgba(255,255,255,0.02), rgba(91,141,255,0.04)) border-box,
                        var(--bg-card) padding-box;
            border-radius: 28px;
            padding: 26px 26px 22px;
            box-shadow: var(--shadow-soft);
            border: 1px solid rgba(255,255,255,0.09);
            backdrop-filter: blur(24px);
        }
        .logo-row {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 3px;
        }
        .orb {
            width: 26px;
            height: 26px;
            border-radius: 999px;
            background: conic-gradient(from 160deg, #5b8dff, #ff5bf1, #5bffde, #5b8dff);
            box-shadow: 0 0 16px rgba(91,141,255,0.9);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 15px;
            color: #fff;
        }
        .brand-title {
            font-size: 17px;
            font-weight: 500;
            color: var(--text-soft);
        }
        .brand-sub {
            font-size: 12px;
            color: var(--text-soft);
            opacity: 0.9;
        }
        .main-title {
            margin: 6px 0 12px;
            font-size: 27px;
            font-weight: 650;
            letter-spacing: 0.01em;
            display: flex;
            align-items: baseline;
            gap: 8px;
        }
        .main-title span.accent {
            font-size: 15px;
            color: var(--accent2);
            font-weight: 400;
        }
        .badge-linh {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 10px 4px 6px;
            border-radius: 999px;
            background: radial-gradient(circle at 0 0, rgba(91,141,255,0.35), transparent);
            border: 1px solid rgba(91,141,255,0.5);
            font-size: 10px;
            color: var(--text-soft);
        }
        .badge-linh .check {
            width: 16px;
            height: 16px;
            border-radius: 999px;
            background: radial-gradient(circle at 30% 30%, #fff, #1da1f2);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 11px;
            color: #fff;
            box-shadow: 0 0 8px rgba(29,161,242,0.9);
        }
        .grid {
            display: grid;
            grid-template-columns: 1.7fr 1.4fr;
            gap: 18px;
            margin-top: 4px;
        }
        .panel {
            background: radial-gradient(circle at top left, rgba(91,141,255,0.18), transparent),
                        var(--bg-input);
            border-radius: var(--radius-xl);
            padding: 14px 14px 12px;
            border: var(--border-soft);
            box-shadow: 0 12px 36px rgba(0,0,0,0.55);
        }
        .panel-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            margin-bottom: 8px;
        }
        .panel-title {
            font-size: 13px;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.14em;
            color: var(--text-soft);
        }
        .chip {
            padding: 3px 8px;
            border-radius: 999px;
            background: rgba(255,255,255,0.03);
            border: 1px solid rgba(255,255,255,0.05);
            font-size: 10px;
            color: var(--accent);
        }
        label {
            display: block;
            font-size: 11px;
            margin-bottom: 2px;
            color: var(--text-soft);
        }
        input[type="text"],
        input[type="password"],
        textarea {
            width: 100%;
            padding: 7px 9px;
            border-radius: 11px;
            border: 1px solid rgba(255,255,255,0.09);
            background: rgba(5,5,20,0.98);
            color: var(--text-main);
            font-size: 11px;
            outline: none;
            transition: all 0.16s ease;
        }
        input::placeholder,
        textarea::placeholder {
            color: rgba(154,160,198,0.5);
        }
        input:focus,
        textarea:focus {
            border-color: var(--accent2);
            box-shadow: 0 0 12px rgba(91,141,255,0.24);
        }
        textarea {
            min-height: 54px;
            resize: vertical;
        }
        .btn-row {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-top: 8px;
        }
        .btn {
            border: none;
            border-radius: 999px;
            padding: 7px 12px;
            font-size: 10px;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: linear-gradient(135deg, var(--accent), var(--accent2));
            color: #ffffff;
            box-shadow: 0 8px 22px rgba(0,0,0,0.65);
            transition: all 0.16s ease;
        }
        .btn span { font-size: 11px; }
        .btn-soft {
            background: rgba(255,255,255,0.02);
            color: var(--text-soft);
            border: 1px solid rgba(255,255,255,0.1);
            box-shadow: none;
        }
        .btn-danger { background: var(--danger); }
        .btn:hover {
            transform: translateY(-1px);
            box-shadow: 0 10px 26px rgba(0,0,0,0.8);
        }
        .btn-soft:hover {
            box-shadow: 0 10px 26px rgba(0,0,0,0.55);
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 6px;
            font-size: 10px;
        }
        th, td {
            padding: 4px 5px;
            border-bottom: 1px solid rgba(255,255,255,0.04);
            color: var(--text-soft);
            text-align: left;
        }
        th {
            font-size: 9px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: rgba(154,160,198,0.95);
        }
        tr:last-child td { border-bottom: none; }
        .pill {
            padding: 2px 7px;
            border-radius: 999px;
            font-size: 9px;
        }
        .pill-ok {
            background: rgba(46,204,113,0.16);
            color: var(--success);
        }
        .pill-unknown {
            background: rgba(255,255,255,0.02);
            color: var(--text-soft);
        }
        .pill-id {
            background: rgba(91,141,255,0.18);
            color: var(--accent);
        }
        .footer {
            margin-top: 10px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 8px;
            font-size: 9px;
            color: var(--text-soft);
        }
        .logout-link {
            color: rgba(154,160,198,0.8);
            text-decoration: none;
            font-size: 9px;
        }
        .logout-link:hover { color: var(--accent2); }
        .flash {
            padding: 6px 9px;
            border-radius: 13px;
            font-size: 9px;
            margin-bottom: 6px;
            background: rgba(255,255,255,0.02);
            border: 1px solid rgba(255,255,255,0.09);
            color: var(--accent);
        }
        .flash-error {
            border-color: var(--danger);
            color: var(--danger);
        }
        @media (max-width: 840px) {
            .grid { grid-template-columns: 1fr; }
            .card { padding: 20px 16px 16px; }
        }
    </style>
</head>
<body>
<div class="stars"></div>
<div class="wrapper">
    <div class="card">
        <div class="logo-row">
            <div class="orb">∞</div>
            <div>
                <div class="brand-title">Balance Watcher Universe</div>
                <div class="brand-sub">Trung tâm giám sát số dư &amp; cảnh báo Telegram theo thời gian gần thực</div>
            </div>
        </div>
        <div class="main-title">
            <div>Quantum Balance Monitor</div>
            <span class="accent">phiên bản Render-ready</span>
        </div>
        <div class="badge-linh">
            <div class="check">✓</div>
            <div>Bot được bảo dưỡng &amp; phát triển bởi <strong>Admin Văn Linh</strong></div>
        </div>
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for cat, msg in messages %}
              <div class="flash {% if cat == 'error' %}flash-error{% endif %}">{{ msg }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        {% block content %}{% endblock %}
    </div>
</div>
</body>
</html>
"""

LOGIN_TEMPLATE = r"""
{% extends "base.html" %}
{% block content %}
<div class="grid">
    <div class="panel">
        <div class="panel-header">
            <div class="panel-title">Đăng nhập bảng điều khiển</div>
            <div class="chip">Mã hoá phiên &amp; khoá bí mật</div>
        </div>
        <form method="post">
            <label>Mật khẩu truy cập (do bạn cấu hình trong ADMIN_PASSWORD)</label>
            <input type="password" name="password" placeholder="Nhập mật khẩu siêu bí mật..." required>
            <div class="btn-row">
                <button type="submit" class="btn">
                    <span>🚀 Vào vũ trụ giám sát</span>
                </button>
            </div>
        </form>
    </div>
    <div class="panel">
        <div class="panel-header">
            <div class="panel-title">Hướng dẫn triển khai nhanh</div>
        </div>
        <div style="font-size:10px; color:var(--text-soft); line-height:1.7;">
            <ol style="padding-left:14px; margin:0;">
                <li>Deploy lên Render (Python, Gunicorn, Flask).</li>
                <li>Đặt biến môi trường <b>ADMIN_PASSWORD</b> &amp; <b>SECRET_KEY</b>.</li>
                <li>Đăng nhập, cấu hình <b>Telegram BOT TOKEN(s)</b> &amp; <b>CHAT ID</b>.</li>
                <li>Thêm các URL API số dư (VD: ShopAccMMO profile API).</li>
                <li>Watcher sẽ theo dõi &amp; bắn cảnh báo khi số dư đổi.</li>
            </ol>
            <div style="margin-top:8px;">
                Không share link dashboard/pw ra ngoài. Toàn bộ brand thuộc <b>Admin Văn Linh</b>.
            </div>
        </div>
    </div>
</div>
{% endblock %}
"""

DASHBOARD_TEMPLATE = r"""
{% extends "base.html" %}
{% block content %}
<div class="grid">
    <!-- LEFT: TELEGRAM + GLOBAL -->
    <div class="panel">
        <div class="panel-header">
            <div class="panel-title">Cấu hình Telegram &amp; hệ thống</div>
            <div class="chip">Nhiều BOT TOKEN → 1 CHAT_ID</div>
        </div>
        <form method="post" action="{{ url_for('save_telegram') }}">
            <label>TELEGRAM_CHAT_ID (nhận thông báo)</label>
            <input type="text" name="telegram_chat_id"
                   placeholder="VD: 123456789 (nên dùng ID thay vì @username)"
                   value="{{ config.telegram_chat_id or '' }}">
            <label>Danh sách TELEGRAM_BOT_TOKEN (mỗi dòng 1 token)</label>
            <textarea name="telegram_bots"
                      placeholder="123456:ABC-DEF...&#10;987654:XYZ-...">{{ '\n'.join(config.telegram_bots) if config.telegram_bots else '' }}</textarea>
            <label>Chu kỳ quét (giây) - từ biến môi trường POLL_INTERVAL = {{ poll_interval }}</label>
            <input type="text" value="{{ poll_interval }}" disabled>
            <div class="btn-row">
                <button type="submit" class="btn">
                    <span>💾 Lưu cấu hình Telegram</span>
                </button>
                <a href="{{ url_for('backup') }}" class="btn btn-soft">
                    📦 Tải backup thủ công
                </a>
            </div>
        </form>
        <div style="margin-top:10px; font-size:9px; color:var(--text-soft);">
            Gợi ý:
            <ul style="margin:4px 0 0 13px; padding:0;">
                <li>Có thể nhập nhiều BOT TOKEN, tất cả sẽ gửi về cùng 1 CHAT_ID.</li>
                <li>Không để lộ CHAT_ID &amp; BOT TOKEN trong ảnh/chia sẻ.</li>
            </ul>
        </div>
    </div>

    <!-- RIGHT: API LIST / ADD -->
    <div class="panel">
        <div class="panel-header">
            <div class="panel-title">Danh sách API số dư</div>
            <div class="chip">Auto CỘNG TIỀN / THANH TOÁN</div>
        </div>
        <form method="post" action="{{ url_for('add_api') }}">
            <label>Tên hiển thị</label>
            <input type="text" name="name" placeholder="VD: ShopAccMMO chính" required>
            <label>URL API kiểm tra số dư</label>
            <input type="text" name="url" placeholder="https://.../api/profile.php?api_key=..." required>
            <label>Trường số dư trong JSON (default: balance) — hỗ trợ dạng: data.balance</label>
            <input type="text" name="balance_field" placeholder="balance" value="balance">
            <div class="btn-row">
                <button type="submit" class="btn">
                    <span>➕ Thêm API mới</span>
                </button>
            </div>
        </form>

        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Tên</th>
                    <th>URL</th>
                    <th>Trường</th>
                    <th>Số dư gần nhất</th>
                    <th>Cập nhật</th>
                    <th></th>
                </tr>
            </thead>
            <tbody>
                {% if config.apis %}
                    {% for api in config.apis %}
                    <tr>
                        <td><span class="pill pill-id">{{ api.id }}</span></td>
                        <td>{{ api.name }}</td>
                        <td style="max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                            {{ api.url }}
                        </td>
                        <td>{{ api.balance_field }}</td>
                        {% set st = state.get(api.id_str) %}
                        {% if st and st.last_balance is not none %}
                            <td><span class="pill pill-ok">{{ st.last_balance }}</span></td>
                            <td style="font-size:8px;">{{ st.last_change or '-' }}</td>
                        {% else %}
                            <td><span class="pill pill-unknown">chưa có dữ liệu</span></td>
                            <td>-</td>
                        {% endif %}
                        <td>
                            <form method="post"
                                  action="{{ url_for('delete_api', api_id=api.id) }}"
                                  onsubmit="return confirm('Xoá API này?');">
                                <button type="submit" class="btn btn-soft btn-danger">✖</button>
                            </form>
                        </td>
                    </tr>
                    {% endfor %}
                {% else %}
                    <tr>
                        <td colspan="7"
                            style="text-align:center; font-size:9px; padding:10px 0; color:var(--text-soft);">
                            Chưa có API nào. Thêm ít nhất một đường dẫn API số dư để bắt đầu.
                        </td>
                    </tr>
                {% endif %}
            </tbody>
        </table>
    </div>
</div>

<div class="footer">
    <div>
        Trạng thái watcher:
        {% if watcher_running %}
            <span class="pill pill-ok">Đang chạy nền</span>
        {% else %}
            <span class="pill pill-unknown">Chưa kích hoạt</span>
        {% endif %}
        <span style="margin-left:6px;">POLL_INTERVAL={{ poll_interval }}s</span>
    </div>
    <div>
        <a href="{{ url_for('logout') }}" class="logout-link">Đăng xuất</a>
    </div>
</div>
{% endblock %}
"""

# ---------------------- Flask app & Jinja loader ----------------------
app = Flask(__name__)
app.secret_key = SECRET_KEY

dict_loader = DictLoader({"base.html": BASE_TEMPLATE})
if app.jinja_loader:
    app.jinja_loader = ChoiceLoader([dict_loader, app.jinja_loader])
else:
    app.jinja_loader = dict_loader

# ---------------------- JSON helpers ----------------------
def _ensure_paths():
    if not os.path.exists(CONFIG_PATH):
        _save_json(CONFIG_PATH, {"telegram_chat_id": "", "telegram_bots": [], "apis": []})
    if not os.path.exists(STATE_PATH):
        _save_json(STATE_PATH, {})

def _load_json(path: str, default: Any):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _save_json(path: str, data: Any):
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)

def load_config() -> Dict[str, Any]:
    _ensure_paths()
    with lock:
        raw = _load_json(CONFIG_PATH, {})
    telegram_chat_id = raw.get("telegram_chat_id", "") or ""
    telegram_bots = raw.get("telegram_bots", []) or []
    apis_raw = raw.get("apis", []) or []
    apis = []
    for idx, api in enumerate(apis_raw, start=1):
        if not api:
            continue
        aid = api.get("id", idx)
        name = api.get("name", f"API #{aid}")
        url = (api.get("url") or "").strip()
        balance_field = (api.get("balance_field") or "balance").strip() or "balance"
        if not url:
            continue
        apis.append(
            {
                "id": int(aid),
                "name": name,
                "url": url,
                "balance_field": balance_field,
            }
        )
    return {"telegram_chat_id": telegram_chat_id, "telegram_bots": telegram_bots, "apis": apis}

def save_config(config: Dict[str, Any]):
    with lock:
        _save_json(CONFIG_PATH, config)

def load_state() -> Dict[str, Any]:
    _ensure_paths()
    with lock:
        st = _load_json(STATE_PATH, {})
    return st if isinstance(st, dict) else {}

def save_state(state: Dict[str, Any]):
    with lock:
        _save_json(STATE_PATH, state)

def extract_field(data: Any, path: str):
    if not path:
        return None
    parts = path.split(".")
    v = data
    for p in parts:
        if isinstance(v, dict):
            v = v.get(p)
        else:
            return None
    return v

def parse_balance(value: Any):
    if value is None:
        return None
    try:
        if isinstance(value, str):
            cleaned = "".join(ch for ch in value if (ch.isdigit() or ch in ",.-"))
            if cleaned.count(",") > 1 and "." not in cleaned:
                cleaned = cleaned.replace(",", "")
            cleaned = cleaned.replace(",", "")
            return float(cleaned)
        return float(value)
    except Exception:
        return None

# ---------------------- Telegram ----------------------
def send_telegram_message(tokens: List[str], chat_id: str, text: str):
    if not tokens or not chat_id:
        return
    for token in tokens:
        token = (token or "").strip()
        if not token:
            continue
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            requests.post(
                url,
                data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
        except Exception:
            pass

# ---------------------- Watcher thread ----------------------
watcher_running = False

def watcher_loop():
    global watcher_running
    watcher_running = True
    while True:
        try:
            cfg = load_config()
            state = load_state()

            bots = cfg.get("telegram_bots", [])
            chat_id = (cfg.get("telegram_chat_id") or "").strip()
            apis = cfg.get("apis", [])

            for api in apis:
                api_id = str(api["id"])
                url = api["url"]
                balance_field = api["balance_field"]

                try:
                    r = requests.get(url, timeout=15)
                    r.raise_for_status()
                    data = r.json()
                except Exception:
                    continue

                raw_balance = extract_field(data, balance_field)
                if raw_balance is None and balance_field != "balance":
                    raw_balance = data.get("balance")

                new_balance = parse_balance(raw_balance)
                if new_balance is None:
                    continue

                info = state.get(api_id, {})
                old_balance = info.get("last_balance")

                if old_balance is None:
                    state[api_id] = {
                        "last_balance": new_balance,
                        "last_change": datetime.utcnow().isoformat() + "Z",
                    }
                else:
                    old_balance = float(old_balance)
                    if abs(new_balance - old_balance) > 1e-9:
                        diff = new_balance - old_balance
                        change_type = "CỘNG TIỀN" if diff > 0 else "THANH TOÁN"
                        prefix_emoji = "🟢" if diff > 0 else "🔴"

                        msg = (
                            f"{prefix_emoji} <b>{change_type}</b> tại <b>{api['name']}</b>\n"
                            f"Số dư cũ: <code>{old_balance}</code>\n"
                            f"Biến động: <code>{diff:+}</code>\n"
                            f"Số dư mới: <b><code>{new_balance}</code></b>\n"
                            f"Thời gian (UTC): <code>{datetime.utcnow().isoformat()}Z</code>"
                        )
                        send_telegram_message(bots, chat_id, msg)

                        state[api_id] = {
                            "last_balance": new_balance,
                            "last_change": datetime.utcnow().isoformat() + "Z",
                        }

            save_state(state)
        except Exception:
            pass

        time.sleep(POLL_INTERVAL)

def start_watcher():
    t = threading.Thread(target=watcher_loop, daemon=True)
    t.start()

# ---------------------- Auth ----------------------
def is_logged_in():
    return session.get("logged_in") is True

@app.before_request
def require_login():
    # cho phép login + health không cần pass
    if request.endpoint in ("login", "health", "static"):
        return
    if not is_logged_in():
        return redirect(url_for("login"))

# ---------------------- Routes ----------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == ADMIN_PASSWORD:
            session["logged_in"] = True
            flash("Đăng nhập thành công. Chào mừng Admin Văn Linh đến vũ trụ giám sát số dư.", "ok")
            return redirect(url_for("dashboard"))
        else:
            flash("Sai mật khẩu. Vui lòng thử lại.", "error")
    return render_template_string(LOGIN_TEMPLATE)

@app.route("/logout")
def logout():
    session.clear()
    flash("Đã đăng xuất.", "ok")
    return redirect(url_for("login"))

@app.route("/")
def dashboard():
    cfg = load_config()
    st_raw = load_state()

    class Obj(dict):
        __getattr__ = dict.get
        __setattr__ = dict.__setitem__

    config = Obj()
    config.telegram_chat_id = cfg.get("telegram_chat_id", "")
    config.telegram_bots = cfg.get("telegram_bots", [])
    apis = []
    for api in cfg.get("apis", []):
        api_obj = Obj(api)
        api_obj.id_str = str(api_obj.id)
        apis.append(api_obj)
    config.apis = apis

    state = {}
    for k, v in st_raw.items():
        o = Obj(v)
        state[str(k)] = o

    return render_template_string(
        DASHBOARD_TEMPLATE,
        config=config,
        state=state,
        watcher_running=watcher_running,
        poll_interval=POLL_INTERVAL,
    )

@app.route("/save_telegram", methods=["POST"])
def save_telegram():
    cfg = load_config()
    chat_id = (request.form.get("telegram_chat_id") or "").strip()
    bots_raw = request.form.get("telegram_bots") or ""
    bots = [line.strip() for line in bots_raw.splitlines() if line.strip()]

    cfg["telegram_chat_id"] = chat_id
    cfg["telegram_bots"] = bots
    save_config(cfg)
    flash("Đã lưu cấu hình Telegram.", "ok")
    return redirect(url_for("dashboard"))

@app.route("/add_api", methods=["POST"])
def add_api():
    cfg = load_config()
    name = (request.form.get("name") or "").strip()
    url_api = (request.form.get("url") or "").strip()
    balance_field = (request.form.get("balance_field") or "").strip() or "balance"

    if not name or not url_api:
        flash("Thiếu tên hoặc URL API.", "error")
        return redirect(url_for("dashboard"))

    apis = cfg.get("apis", [])
    new_id = max((int(a.get("id", 0)) for a in apis), default=0) + 1
    apis.append(
        {
            "id": new_id,
            "name": name,
            "url": url_api,
            "balance_field": balance_field,
        }
    )
    cfg["apis"] = apis
    save_config(cfg)
    flash(f"Đã thêm API [{name}].", "ok")
    return redirect(url_for("dashboard"))

@app.route("/delete_api/<int:api_id>", methods=["POST"])
def delete_api(api_id: int):
    cfg = load_config()
    apis = cfg.get("apis", [])
    apis = [a for a in apis if int(a.get("id", 0)) != int(api_id)]
    cfg["apis"] = apis
    save_config(cfg)

    st = load_state()
    st.pop(str(api_id), None)
    save_state(st)

    flash(f"Đã xoá API ID {api_id}.", "ok")
    return redirect(url_for("dashboard"))

@app.route("/backup")
def backup():
    cfg = load_config()
    st = load_state()
    backup_data = {
        "config": cfg,
        "state": st,
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
    }
    backup_json = json.dumps(backup_data, ensure_ascii=False, indent=2)
    return Response(
        backup_json,
        mimetype="application/json",
        headers={"Content-Disposition": 'attachment; filename="balance_watcher_backup.json"'},
    )

@app.context_processor
def inject_title():
    return {"title": APP_TITLE}

@app.route("/health")
def health():
    return {"status": "ok", "watcher_running": watcher_running}

# khởi động watcher khi app load
start_watcher()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
