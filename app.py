import os
import sqlite3
import threading
import time
import json
from datetime import datetime
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
    send_file,
)
from functools import wraps

# =========================
# CẤU HÌNH CƠ BẢN
# =========================

APP_TITLE = "Balance Watcher Universe"

# Một pass duy nhất:
# - ADMIN_PASSWORD: dùng để login
# - SECRET_KEY: nếu không set riêng thì dùng luôn ADMIN_PASSWORD
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
SECRET_KEY = os.getenv("SECRET_KEY", ADMIN_PASSWORD)

# DB path (Render dùng /data cho persistent)
DATA_DIR = "/data"
if not os.path.isdir(DATA_DIR):
    DATA_DIR = "."
DB_PATH = os.path.join(DATA_DIR, "balance_watcher.db")

# Mặc định nếu người dùng chưa nhập trong giao diện
POLL_INTERVAL_DEFAULT = 30  # giây

app = Flask(__name__)
app.secret_key = SECRET_KEY

db_lock = threading.Lock()
watcher_started = False
watcher_running = False

# =========================
# HELPERS: format tiền & thời gian & trích xuất số dư
# =========================

def fmt_amount(v: float) -> str:
    """1000000.0 -> 1,000,000đ"""
    try:
        return f"{float(v):,.0f}đ"
    except Exception:
        return f"{v}đ"

def fmt_time_label_utc(dt: datetime) -> str:
    """20:40 10/11/2025 (UTC)"""
    return dt.strftime("%H:%M %d/%m/%Y (UTC)")

def to_float(s: Optional[str], default: Optional[float] = None) -> Optional[float]:
    """Chuyển đổi string (có thể có dấu phẩy) sang float."""
    try:
        if s is None:
            return default
        s = str(s).replace(",", "").strip()
        return float(s)
    except Exception:
        return default

def _get_by_path(data: Any, path: str) -> Any:
    """Truy cập giá trị lồng nhau trong dict/list bằng path (ví dụ: 'data.balance')."""
    if not path:
        return None
    cur = data
    for part in str(path).split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            try:
                cur = cur[int(part)]
            except IndexError:
                return None
        else:
            return None
        if cur is None:
            return None
    return cur

def extract_balance(json_data: Dict[str, Any], balance_field: str) -> Optional[float]:
    """Trích xuất số dư từ JSON, sử dụng balance_field hoặc tự động tìm."""
    if balance_field:
        value = _get_by_path(json_data, balance_field)
        return to_float(value)

    common_paths = [
        "balance", "data.balance", "user.balance", "profile.balance", 
        "result.balance", "wallet.balance", "amount", "data.amount", 
        "data.money", "money",
    ]
    for path in common_paths:
        value = _get_by_path(json_data, path)
        if value is not None:
            float_value = to_float(value)
            if float_value is not None:
                return float_value
    
    return None

# =========================
# TEMPLATES (Đã cập nhật phần Backup & Restore)
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
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif;
        }
    </style>
</head>
<body class="flex items-center justify-center">
    <div class="max-w-md w-full mx-4">
        <div class="bg-slate-900/80 border border-slate-700/80 rounded-3xl shadow-2xl p-8 backdrop-blur-xl relative overflow-hidden">
            <div class="absolute -top-10 -right-10 w-32 h-32 bg-indigo-500/20 rounded-full blur-3xl"></div>
            <div class="absolute -bottom-16 -left-10 w-40 h-40 bg-fuchsia-500/10 rounded-full blur-3xl"></div>

            <div class="flex items-center gap-3 mb-2 relative z-10">
                <div class="w-8 h-8 rounded-full bg-gradient-to-tr from-indigo-400 via-sky-400 to-fuchsia-400 flex items-center justify-center text-white text-xl shadow-lg">
                    ∞
                </div>
                <div>
                    <div class="text-xs uppercase tracking-[0.18em] text-slate-400">Quantum Security Gate</div>
                    <div class="text-sm text-slate-500 flex items-center gap-2">
                        Bot được bảo dưỡng & phát triển bởi
                        <span class="font-semibold text-cyan-400">Admin Văn Linh</span>
                        <span class="w-4 h-4 rounded-full bg-gradient-to-tr from-sky-400 to-blue-600 flex items-center justify-center text-[10px] text-white shadow-lg">✓</span>
                    </div>
                </div>
            </div>

            <h1 class="mt-4 text-2xl font-semibold text-slate-50 tracking-tight">
                Đăng nhập bảng điều khiển số dư
            </h1>
            <p class="mt-1 text-sm text-slate-400">
                Nhập mật khẩu quản trị để truy cập Balance Watcher Universe.
            </p>

            {% with messages = get_flashed_messages(with_categories=true) %}
              {% if messages %}
                <div class="mt-4 space-y-2">
                  {% for category, message in messages %}
                    <div class="px-3 py-2 rounded-2xl text-xs
                        {% if category == 'error' %}bg-red-900/60 text-red-200 border border-red-500/40
                        {% else %}bg-emerald-900/40 text-emerald-200 border border-emerald-500/30{% endif %}">
                      {{ message | safe }}
                    </div>
                  {% endfor %}
                </div>
              {% endif %}
            {% endwith %}

            <form method="post" class="mt-5 space-y-3 relative z-10">
                <label class="block text-xs font-medium text-slate-400 mb-1">
                    Mật khẩu Admin
                </label>
                <input
                    type="password"
                    name="password"
                    required
                    placeholder="ADMIN_PASSWORD trên Render"
                    class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-slate-100 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-400 placeholder-slate-500 shadow-inner"
                />
                <button
                    type="submit"
                    class="w-full mt-2 inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-2xl bg-gradient-to-r from-indigo-500 via-sky-500 to-fuchsia-500 text-white text-sm font-medium shadow-xl hover:shadow-2xl hover:-translate-y-0.5 transition-all"
                >
                    🚀 Vào Dashboard Vũ Trụ
                </button>
            </form>
        </div>
    </div>
</body>
</html>
"""

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
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif;
            background-color: #020817;
            background-image:
                radial-gradient(circle at 0 0, rgba(129, 140, 248, 0.18), transparent 55%),
                radial-gradient(circle at 100% 0, rgba(45, 212, 191, 0.10), transparent 55%),
                radial-gradient(circle at 100% 100%, rgba(236, 72, 153, 0.10), transparent 55%);
            min-height: 100vh;
        }
        .scrollbar-thin::-webkit-scrollbar { height:5px; width:5px; }
        .scrollbar-thin::-webkit-scrollbar-thumb { background-color:rgba(148,163,253,0.4); border-radius:999px; }
        .scrollbar-thin::-webkit-scrollbar-track { background-color:transparent; }
    </style>
</head>
<body class="text-slate-100">
<div class="min-h-screen px-4 py-6 md:px-8 md:py-8">
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        <div class="max-w-6xl mx-auto mb-4 space-y-2">
          {% for category, message in messages %}
            <div class="px-4 py-2 rounded-2xl text-xs border
                {% if category == 'error' %}bg-red-900/60 text-red-200 border-red-500/40
                {% else %}bg-emerald-900/40 text-emerald-200 border-emerald-500/30{% endif %}">
              {{ message | safe }}
            </div>
          {% endfor %}
        </div>
      {% endif %}
    {% endwith %}

    <div class="max-w-6xl mx-auto mb-5 flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        <div>
            <div class="flex items-center gap-3">
                <div class="w-9 h-9 rounded-full bg-gradient-to-tr from-indigo-400 via-sky-400 to-fuchsia-400 flex items-center justify-center text-white text-2xl shadow-lg">
                    ∞
                </div>
                <div>
                    <div class="text-[10px] uppercase tracking-[0.18em] text-slate-400">
                        Balance Watcher Universe
                    </div>
                    <div class="flex items-center gap-2 text-[11px] text-slate-500">
                        Bot được bảo dưỡng &amp; phát triển bởi
                        <span class="font-semibold text-cyan-400">Admin Văn Linh</span>
                        <span class="w-4 h-4 rounded-full bg-gradient-to-tr from-sky-400 to-blue-600 flex items-center justify-center text-[10px] text-white shadow-lg">✓</span>
                    </div>
                </div>
            </div>
            <h1 class="mt-3 text-3xl font-semibold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-indigo-300 via-sky-300 to-fuchsia-300">
                Quantum Balance Monitor Dashboard
            </h1>
            <p class="mt-1 text-xs text-slate-400 max-w-xl">
                Theo dõi biến động số dư nhiều website, phân loại tự động
                <span class="text-emerald-400 font-semibold">CỘNG TIỀN</span> /
                <span class="text-rose-400 font-semibold">THANH TOÁN</span> và gửi cảnh báo tức thời về Telegram.
            </p>
        </div>
        <div class="flex flex-col items-start md:items-end gap-1 text-[10px] text-slate-500">
            <div>Chu kỳ quét hiện tại:
                <span class="text-indigo-300 font-semibold">{{ effective_poll_interval }} giây</span>
            </div>
            <div>Ngưỡng cảnh báo chung:
                {% if global_threshold is not none %}
                    <span class="text-rose-300 font-semibold">{{ "{:,.0f}".format(global_threshold|float) }}đ</span>
                {% else %}
                    <span class="text-slate-400">chưa đặt</span>
                {% endif %}
            </div>
            <div>Trạng thái watcher:
                {% if watcher_running %}
                    <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-900/60 text-emerald-300 text-[10px]">
                        <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span> Đang chạy
                    </span>
                {% else %}
                    <span class="inline-flex items-center px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 text-[10px]">
                        Tạm dừng
                    </span>
                {% endif %}
            </div>
            <div>
                <a href="{{ url_for('logout') }}" class="text-slate-500 hover:text-fuchsia-400 transition text-[10px]">
                    Đăng xuất
                </a>
            </div>
        </div>
    </div>

    <div class="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-3 gap-5 items-start">
        <div class="space-y-5">
            <div class="bg-slate-900/80 border border-slate-800 rounded-3xl p-5 shadow-2xl backdrop-blur-xl">
                <div class="flex items-center justify-between gap-2 mb-3">
                    <h2 class="text-sm font-semibold text-indigo-300 uppercase tracking-[0.16em]">Cài đặt chung</h2>
                    <span class="px-2 py-0.5 rounded-full bg-slate-800/90 text-[9px] text-slate-400">
                        Telegram: 1 Chat ID, nhiều Bot Token
                    </span>
                </div>
                <form method="post" action="{{ url_for('save_settings') }}" class="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div class="md:col-span-2">
                        <label class="block text-[10px] text-slate-400 mb-1">TELEGRAM_CHAT_ID (nhận cảnh báo)</label>
                        <input type="text" name="default_chat_id"
                            value="{{ settings.default_chat_id or '' }}"
                            placeholder="VD: 123456789 hoặc -100123456789"
                            class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-400">
                    </div>

                    <div>
                        <label class="block text-[10px] text-slate-400 mb-1">Bot mặc định để gửi (tuỳ chọn)</label>
                        <select name="default_bot_id"
                            class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-400">
                            <option value="">-- Gửi bằng TẤT CẢ bot --</option>
                            {% for bot in bots %}
                                <option value="{{ bot.id }}" {% if settings.default_bot_id and settings.default_bot_id == bot.id|string %}selected{% endif %}>
                                    {{ bot.bot_name }} (..{{ bot.bot_token[-6:] }})
                                </option>
                            {% endfor %}
                        </select>
                    </div>

                    <div>
                        <label class="block text-[10px] text-slate-400 mb-1">Chu kỳ quét (giây)</label>
                        <input type="text" name="poll_interval"
                            value="{{ settings.poll_interval or '' }}"
                            placeholder="VD: 15, 30, 60..."
                            class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-400">
                    </div>

                    <div>
                        <label class="block text-[10px] text-slate-400 mb-1">Ngưỡng cảnh báo chung (VND)</label>
                        <input type="text" name="global_threshold"
                            value="{{ settings.global_threshold or '' }}"
                            placeholder="VD: 1,000,000 (bỏ trống nếu không cảnh báo)"
                            class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-rose-500 focus:border-rose-400">
                    </div>

                    <div class="md:col-span-2">
                        <button type="submit"
                            class="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-2xl bg-gradient-to-r from-indigo-500 via-sky-500 to-fuchsia-500 text-white text-[11px] font-medium shadow-lg hover:-translate-y-0.5 hover:shadow-xl transition-all">
                            💾 Lưu cấu hình
                        </button>
                    </div>
                </form>
            </div>

            <div class="bg-slate-900/80 border border-slate-800 rounded-3xl p-5 shadow-2xl backdrop-blur-xl">
                <div class="flex items-center justify-between mb-3">
                    <h2 class="text-sm font-semibold text-cyan-300 uppercase tracking-[0.16em]">Quản lý Bot Telegram</h2>
                </div>
                <form method="post" action="{{ url_for('add_bot') }}" class="space-y-3 mb-4">
                    <div>
                        <label class="block text-[10px] text-slate-400 mb-1">Tên bot (hiển thị)</label>
                        <input type="text" name="bot_name" required
                            placeholder="VD: Bot Cảnh báo chính"
                            class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-cyan-400">
                    </div>
                    <div>
                        <label class="block text-[10px] text-slate-400 mb-1">Token bot</label>
                        <input type="text" name="bot_token" required
                            placeholder="123456:ABC-DEF..."
                            class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-cyan-500 focus:border-cyan-400">
                    </div>
                    <button type="submit"
                        class="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-2xl bg-gradient-to-r from-emerald-500 to-teal-500 text-white text-[11px] font-medium shadow-lg hover:-translate-y-0.5 hover:shadow-xl transition-all">
                        ➕ Thêm Bot
                    </button>
                </form>
                <div class="space-y-2 max-h-40 overflow-y-auto scrollbar-thin">
                    {% for bot in bots %}
                    <div class="flex items-center justify-between px-3 py-2 rounded-2xl bg-slate-950/70 border border-slate-800 text-[10px]">
                        <div class="flex flex-col">
                            <span class="text-slate-100 font-medium">{{ bot.bot_name }}</span>
                            <span class="text-slate-500 text-[9px]">...{{ bot.bot_token[-12:] }}</span>
                        </div>
                        <div class="flex items-center gap-2">
                            <form method="post" action="{{ url_for('test_bot') }}">
                                <input type="hidden" name="bot_id" value="{{ bot.id }}">
                                <button class="px-2 py-1 rounded-xl bg-slate-800 text-cyan-300 hover:bg-cyan-600/20 hover:text-cyan-200 text-[9px]">
                                    Test
                                </button>
                            </form>
                            <form method="post" action="{{ url_for('delete_bot') }}"
                                    onsubmit="return confirm('Xoá bot {{ bot.bot_name }}?');">
                                <input type="hidden" name="bot_id" value="{{ bot.id }}">
                                <button class="px-2 py-1 rounded-xl bg-slate-900 text-rose-400 hover:bg-rose-600/20 hover:text-rose-300 text-[9px]">
                                    Xoá
                                </button>
                            </form>
                        </div>
                    </div>
                    {% else %}
                    <div class="text-[9px] text-slate-500">
                        Chưa có bot nào. Thêm ít nhất 1 bot để bắt đầu gửi cảnh báo.
                    </div>
                    {% endfor %}
                </div>
            </div>

            <div class="bg-slate-900/80 border border-slate-800 rounded-3xl p-5 shadow-2xl backdrop-blur-xl">
                <div class="flex items-center justify-between mb-3">
                    <h2 class="text-sm font-semibold text-fuchsia-300 uppercase tracking-[0.16em]">Backup & Restore</h2>
                </div>
                <p class="text-[10px] text-slate-400 mb-3">
                    Tải xuống toàn bộ cấu hình (bots, API, settings) để lưu trữ an toàn hoặc khôi phục lại.
                </p>
                <div class="space-y-3">
                    <a href="{{ url_for('download_backup') }}"
                       class="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-2xl bg-slate-800 text-slate-100 text-[11px] border border-slate-600 hover:bg-slate-700 hover:border-fuchsia-500/60 hover:text-fuchsia-200 transition-all">
                        📦 Tải file backup (.json)
                    </a>
                    
                    <form method="post" action="{{ url_for('upload_restore') }}" enctype="multipart/form-data" 
                        onsubmit="return confirm('⚠️ CẢNH BÁO: Thao tác này sẽ XÓA TOÀN BỘ cấu hình hiện tại và khôi phục từ file. Bạn có chắc chắn?');">
                        <label class="block text-[10px] text-slate-400 mb-1">Upload file backup (.json)</label>
                        <input type="file" name="backup_file" required accept=".json"
                            class="w-full text-[11px] text-slate-400 file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:text-white file:font-medium file:bg-slate-700 hover:file:bg-indigo-600 cursor-pointer">
                        <button type="submit"
                            class="w-full mt-3 inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-2xl bg-rose-700 text-white text-[11px] font-medium shadow-lg hover:bg-rose-600 transition-all">
                            🔄 Khôi phục từ Backup
                        </button>
                    </form>
                </div>
            </div>
        </div>

        <div class="lg:col-span-2 space-y-5">
            <div class="bg-slate-900/80 border border-slate-800 rounded-3xl p-5 shadow-2xl backdrop-blur-xl">
                <div class="flex items-center justify-between gap-2 mb-3">
                    <h2 class="text-sm font-semibold text-sky-300 uppercase tracking-[0.16em]">Thêm API số dư</h2>
                    <span class="px-2 py-0.5 rounded-full bg-slate-800/90 text-[9px] text-slate-400">
                        Hỗ trợ nhiều website khác nhau
                    </span>
                </div>
                <form method="post" action="{{ url_for('add_api') }}" class="grid grid-cols-1 md:grid-cols-2 gap-3 text-[10px]">
                    <div>
                        <label class="block text-slate-400 mb-1">Tên hiển thị</label>
                        <input type="text" name="name" required
                            placeholder="VD: ShopAccMMO chính"
                            class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-400">
                    </div>
                    <div>
                        <label class="block text-slate-400 mb-1">URL API kiểm tra số dư</label>
                        <input type="text" name="url" required
                            placeholder="https://.../api/profile.php?api_key=XXXX"
                            class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-400">
                    </div>
                    <div>
                        <label class="block text-slate-400 mb-1">Trường số dư trong JSON</label>
                        <input type="text" name="balance_field"
                            placeholder="Để trống = auto detect (balance / data.balance / ...)"
                            class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-400">
                    </div>
                    <div class="flex items-end">
                        <button type="submit"
                            class="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-2xl bg-gradient-to-r from-sky-500 to-indigo-500 text-white text-[11px] font-medium shadow-lg hover:-translate-y-0.5 hover:shadow-xl transition-all">
                            ➕ Thêm API
                        </button>
                    </div>
                </form>
            </div>

            <div class="bg-slate-900/80 border border-slate-800 rounded-3xl p-5 shadow-2xl backdrop-blur-xl">
                <div class="flex items-center justify-between mb-3">
                    <h2 class="text-sm font-semibold text-indigo-300 uppercase tracking-[0.16em]">Danh sách API đang theo dõi</h2>
                    <span class="text-[9px] text-slate-500">
                        Lần chạy gần nhất: <span class="text-sky-300">{{ last_run or 'chưa có' }}</span>
                    </span>
                </div>
                <div class="overflow-x-auto scrollbar-thin">
                    <table class="min-w-full text-[10px]">
                        <thead class="bg-slate-950/80">
                            <tr>
                                <th class="px-3 py-2 text-left text-slate-400 uppercase tracking-[0.14em]">ID</th>
                                <th class="px-3 py-2 text-left text-slate-400 uppercase tracking-[0.14em]">Tên</th>
                                <th class="px-3 py-2 text-left text-slate-400 uppercase tracking-[0.14em]">URL</th>
                                <th class="px-3 py-2 text-left text-slate-400 uppercase tracking-[0.14em]">Trường</th>
                                <th class="px-3 py-2 text-left text-slate-400 uppercase tracking-[0.14em]">Số dư gần nhất</th>
                                <th class="px-3 py-2 text-left text-slate-400 uppercase tracking-[0.14em]">Cập nhật</th>
                                <th class="px-3 py-2 text-right text-slate-400 uppercase tracking-[0.14em]"></th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-slate-800">
                            {% for api in apis %}
                            <tr class="hover:bg-slate-800/80 transition-colors">
                                <td class="px-3 py-2 text-slate-400">#{{ api.id }}</td>
                                <td class="px-3 py-2 text-slate-100 font-medium">{{ api.name }}</td>
                                <td class="px-3 py-2 text-slate-500 max-w-[220px] truncate">{{ api.url }}</td>
                                <td class="px-3 py-2 text-slate-400">{{ api.balance_field or 'auto' }}</td>
                                <td class="px-3 py-2">
                                    {% if api.last_balance is not none %}
                                        <span class="inline-flex px-2 py-0.5 rounded-full bg-emerald-900/40 text-emerald-300">
                                            {{ "{:,.0f}".format(api.last_balance|float) }}đ
                                        </span>
                                    {% else %}
                                        <span class="inline-flex px-2 py-0.5 rounded-full bg-slate-800 text-slate-400">
                                            chưa có
                                        </span>
                                    {% endif %}
                                </td>
                                <td class="px-3 py-2 text-slate-500">
                                    {{ api.last_change or '-' }}
                                </td>
                                <td class="px-3 py-2 text-right">
                                    <form method="post" action="{{ url_for('delete_api', api_id=api.id) }}"
                                            onsubmit="return confirm('Xoá API {{ api.name }} khỏi danh sách theo dõi?');">
                                        <button class="px-2 py-1 rounded-xl bg-slate-950 text-rose-400 hover:bg-rose-600/20 hover:text-rose-300">
                                            ✖
                                        </button>
                                    </form>
                                </td>
                            </tr>
                            {% else %}
                            <tr>
                                <td colspan="7" class="px-3 py-4 text-center text-slate-500 text-[10px]">
                                    Chưa có API nào. Thêm ít nhất một API để bắt đầu giám sát.
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
</div>
</body>
</html>
"""

# =========================
# DB HELPER
# =========================

def init_db():
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("""
        CREATE TABLE IF NOT EXISTS telegram_bots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_name TEXT NOT NULL,
            bot_token TEXT NOT NULL UNIQUE
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)

        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('default_chat_id', '')")
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('default_bot_id', '')")
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_run', '')")
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('poll_interval', '')")
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('global_threshold', '')")

        c.execute("""
        CREATE TABLE IF NOT EXISTS apis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            balance_field TEXT NOT NULL,
            last_balance INTEGER,  
            last_change TEXT
        )
        """)

        conn.commit()
        conn.close()

def get_settings() -> Dict[str, Optional[str]]:
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT key, value FROM settings")
        rows = c.fetchall()
        conn.close()
    return {k: (v if v is not None else "") for k, v in rows}

def set_setting(key: str, value: str):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.commit()
        conn.close()

def get_bots() -> List[Dict[str, Any]]:
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM telegram_bots ORDER BY id")
        rows = c.fetchall()
        conn.close()
    return [dict(r) for r in rows]

def get_apis() -> List[Dict[str, Any]]:
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM apis ORDER BY id")
        rows = c.fetchall()
        conn.close()
    return [dict(r) for r in rows]

def add_bot_db(name: str, token: str):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO telegram_bots (bot_name, bot_token) VALUES (?, ?)", (name, token))
        conn.commit()
        conn.close()

def delete_bot_db(bot_id: int):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM telegram_bots WHERE id=?", (bot_id,))
        conn.commit()
        conn.close()

def add_api_db(name: str, url: str, balance_field: str):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT INTO apis (name, url, balance_field, last_balance, last_change) "
            "VALUES (?, ?, ?, NULL, NULL)",
            (name, url, balance_field or ""),
        )
        conn.commit()
        conn.close()

def delete_api_db(api_id: int):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM apis WHERE id=?", (api_id,))
        conn.commit()
        conn.close()

def update_api_state(api_id: int, balance: float, changed_at: str):
    """Lưu số dư dưới dạng INTEGER (số nguyên) để tránh lỗi dấu phẩy động."""
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Chuyển số dư float sang integer (bỏ phần thập phân) trước khi lưu
        int_balance = int(balance) 
        
        c.execute(
            "UPDATE apis SET last_balance=?, last_change=? WHERE id=?",
            (int_balance, changed_at, api_id),
        )
        conn.commit()
        conn.close()

def clear_all_data():
    """Xóa tất cả dữ liệu trong bảng apis và telegram_bots, và reset settings."""
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # Xóa dữ liệu cũ
        c.execute("DELETE FROM apis")
        c.execute("DELETE FROM telegram_bots")
        c.execute("DELETE FROM settings WHERE key NOT IN ('admin_password_hash', 'secret_key')") # Giữ lại key quan trọng nếu có
        
        # Reset lại các settings mặc định
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('default_chat_id', '')")
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('default_bot_id', '')")
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('last_run', '')")
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('poll_interval', '')")
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('global_threshold', '')")
        
        conn.commit()
        conn.close()

# =========================
# TELEGRAM NOTIFIER
# =========================

def send_telegram_message(token: str, chat_id: str, message: str) -> bool:
    """Gửi tin nhắn Telegram và trả về True nếu thành công."""
    if not token or not chat_id or not message:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": "True",
    }
    
    try:
        response = requests.post(url, data=payload, timeout=10)
        response.raise_for_status()
        return response.json().get('ok', False)
    except requests.exceptions.RequestException as e:
        print(f"Lỗi gửi Telegram (Bot ...{token[-6:]}): {e}")
        return False

def notify_change(api: Dict[str, Any], change: int, new_balance: float, settings: Dict[str, Optional[str]], bots: List[Dict[str, Any]]):
    """Gửi thông báo khi số dư thay đổi đáng kể."""
    
    global_threshold = to_float(settings.get('global_threshold')) or 0.0
    
    if abs(change) < global_threshold:
        return

    if not settings.get('default_chat_id') or not bots:
        print("Bỏ qua cảnh báo: Thiếu Chat ID hoặc Bot Token.")
        return

    chat_id = settings['default_chat_id']
    
    if change > 0:
        change_type = "💰 CỘNG TIỀN (Deposit)"
        change_color = "🟢"
        emoji = "✨"
    else:
        change_type = "💸 THANH TOÁN (Payment/Withdraw)"
        change_color = "🔴"
        emoji = "⚠️"

    # Lấy old_balance bằng cách trừ change (số nguyên) khỏi new_balance (số float)
    old_balance_float = new_balance - change

    message = f"""{emoji} <b>BALANCE WATCHER ALERT</b> {emoji}
---
<b>Trang web:</b> <code>{api['name']}</code>
<b>Phân loại:</b> {change_type}

<b>Biến động:</b> {change_color} <b>{fmt_amount(float(change))}</b>
<b>Số dư cũ:</b> {fmt_amount(old_balance_float)}
<b>Số dư mới:</b> {fmt_amount(new_balance)}

<b>Thời gian (UTC):</b> {fmt_time_label_utc(datetime.utcnow())}
"""
    
    bots_to_send = []
    if settings.get('default_bot_id'):
        default_bot = next((b for b in bots if b['id'] == int(settings['default_bot_id'])), None)
        if default_bot:
            bots_to_send.append(default_bot)
        else:
            bots_to_send = bots
    else:
        bots_to_send = bots
        
    for bot in bots_to_send:
        success = send_telegram_message(bot['bot_token'], chat_id, message)
        if not success:
            print(f"Lỗi gửi cảnh báo bằng bot: {bot['bot_name']}")

# =========================
# WATCHER CORE LOGIC
# =========================

def check_balances():
    """Kiểm tra số dư tất cả API và cập nhật/cảnh báo."""
    settings = get_settings()
    apis = get_apis()
    bots = get_bots()
    
    run_time = datetime.utcnow().strftime("%H:%M:%S %d/%m")
    set_setting('last_run', run_time)
    
    global_threshold_val = settings.get('global_threshold') or '0'
    print(f"[{run_time}] Bắt đầu chu kỳ quét ({len(apis)} API) - Threshold: {global_threshold_val}đ")

    for api in apis:
        try:
            # 1. Gọi API
            response = requests.get(api['url'], timeout=15)
            response.raise_for_status()
            json_data = response.json()

            # 2. Trích xuất số dư (vẫn là float để giữ độ chính xác tối đa)
            new_balance = extract_balance(json_data, api['balance_field'])

            if new_balance is None:
                continue
            
            new_balance = float(new_balance)
            
            # 3. So sánh và Cảnh báo
            old_balance_int = api.get('last_balance') # Lấy INTEGER từ DB
            
            if old_balance_int is not None:
                # Ép new_balance về INT để so sánh, loại bỏ sai số thập phân
                new_balance_int = int(new_balance) 
                
                change = new_balance_int - old_balance_int
                
                if abs(change) > 0:
                    print(f"💰 Phát hiện thay đổi trên {api['name']} ({api['last_balance']} -> {new_balance_int})")
                    # Dùng change (INT) và new_balance (FLOAT) để gửi thông báo
                    notify_change(api, change, new_balance, settings, bots)
            
            # 4. Cập nhật DB (Dùng giá trị float mới nhất)
            update_api_state(api['id'], new_balance, fmt_time_label_utc(datetime.utcnow()))

        except requests.exceptions.RequestException as e:
            print(f"❌ Lỗi HTTP/Network khi quét {api['name']}: {e}")
        except json.JSONDecodeError:
            print(f"❌ Lỗi JSON response từ {api['name']}")
        except Exception as e:
            print(f"❌ Lỗi không xác định khi xử lý {api['name']}: {e}")

    print(f"[{run_time}] Hoàn thành chu kỳ quét.")


def watcher_thread():
    """Luồng chạy nền của watcher."""
    global watcher_running
    print("Watcher thread started.")
    watcher_running = True
    
    while watcher_running:
        settings = get_settings()
        poll_interval = to_float(settings.get('poll_interval'))
        if not poll_interval or poll_interval < 5:
            poll_interval = POLL_INTERVAL_DEFAULT
            
        check_balances()
        
        print(f"Tạm dừng {int(poll_interval)} giây...")
        time.sleep(poll_interval)
    
    print("Watcher thread stopped.")


def start_watcher():
    """Bắt đầu luồng watcher nếu chưa chạy."""
    global watcher_started
    if not watcher_started:
        thread = threading.Thread(target=watcher_thread)
        thread.daemon = True
        thread.start()
        watcher_started = True

# =========================
# FLASK ROUTES
# =========================

def login_required(f):
    """Decorator kiểm tra đăng nhập."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("logged_in") != True:
            flash("Vui lòng đăng nhập để truy cập Dashboard.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

@app.route("/", methods=["GET", "POST"])
def login():
    """Route Đăng nhập."""
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        password = request.form.get("password")
        if password == ADMIN_PASSWORD:
            session["logged_in"] = True
            flash("Đăng nhập thành công! Chào mừng trở lại vũ trụ.", "success")
            if os.environ.get("FLASK_ENV") == "development":
                start_watcher()
            return redirect(url_for("dashboard"))
        else:
            flash("Mật khẩu quản trị không chính xác.", "error")

    return render_template_string(LOGIN_TEMPLATE, title=APP_TITLE)

@app.route("/logout")
def logout():
    """Route Đăng xuất."""
    session.pop("logged_in", None)
    flash("Bạn đã đăng xuất.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    """Route Dashboard chính."""
    settings = get_settings()
    bots = get_bots()
    apis = get_apis()

    poll_interval_db = to_float(settings.get('poll_interval'))
    effective_poll_interval = int(poll_interval_db) if poll_interval_db and poll_interval_db >= 5 else POLL_INTERVAL_DEFAULT
    
    global_threshold_val = to_float(settings.get('global_threshold'))

    return render_template_string(
        DASHBOARD_TEMPLATE,
        title=APP_TITLE,
        settings=settings,
        bots=bots,
        apis=apis,
        watcher_running=watcher_running,
        effective_poll_interval=effective_poll_interval,
        last_run=settings.get('last_run', 'chưa có'),
        global_threshold=global_threshold_val,
    )

@app.route("/save_settings", methods=["POST"])
@login_required
def save_settings():
    """Lưu cấu hình chung."""
    default_chat_id = request.form.get("default_chat_id", "").strip()
    default_bot_id = request.form.get("default_bot_id", "").strip()
    poll_interval = request.form.get("poll_interval", "").strip()
    global_threshold = request.form.get("global_threshold", "").strip()

    try:
        if poll_interval:
            interval_sec = to_float(poll_interval)
            if interval_sec is None or interval_sec < 5:
                 flash("Chu kỳ quét tối thiểu là **5 giây** và phải là số hợp lệ.", "error")
                 return redirect(url_for("dashboard"))
            poll_interval = str(int(interval_sec))
        
        if global_threshold:
            global_threshold = global_threshold.replace(",", "")
            if to_float(global_threshold) is None:
                flash("Ngưỡng cảnh báo không hợp lệ. Vui lòng nhập số (ví dụ: 1000000).", "error")
                return redirect(url_for("dashboard"))

        set_setting('default_chat_id', default_chat_id)
        set_setting('default_bot_id', default_bot_id)
        set_setting('poll_interval', poll_interval)
        set_setting('global_threshold', global_threshold)
        
        flash("💾 Cấu hình chung đã được lưu thành công! **Watcher sẽ áp dụng chu kỳ quét mới sau lần chạy hiện tại.**", "success")
        
    except Exception as e:
        flash(f"Lỗi khi lưu cấu hình: {e}", "error")

    return redirect(url_for("dashboard"))


@app.route("/add_bot", methods=["POST"])
@login_required
def add_bot():
    """Thêm bot Telegram mới."""
    bot_name = request.form.get("bot_name", "").strip()
    bot_token = request.form.get("bot_token", "").strip()

    if not bot_name or not bot_token:
        flash("Tên bot và Token bot không được để trống.", "error")
        return redirect(url_for("dashboard"))
        
    try:
        add_bot_db(bot_name, bot_token)
        flash(f"➕ Bot '<b>{bot_name}</b>' đã được thêm thành công!", "success")
    except sqlite3.IntegrityError:
        flash("Bot Token này đã tồn tại trong hệ thống.", "error")
    except Exception as e:
        flash(f"Lỗi khi thêm bot: {e}", "error")

    return redirect(url_for("dashboard"))


@app.route("/delete_bot", methods=["POST"])
@login_required
def delete_bot():
    """Xóa bot Telegram."""
    bot_id = request.form.get("bot_id", type=int)
    
    if bot_id:
        delete_bot_db(bot_id)
        
        settings = get_settings()
        if settings.get('default_bot_id') == str(bot_id):
            set_setting('default_bot_id', '')
            
        flash("✖ Bot đã được xoá thành công.", "success")
    else:
        flash("ID bot không hợp lệ.", "error")
        
    return redirect(url_for("dashboard"))

@app.route("/test_bot", methods=["POST"])
@login_required
def test_bot():
    """Thử nghiệm gửi tin nhắn bằng bot cụ thể."""
    bot_id = request.form.get("bot_id", type=int)
    settings = get_settings()
    
    if not settings.get('default_chat_id'):
        flash("🚨 Thiếu **Chat ID mặc định**. Vui lòng thiết lập Chat ID trước khi Test.", "error")
        return redirect(url_for("dashboard"))

    bots = get_bots()
    test_bot = next((b for b in bots if b['id'] == bot_id), None)

    if not test_bot:
        flash("Bot không tồn tại.", "error")
        return redirect(url_for("dashboard"))

    message = f"✅ <b>[TEST]</b> Bot <code>{test_bot['bot_name']}</code> đang hoạt động! Tin nhắn gửi từ Balance Watcher Universe."
    success = send_telegram_message(test_bot['bot_token'], settings['default_chat_id'], message)
    
    if success:
        flash(f"🎉 Gửi tin nhắn TEST thành công bằng bot: <b>{test_bot['bot_name']}</b>", "success")
    else:
        flash(f"❌ Lỗi gửi tin nhắn TEST bằng bot: <b>{test_bot['bot_name']}</b>. Kiểm tra lại **Token và Chat ID**.", "error")
        
    return redirect(url_for("dashboard"))


@app.route("/add_api", methods=["POST"])
@login_required
def add_api():
    """Thêm API số dư mới."""
    name = request.form.get("name", "").strip()
    url = request.form.get("url", "").strip()
    balance_field = request.form.get("balance_field", "").strip()

    if not name or not url:
        flash("Tên hiển thị và URL API không được để trống.", "error")
        return redirect(url_for("dashboard"))

    try:
        if not url.startswith(("http://", "https://")):
            flash("URL API không hợp lệ (phải bắt đầu bằng **http://** hoặc **https://**).", "error")
            return redirect(url_for("dashboard"))

        add_api_db(name, url, balance_field)
        flash(f"➕ API '<b>{name}</b>' đã được thêm vào danh sách theo dõi!", "success")
    except sqlite3.IntegrityError:
        flash("URL API này đã tồn tại trong hệ thống.", "error")
    except Exception as e:
        flash(f"Lỗi khi thêm API: {e}", "error")

    return redirect(url_for("dashboard"))


@app.route("/delete_api/<int:api_id>", methods=["POST"])
@login_required
def delete_api(api_id: int):
    """Xóa API số dư."""
    try:
        delete_api_db(api_id)
        flash("✖ API đã được xoá khỏi danh sách theo dõi.", "success")
    except Exception as e:
        flash(f"Lỗi khi xoá API: {e}", "error")
        
    return redirect(url_for("dashboard"))


@app.route("/download_backup")
@login_required
def download_backup():
    """Tải xuống file backup ở dạng JSON."""
    
    backup_data = {
        "timestamp": datetime.utcnow().isoformat(),
        "settings": get_settings(),
        "telegram_bots": get_bots(),
        "apis": get_apis(),
    }
    
    # Chuẩn bị phản hồi với file JSON
    response = app.response_class(
        response=json.dumps(backup_data, indent=4),
        status=200,
        mimetype='application/json'
    )
    response.headers.set("Content-Disposition", "attachment", filename="balance_watcher_backup.json")
    return response

@app.route("/upload_restore", methods=["POST"])
@login_required
def upload_restore():
    """Khôi phục dữ liệu từ file JSON."""
    
    if 'backup_file' not in request.files:
        flash("Không tìm thấy file backup.", "error")
        return redirect(url_for("dashboard"))
    
    file = request.files['backup_file']
    if file.filename == '':
        flash("Vui lòng chọn file JSON để khôi phục.", "error")
        return redirect(url_for("dashboard"))
        
    if not file.filename.lower().endswith('.json'):
        flash("File không đúng định dạng. Vui lòng chọn file .json.", "error")
        return redirect(url_for("dashboard"))

    try:
        # Đọc nội dung file
        data = json.load(file.stream)
        
        # 1. Xác thực cấu trúc cơ bản
        if not all(k in data for k in ["settings", "telegram_bots", "apis"]):
            flash("Cấu trúc file JSON không hợp lệ. Thiếu trường 'settings', 'telegram_bots' hoặc 'apis'.", "error")
            return redirect(url_for("dashboard"))
            
        # 2. Xóa dữ liệu cũ và reset settings
        clear_all_data()
        
        # 3. Khôi phục Settings
        for key, value in data["settings"].items():
            if key not in ['admin_password_hash', 'secret_key']: # Không ghi đè các key bảo mật
                set_setting(key, value)
                
        # 4. Khôi phục Bots
        for bot in data["telegram_bots"]:
            try:
                add_bot_db(bot['bot_name'], bot['bot_token'])
            except sqlite3.IntegrityError:
                pass # Bỏ qua bot trùng token

        # 5. Khôi phục APIs
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        for api in data["apis"]:
            try:
                c.execute(
                    "INSERT INTO apis (name, url, balance_field, last_balance, last_change) VALUES (?, ?, ?, ?, ?)",
                    (api['name'], api['url'], api['balance_field'], api.get('last_balance'), api.get('last_change')),
                )
            except sqlite3.IntegrityError:
                 flash(f"⚠️ Cảnh báo: API '{api['name']}' bị trùng URL và đã bị bỏ qua.", "error")
            
        conn.commit()
        conn.close()
        
        flash("✅ Khôi phục dữ liệu thành công! Vui lòng kiểm tra lại cấu hình và trạng thái Watcher.", "success")
        
    except json.JSONDecodeError:
        flash("Lỗi: File JSON không hợp lệ.", "error")
    except Exception as e:
        flash(f"Lỗi khôi phục không xác định: {e}", "error")
        
    return redirect(url_for("dashboard"))


# =========================
# KHỞI TẠO VÀ CHẠY
# =========================

init_db() 

if os.environ.get("FLASK_ENV") != "development":
    start_watcher()
    print("Watcher Thread được tự động khởi động (Production mode).")
else:
    print("Watcher Thread sẽ được khởi động khi Admin đăng nhập lần đầu (Development mode).")


if __name__ == "__main__":
    print("Khởi động ứng dụng Flask (Dev Server)...")
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)), debug=os.environ.get("FLASK_ENV") == "development")
