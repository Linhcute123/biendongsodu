import os
import sqlite3
import threading
import time
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

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

# =========================
# CẤU HÌNH CƠ BẢN
# =========================

APP_TITLE = "Balance Watcher Universe"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
SECRET_KEY = os.getenv("SECRET_KEY", ADMIN_PASSWORD)

# Đường dẫn file backup tự động (Secret File trên Render)
# Bạn cần tạo file tên là "backup" trong phần Secret Files của Render
AUTO_BACKUP_PATH = os.getenv("SECRET_BACKUP_FILE_PATH", "/etc/secrets/backup")

DATA_DIR = "/data"
if not os.path.isdir(DATA_DIR):
    DATA_DIR = "."
DB_PATH = os.path.join(DATA_DIR, "balance_watcher.db")

POLL_INTERVAL_DEFAULT = 30
PING_INTERVAL_DEFAULT = 10  # Mặc định 10 phút ping 1 lần

app = Flask(__name__)
app.secret_key = SECRET_KEY

db_lock = threading.Lock()
watcher_started = False
watcher_running = False
pinger_started = False  # Cờ chạy luồng Ping

# =========================
# Múi giờ Việt Nam
# =========================
try:
    from zoneinfo import ZoneInfo
    VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
except Exception:
    VN_TZ = timezone(timedelta(hours=7))

def fmt_time_label_vn(dt_utc: datetime) -> str:
    try:
        local = dt_utc.replace(tzinfo=timezone.utc).astimezone(VN_TZ)
    except Exception:
        local = dt_utc
    return local.strftime("%H:%M %d/%m/%Y (VN)")

def parse_iso_utc(s: str) -> Optional[datetime]:
    if not s: return None
    try:
        si = s.rstrip("Z")
        dt = datetime.fromisoformat(si)
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        else: dt = dt.astimezone(timezone.utc)
        return dt
    except Exception: return None

# =========================
# HELPERS
# =========================
def fmt_amount(v: float) -> str:
    try: return f"{float(v):,.0f}đ"
    except: return f"{v}đ"

def to_float(s: Optional[str], default: Optional[float] = None) -> Optional[float]:
    try:
        if s is None: return default
        s = s.replace(",", "").strip()
        return float(s)
    except: return default

# =========================
# TEMPLATE: LOGIN (Giao diện Vũ trụ)
# =========================
LOGIN_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <title>Đăng nhập | {{ title }}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {
            background-color: #020817;
            background-image:
                radial-gradient(circle at 0 0, rgba(129, 140, 248, 0.18), transparent 55%),
                radial-gradient(circle at 100% 0, rgba(45, 212, 191, 0.10), transparent 55%),
                radial-gradient(circle at 100% 100%, rgba(236, 72, 153, 0.10), transparent 55%);
            min-height: 100vh;
            font-family: system-ui, -apple-system, sans-serif;
        }
    </style>
</head>
<body class="flex items-center justify-center">
    <div class="max-w-md w-full mx-4">
        <div class="bg-slate-900/80 border border-slate-700/80 rounded-3xl shadow-2xl p-8 backdrop-blur-xl relative overflow-hidden">
            <div class="absolute -top-10 -right-10 w-32 h-32 bg-indigo-500/20 rounded-full blur-3xl"></div>
            <div class="absolute -bottom-16 -left-10 w-40 h-40 bg-fuchsia-500/10 rounded-full blur-3xl"></div>
            <div class="flex items-center gap-3 mb-2 relative z-10">
                <div class="w-8 h-8 rounded-full bg-gradient-to-tr from-indigo-400 via-sky-400 to-fuchsia-400 flex items-center justify-center text-white text-xl shadow-lg">∞</div>
                <div class="text-xs uppercase tracking-[0.18em] text-slate-400">Quantum Security Gate</div>
            </div>
            <h1 class="mt-4 text-2xl font-semibold text-slate-50 tracking-tight">Đăng nhập Dashboard</h1>
            {% with messages = get_flashed_messages(with_categories=true) %}
              {% if messages %}
                <div class="mt-4 space-y-2">
                  {% for category, message in messages %}
                    <div class="px-3 py-2 rounded-2xl text-xs text-red-200 border border-red-500/40 bg-red-900/60">{{ message }}</div>
                  {% endfor %}
                </div>
              {% endif %}
            {% endwith %}
            <form method="post" class="mt-5 space-y-3 relative z-10">
                <input type="password" name="password" required placeholder="Mật khẩu Admin"
                    class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-slate-100 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500">
                <button type="submit" class="w-full mt-2 px-4 py-2.5 rounded-2xl bg-gradient-to-r from-indigo-500 via-sky-500 to-fuchsia-500 text-white text-sm font-medium shadow-xl hover:shadow-2xl hover:-translate-y-0.5 transition-all">
                    🚀 Vào Dashboard Vũ Trụ
                </button>
            </form>
        </div>
    </div>
</body>
</html>
"""

# =========================
# TEMPLATE: DASHBOARD (Giao diện Vũ trụ - Đã xóa Email, Thêm Ping)
# =========================
DASHBOARD_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <title>{{ title }} | Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { 
            font-family: system-ui, -apple-system, sans-serif;
            background-color: #020817;
            background-image:
                radial-gradient(circle at 0 0, rgba(129, 140, 248, 0.18), transparent 55%),
                radial-gradient(circle at 100% 0, rgba(45, 212, 191, 0.10), transparent 55%),
                radial-gradient(circle at 100% 100%, rgba(236, 72, 153, 0.10), transparent 55%);
            min-height: 100vh;
            color: #f1f5f9;
        }
        .scrollbar-thin::-webkit-scrollbar { height:5px; width:5px; }
        .scrollbar-thin::-webkit-scrollbar-thumb { background-color:rgba(148,163,253,0.4); border-radius:999px; }
    </style>
</head>
<body class="p-4 md:p-8">
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        <div class="max-w-6xl mx-auto mb-4 space-y-2">
          {% for category, message in messages %}
            <div class="px-4 py-2 rounded-2xl text-xs border
                {% if category == 'error' %}bg-red-900/60 text-red-200 border-red-500/40{% else %}bg-emerald-900/40 text-emerald-200 border-emerald-500/30{% endif %}">
              {{ message }}
            </div>
          {% endfor %}
        </div>
      {% endif %}
    {% endwith %}

    <div class="max-w-6xl mx-auto mb-5 flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        <div>
            <div class="flex items-center gap-3">
                <div class="w-9 h-9 rounded-full bg-gradient-to-tr from-indigo-400 via-sky-400 to-fuchsia-400 flex items-center justify-center text-white text-2xl shadow-lg">∞</div>
                <div>
                    <div class="text-[10px] uppercase tracking-[0.18em] text-slate-400">Balance Watcher Universe</div>
                    <div class="text-[11px] text-slate-500">Admin Văn Linh <span class="text-cyan-400">✓</span></div>
                </div>
            </div>
            <h1 class="mt-3 text-3xl font-semibold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-indigo-300 via-sky-300 to-fuchsia-300">
                Quantum Dashboard
            </h1>
        </div>
        <div class="flex flex-col items-end gap-1 text-[10px] text-slate-500">
            <div>Auto Restore: <span class="{{ 'text-emerald-400' if auto_restore_status == 'Success' else 'text-rose-400' }}">{{ auto_restore_status }}</span></div>
            <div>Ping Web: <span class="{{ 'text-emerald-400' if ping_active else 'text-slate-600' }}">{{ 'Đang chạy' if ping_active else 'Đã tắt' }}</span></div>
            <a href="{{ url_for('logout') }}" class="text-slate-500 hover:text-fuchsia-400 transition">Đăng xuất</a>
        </div>
    </div>

    <div class="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-3 gap-5 items-start">
        
        <div class="space-y-5">
            <div class="bg-slate-900/80 border border-slate-800 rounded-3xl p-5 shadow-2xl backdrop-blur-xl">
                <h2 class="text-sm font-semibold text-indigo-300 uppercase tracking-[0.16em] mb-3">Cài đặt & Ping</h2>
                <form method="post" action="{{ url_for('save_settings') }}" class="space-y-3">
                    
                    <div class="space-y-1">
                        <label class="block text-[10px] text-slate-400">Telegram Chat ID</label>
                        <input type="text" name="default_chat_id" value="{{ settings.default_chat_id }}" placeholder="ID nhận tin nhắn"
                            class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500">
                    </div>

                    <div class="grid grid-cols-2 gap-2">
                        <div>
                            <label class="block text-[10px] text-slate-400">Chu kỳ quét (s)</label>
                            <input type="number" name="poll_interval" value="{{ settings.poll_interval }}"
                                class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500">
                        </div>
                        <div>
                            <label class="block text-[10px] text-slate-400">Ngưỡng báo (VND)</label>
                            <input type="text" name="global_threshold" value="{{ settings.global_threshold }}"
                                class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 focus:outline-none focus:ring-2 focus:ring-rose-500">
                        </div>
                    </div>

                    <hr class="border-slate-700/60 my-2">
                    
                    <div class="space-y-2">
                        <h3 class="text-[11px] font-bold text-emerald-400 uppercase">⚡ Ping Keep-Alive (Chống ngủ)</h3>
                        <div>
                            <label class="block text-[10px] text-slate-400">Link Web (Ping chính nó)</label>
                            <input type="text" name="ping_url" value="{{ settings.ping_url }}" placeholder="https://ten-app.onrender.com"
                                class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                        </div>
                        <div>
                            <label class="block text-[10px] text-slate-400">Thời gian Ping (phút)</label>
                            <input type="number" name="ping_interval" value="{{ settings.ping_interval }}" placeholder="VD: 10"
                                class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500">
                        </div>
                    </div>

                    <button type="submit" class="w-full mt-2 inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-2xl bg-gradient-to-r from-indigo-500 via-sky-500 to-fuchsia-500 text-white text-[11px] font-medium shadow-lg hover:-translate-y-0.5 transition-all">
                        💾 Lưu cấu hình
                    </button>
                </form>
            </div>

            <div class="bg-slate-900/80 border border-slate-800 rounded-3xl p-5 shadow-2xl backdrop-blur-xl">
                <h2 class="text-sm font-semibold text-fuchsia-300 uppercase tracking-[0.16em] mb-3">Backup / Restore</h2>
                <div class="grid grid-cols-2 gap-2 mb-3">
                    <a href="{{ url_for('download_backup') }}" class="w-full text-center px-4 py-2 rounded-2xl bg-slate-800 text-[10px] border border-slate-600 hover:text-fuchsia-200">📦 Tải Backup</a>
                    <a href="{{ url_for('download_apis') }}" class="w-full text-center px-4 py-2 rounded-2xl bg-slate-800 text-[10px] border border-slate-600 hover:text-fuchsia-200">🌐 Tải APIs</a>
                </div>
                <form method="post" action="{{ url_for('restore_backup') }}" enctype="multipart/form-data" class="space-y-2">
                    <input type="file" name="backup_file" accept=".json" class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[10px] text-slate-400">
                    <label class="flex items-center gap-2 text-[10px] text-slate-400">
                        <input type="checkbox" name="wipe" value="1" class="rounded bg-slate-900"> Xoá dữ liệu cũ
                    </label>
                    <button type="submit" class="w-full px-4 py-2 rounded-2xl bg-slate-800 text-fuchsia-400 text-[11px] font-bold border border-slate-700 hover:bg-slate-700">
                        ♻️ Restore từ File
                    </button>
                </form>
            </div>
            
            <div class="bg-slate-900/80 border border-slate-800 rounded-3xl p-5 shadow-2xl backdrop-blur-xl">
                <h2 class="text-sm font-semibold text-cyan-300 uppercase tracking-[0.16em] mb-3">Bot Telegram</h2>
                <form method="post" action="{{ url_for('add_bot') }}" class="space-y-2 mb-3">
                    <input type="text" name="bot_name" placeholder="Tên Bot" required class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 focus:outline-none focus:ring-2 focus:ring-cyan-500">
                    <input type="text" name="bot_token" placeholder="Token" required class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 focus:outline-none focus:ring-2 focus:ring-cyan-500">
                    <button type="submit" class="w-full px-4 py-2 rounded-2xl bg-cyan-900/50 text-cyan-400 text-[11px] font-bold border border-cyan-700/50 hover:bg-cyan-900/80">➕ Thêm Bot</button>
                </form>
                <div class="space-y-2 max-h-32 overflow-y-auto scrollbar-thin">
                    {% for bot in bots %}
                    <div class="flex justify-between items-center px-3 py-2 rounded-2xl bg-slate-950/70 border border-slate-800">
                        <div class="text-[10px]">
                            <div class="text-slate-200 font-bold">{{ bot.bot_name }}</div>
                            <div class="text-slate-500">...{{ bot.bot_token[-8:] }}</div>
                        </div>
                        <form method="post" action="{{ url_for('delete_bot') }}"><input type="hidden" name="bot_id" value="{{ bot.id }}"><button class="text-[10px] text-rose-400 hover:text-rose-300">Xoá</button></form>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>

        <div class="lg:col-span-2 space-y-5">
            <div class="bg-slate-900/80 border border-slate-800 rounded-3xl p-5 shadow-2xl backdrop-blur-xl">
                <h2 class="text-sm font-semibold text-sky-300 uppercase tracking-[0.16em] mb-3">Thêm API Theo dõi</h2>
                <form method="post" action="{{ url_for('add_api') }}" class="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <input type="text" name="name" placeholder="Tên Shop/Web" required class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 focus:outline-none focus:ring-2 focus:ring-sky-500">
                    <input type="text" name="url" placeholder="Link API (https://...)" required class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 focus:outline-none focus:ring-2 focus:ring-sky-500">
                    <input type="text" name="balance_field" placeholder="Trường số dư (balance, data.money...)" class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 focus:outline-none focus:ring-2 focus:ring-sky-500">
                    <div class="md:col-span-2"><button type="submit" class="w-full px-4 py-2 rounded-2xl bg-sky-600 text-white text-[11px] font-bold shadow-lg hover:bg-sky-500">➕ Thêm API</button></div>
                </form>
            </div>

            <div class="bg-slate-900/80 border border-slate-800 rounded-3xl p-5 shadow-2xl backdrop-blur-xl overflow-hidden">
                <div class="flex items-center justify-between mb-3">
                    <h2 class="text-sm font-semibold text-slate-300 uppercase tracking-[0.16em]">Danh sách API</h2>
                    <span class="text-[10px] text-slate-500">Cập nhật: {{ last_run_vn }}</span>
                </div>
                <div class="overflow-x-auto scrollbar-thin">
                    <table class="min-w-full text-[10px]">
                        <thead class="bg-slate-950/80 text-slate-400 uppercase">
                            <tr>
                                <th class="px-3 py-2 text-left">ID</th>
                                <th class="px-3 py-2 text-left">Tên</th>
                                <th class="px-3 py-2 text-left">URL</th>
                                <th class="px-3 py-2 text-left">Số dư</th>
                                <th class="px-3 py-2 text-left">Thời gian</th>
                                <th class="px-3 py-2 text-right"></th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-slate-800">
                            {% for api in apis %}
                            <tr class="hover:bg-slate-800/80 transition">
                                <td class="px-3 py-2 text-slate-500">#{{ api.id }}</td>
                                <td class="px-3 py-2 font-medium text-slate-100">{{ api.name }}</td>
                                <td class="px-3 py-2 text-slate-500 truncate max-w-[150px]">{{ api.url }}</td>
                                <td class="px-3 py-2"><span class="px-2 py-0.5 rounded-full bg-emerald-900/40 text-emerald-300">{{ "{:,.0f}".format(api.last_balance|float) if api.last_balance is not none else '---' }}đ</span></td>
                                <td class="px-3 py-2 text-slate-500">{{ api.last_change_vn }}</td>
                                <td class="px-3 py-2 text-right">
                                    <form method="post" action="{{ url_for('delete_api', api_id=api.id) }}" onsubmit="return confirm('Xoá?');"><button class="text-rose-400 hover:text-rose-300">✕</button></form>
                                </td>
                            </tr>
                            {% else %}
                            <tr><td colspan="6" class="px-3 py-4 text-center text-slate-500">Chưa có API nào.</td></tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
"""

# =========================
# DATABASE
# =========================
def init_db():
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS telegram_bots (id INTEGER PRIMARY KEY AUTOINCREMENT, bot_name TEXT, bot_token TEXT UNIQUE)")
        c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        
        # Các keys cấu hình (đã xóa report_email, smtp_*)
        keys = ["default_chat_id", "default_bot_id", "last_run", "poll_interval", "global_threshold", 
                "ping_url", "ping_interval"]
        for k in keys:
            c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, '')", (k,))
            
        c.execute("CREATE TABLE IF NOT EXISTS apis (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, url TEXT, balance_field TEXT, last_balance REAL, last_change TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS balance_history (id INTEGER PRIMARY KEY AUTOINCREMENT, api_id INTEGER, name TEXT, timestamp TEXT, change_amount REAL, new_balance REAL)")
        conn.commit()
        conn.close()

def get_settings() -> Dict[str, Optional[str]]:
    with db_lock:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor(); c.execute("SELECT key, value FROM settings"); rows = c.fetchall(); conn.close()
    return {k: (v if v is not None else "") for k, v in rows}

def set_setting(key: str, value: str):
    with db_lock:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor(); c.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value)); conn.commit(); conn.close()

def get_bots():
    with db_lock: conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor(); c.execute("SELECT * FROM telegram_bots"); rows = c.fetchall(); conn.close()
    return [dict(r) for r in rows]

def add_bot_db(name, token):
    with db_lock: conn = sqlite3.connect(DB_PATH); c = conn.cursor(); c.execute("INSERT INTO telegram_bots (bot_name, bot_token) VALUES (?, ?)", (name, token)); conn.commit(); conn.close()

def delete_bot_db(bid):
    with db_lock: conn = sqlite3.connect(DB_PATH); c = conn.cursor(); c.execute("DELETE FROM telegram_bots WHERE id=?", (bid,)); conn.commit(); conn.close()

def get_apis():
    with db_lock: conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; c = conn.cursor(); c.execute("SELECT * FROM apis"); rows = c.fetchall(); conn.close()
    return [dict(r) for r in rows]

def add_api_db(name, url, field):
    with db_lock: conn = sqlite3.connect(DB_PATH); c = conn.cursor(); c.execute("INSERT INTO apis (name, url, balance_field) VALUES (?, ?, ?)", (name, url, field)); nid = c.lastrowid; conn.commit(); conn.close(); return nid

def delete_api_db(aid):
    with db_lock: conn = sqlite3.connect(DB_PATH); c = conn.cursor(); c.execute("DELETE FROM apis WHERE id=?", (aid,)); c.execute("DELETE FROM balance_history WHERE api_id=?", (aid,)); conn.commit(); conn.close()

def update_api_state(aid, bal, chg):
    with db_lock: conn = sqlite3.connect(DB_PATH); c = conn.cursor(); c.execute("UPDATE apis SET last_balance=?, last_change=? WHERE id=?", (bal, chg, aid)); conn.commit(); conn.close()

def log_transaction(aid, name, ts, chg, new_bal):
    with db_lock: conn = sqlite3.connect(DB_PATH); c = conn.cursor(); c.execute("INSERT INTO balance_history (api_id, name, timestamp, change_amount, new_balance) VALUES (?, ?, ?, ?, ?)", (aid, name, ts, chg, new_bal)); conn.commit(); conn.close()

def wipe_table(table):
    with db_lock: conn = sqlite3.connect(DB_PATH); c = conn.cursor(); c.execute(f"DELETE FROM {table}"); conn.commit(); conn.close()

# =========================
# LOGIC XỬ LÝ (BALANCE)
# =========================
def _get_by_path(data, path):
    if not path: return None
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict): cur = cur.get(part)
        else: return None
    return cur

def extract_balance_auto(data, field):
    try:
        if field:
            val = _get_by_path(data, field)
            if val is not None: return float(str(val).replace(",",""))
        candidates = ["balance", "data.balance", "user.balance", "sodu", "money"]
        for c in candidates:
            val = _get_by_path(data, c)
            if val is not None: return float(str(val).replace(",",""))
    except: pass
    return None

def send_telegram(tokens, chat_id, text):
    if not chat_id: return
    for t in tokens:
        try: requests.post(f"https://api.telegram.org/bot{t}/sendMessage", data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=5)
        except: pass

# =========================
# AUTO RESTORE (LOGIC CHÍNH)
# =========================
def process_restore_json_data(payload: dict, wipe: bool = True):
    """Hàm xử lý dữ liệu JSON để nạp vào DB"""
    if wipe:
        wipe_table("telegram_bots")
        wipe_table("apis")
        wipe_table("balance_history")

    settings = payload.get("settings", {})
    # Các key cần restore (bao gồm Ping)
    keys = ["default_chat_id", "default_bot_id", "poll_interval", "global_threshold", "ping_url", "ping_interval"]
    for k in keys:
        if k in settings:
            set_setting(k, str(settings.get(k) if settings.get(k) is not None else ""))

    for b in payload.get("bots", []):
        try: add_bot_db(b.get("bot_name"), b.get("bot_token"))
        except: pass

    id_map = {}
    for a in payload.get("apis", []):
        try:
            old_id = a.get("id")
            new_id = add_api_db(a.get("name"), a.get("url"), a.get("balance_field"))
            if old_id: id_map[old_id] = new_id
            if a.get("last_balance") is not None:
                update_api_state(new_id, float(a["last_balance"]), a.get("last_change"))
        except: pass
    
    for h in payload.get("history", []):
        try:
            nid = id_map.get(h.get("api_id"))
            if nid: log_transaction(nid, h.get("name"), h.get("timestamp"), h.get("change_amount"), h.get("new_balance"))
        except: pass

# TỰ ĐỘNG CHẠY KHI KHỞI ĐỘNG
auto_restore_status_msg = "Chưa chạy"
def attempt_auto_restore():
    global auto_restore_status_msg
    if not os.path.exists(AUTO_BACKUP_PATH):
        auto_restore_status_msg = "Không tìm thấy file backup (/etc/secrets/...)"
        print(f"Auto Restore: File not found at {AUTO_BACKUP_PATH}")
        return

    try:
        with open(AUTO_BACKUP_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Auto restore luôn wipe dữ liệu rác để nạp chuẩn từ file
        process_restore_json_data(data, wipe=True) 
        auto_restore_status_msg = "Success"
        print("Auto Restore: Successfully loaded data from Secret file.")
    except Exception as e:
        auto_restore_status_msg = f"Error: {str(e)}"
        print(f"Auto Restore Failed: {e}")

# =========================
# THREADS (WATCHER + PINGER)
# =========================
def watcher_loop():
    global watcher_running
    watcher_running = True
    while True:
        try:
            settings = get_settings()
            poll = to_float(settings.get("poll_interval"), POLL_INTERVAL_DEFAULT)
            if poll < 5: poll = 5
            
            apis = get_apis()
            bots = get_bots()
            chat_id = settings.get("default_chat_id")
            threshold = to_float(settings.get("global_threshold"))
            tokens = [b["bot_token"] for b in bots]
            
            set_setting("last_run", datetime.utcnow().isoformat()+"Z")

            for api in apis:
                try:
                    r = requests.get(api["url"], timeout=10)
                    if r.status_code != 200: continue
                    new_bal = extract_balance_auto(r.json(), api["balance_field"])
                    if new_bal is None: continue
                    
                    old_bal = api["last_balance"]
                    now_str = datetime.utcnow().isoformat()+"Z"
                    
                    if old_bal is None:
                        update_api_state(api["id"], new_bal, now_str)
                    else:
                        diff = new_bal - old_bal
                        if abs(diff) > 0:
                            log_transaction(api["id"], api["name"], now_str, diff, new_bal)
                            msg = f"{'💰 NẠP' if diff > 0 else '🔻 THANH TOÁN'}: {api['name']}\nSố tiền: {fmt_amount(diff)}\nSố dư: {fmt_amount(new_bal)}"
                            send_telegram(tokens, chat_id, msg)
                            update_api_state(api["id"], new_bal, now_str)
                        
                        if threshold and old_bal >= threshold and new_bal < threshold:
                            send_telegram(tokens, chat_id, f"🚨 CẢNH BÁO: {api['name']} xuống dưới mức {fmt_amount(threshold)}!")
                            
                except: pass
            time.sleep(poll)
        except: time.sleep(POLL_INTERVAL_DEFAULT)

# PING WEB ĐỂ KHÔNG BỊ DOWN
def pinger_loop():
    global pinger_started
    pinger_started = True
    while True:
        try:
            settings = get_settings()
            url = settings.get("ping_url")
            interval_min = to_float(settings.get("ping_interval"), PING_INTERVAL_DEFAULT)
            if interval_min < 1: interval_min = 1
            
            if url:
                try: requests.get(url, timeout=10)
                except: pass
            
            time.sleep(interval_min * 60) # Đổi ra giây
        except: time.sleep(600)

def start_threads():
    global watcher_started
    if not watcher_started:
        watcher_started = True
        threading.Thread(target=watcher_loop, daemon=True).start()
        threading.Thread(target=pinger_loop, daemon=True).start()

# =========================
# ROUTES
# =========================
@app.route("/", methods=["GET"])
def dashboard():
    if not session.get("logged_in"): return redirect(url_for("login"))
    start_threads()
    
    settings_raw = get_settings()
    class Obj: pass
    settings = Obj()
    for k,v in settings_raw.items(): setattr(settings, k, v)
    
    last_run = parse_iso_utc(getattr(settings, 'last_run', ''))
    
    # Truyền biến ping_active ra template
    return render_template_string(
        DASHBOARD_TEMPLATE,
        title=APP_TITLE,
        bots=get_bots(),
        apis=[dict(a, last_change_vn=fmt_time_label_vn(parse_iso_utc(a['last_change']))) for a in get_apis()],
        settings=settings,
        last_run_vn=fmt_time_label_vn(last_run) if last_run else "Chưa chạy",
        auto_restore_status=auto_restore_status_msg,
        ping_active=bool(getattr(settings, 'ping_url', ''))
    )

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        flash("Sai mật khẩu", "error")
    return render_template_string(LOGIN_TEMPLATE, title=APP_TITLE)

@app.route("/save_settings", methods=["POST"])
def save_settings():
    form = request.form
    set_setting("default_chat_id", form.get("default_chat_id", ""))
    set_setting("poll_interval", form.get("poll_interval", ""))
    set_setting("global_threshold", form.get("global_threshold", ""))
    # Lưu cấu hình Ping
    set_setting("ping_url", form.get("ping_url", ""))
    set_setting("ping_interval", form.get("ping_interval", ""))
    
    flash("Đã lưu cấu hình", "ok")
    return redirect(url_for("dashboard"))

@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("login"))

@app.route("/add_bot", methods=["POST"])
def add_bot():
    add_bot_db(request.form.get("bot_name"), request.form.get("bot_token"))
    return redirect(url_for("dashboard"))

@app.route("/delete_bot", methods=["POST"])
def delete_bot():
    delete_bot_db(request.form.get("bot_id"))
    return redirect(url_for("dashboard"))

@app.route("/add_api", methods=["POST"])
def add_api():
    add_api_db(request.form.get("name"), request.form.get("url"), request.form.get("balance_field"))
    return redirect(url_for("dashboard"))

@app.route("/delete_api/<int:api_id>", methods=["POST"])
def delete_api(api_id):
    delete_api_db(api_id)
    return redirect(url_for("dashboard"))

@app.route("/download_backup")
def download_backup():
    import json
    data = {"settings": get_settings(), "bots": get_bots(), "apis": get_apis(), "history": []}
    return Response(json.dumps(data, ensure_ascii=False, indent=2), mimetype="application/json", headers={"Content-Disposition": 'attachment; filename="backup.json"'})

@app.route("/download_apis")
def download_apis():
    import json
    return Response(json.dumps(get_apis(), ensure_ascii=False, indent=2), mimetype="application/json", headers={"Content-Disposition": 'attachment; filename="apis.json"'})

@app.route("/restore_backup", methods=["POST"])
def restore_backup():
    f = request.files.get("backup_file")
    if f:
        try:
            data = json.load(f)
            process_restore_json_data(data, wipe=(request.form.get("wipe")=="1"))
            flash("Restore thành công", "ok")
        except Exception as e: flash(f"Lỗi: {e}", "error")
    return redirect(url_for("dashboard"))

# =========================
# MAIN INIT
# =========================
def init_and_run():
    init_db()
    attempt_auto_restore() # Chạy ngay khi khởi động để lấy lại dữ liệu từ Secret File
    start_threads()

if __name__ == "__main__":
    init_and_run()
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
