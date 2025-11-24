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
# CÁC THƯ VIỆN CHO EMAIL (GIỮ LẠI ĐỂ GỬI TEST THỦ CÔNG)
# =========================
import smtplib
import ssl
from email.message import EmailMessage
import io
import socket

# =========================
# CẤU HÌNH CƠ BẢN
# =========================

APP_TITLE = "Balance Watcher Universe"

# Một pass duy nhất:
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
SECRET_KEY = os.getenv("SECRET_KEY", ADMIN_PASSWORD)

# ! MỚI: ĐƯỜNG DẪN FILE BACKUP TỪ SECRET FILES (RENDER)
# Ví dụ trên Render bạn đặt Key là SECRET_BACKUP_FILE_PATH, Value là /etc/secrets/backup
SECRET_BACKUP_FILE_PATH = os.getenv("SECRET_BACKUP_FILE_PATH")

# DB path (Render dùng /data cho persistent)
DATA_DIR = "/data"
if not os.path.isdir(DATA_DIR):
    DATA_DIR = "."
DB_PATH = os.path.join(DATA_DIR, "balance_watcher.db")

POLL_INTERVAL_DEFAULT = 30

app = Flask(__name__)
app.secret_key = SECRET_KEY

db_lock = threading.Lock()
watcher_started = False
watcher_running = False

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
    if not s:
        return None
    try:
        si = s.rstrip("Z")
        dt = datetime.fromisoformat(si)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except Exception:
        return None

# =========================
# HELPERS: format tiền
# =========================
def fmt_amount(v: float) -> str:
    try:
        return f"{float(v):,.0f}đ"
    except Exception:
        try:
            return f"{float(str(v).replace(',', '')):,.0f}đ"
        except Exception:
            return f"{v}đ"

def to_float(s: Optional[str], default: Optional[float] = None) -> Optional[float]:
    try:
        if s is None:
            return default
        s = s.replace(",", "").strip()
        return float(s)
    except Exception:
        return default

# =========================
# TEMPLATE: LOGIN
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
                Đăng nhập bảng điều khiển
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
                      {{ message }}
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

# =========================
# TEMPLATE: DASHBOARD
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
              {{ message }}
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
                {% if global_threshold %}
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
                        Telegram & Email
                    </span>
                </div>
                
                <form method="post" action="{{ url_for('save_settings') }}" class="space-y-3">
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div class="md:col-span-2">
                            <label class="block text-[10px] text-slate-400 mb-1">TELEGRAM_CHAT_ID (nhận cảnh báo)</label>
                            <input type="text" name="default_chat_id"
                                value="{{ settings.default_chat_id or '' }}"
                                placeholder="VD: 123456789 hoặc -100123456789"
                                class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-400">
                        </div>

                        <div>
                            <label class="block text-[10px] text-slate-400 mb-1">Bot mặc định (tuỳ chọn)</label>
                            <select name="default_bot_id"
                                class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-400">
                                <option value="">-- Gửi bằng TẤT CẢ bot --</option>
                                {% for bot in bots %}
                                    <option value="{{ bot.id }}" {% if settings.default_bot_id and settings.default_bot_id == bot.id %}selected{% endif %}>
                                        {{ bot.bot_name }} (..{{ bot.bot_token[-6:] }})
                                    </option>
                                {% endfor %}
                            </select>
                        </div>

                        <div>
                            <label class="block text-[10px] text-slate-400 mb-1">Chu kỳ quét (giây)</label>
                            <input type="number" min="5" step="1" name="poll_interval"
                                value="{{ settings.poll_interval or '' }}"
                                placeholder="VD: 30"
                                class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-400">
                        </div>
                        
                        <div class="md:col-span-2">
                            <label class="block text-[10px] text-slate-400 mb-1">Ngưỡng cảnh báo chung (VND)</label>
                            <input type="text" name="global_threshold"
                                value="{{ settings.global_threshold or '' }}"
                                placeholder="VD: 1,000,000 (bỏ trống nếu không cảnh báo)"
                                class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-rose-500 focus:border-rose-400">
                        </div>
                    </div>
                    
                    <hr class="border-slate-700/60 my-4">
                    <h3 class="text-sm font-semibold text-yellow-300 uppercase tracking-[0.16em] mb-3">SMTP Email (Thủ công)</h3>
                    
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div>
                            <label class="block text-[10px] text-slate-400 mb-1">Email nhận</label>
                            <input type="email" name="report_email"
                                value="{{ settings.report_email or '' }}"
                                placeholder="admin@gmail.com"
                                class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-yellow-500 focus:border-yellow-400">
                        </div>
                        <div>
                            <label class="block text-[10px] text-slate-400 mb-1">SMTP Server</label>
                            <input type="text" name="smtp_server"
                                value="{{ settings.smtp_server or '' }}"
                                placeholder="smtp.gmail.com"
                                class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-yellow-500 focus:border-yellow-400">
                        </div>
                        <div>
                            <label class="block text-[10px] text-slate-400 mb-1">SMTP Port</label>
                            <input type="number" name="smtp_port"
                                value="{{ settings.smtp_port or '' }}"
                                placeholder="587/465"
                                class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-yellow-500 focus:border-yellow-400">
                        </div>
                        <div>
                            <label class="block text-[10px] text-slate-400 mb-1">SMTP User</label>
                            <input type="email" name="smtp_user"
                                value="{{ settings.smtp_user or '' }}"
                                class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-yellow-500 focus:border-yellow-400">
                        </div>
                        <div class="md:col-span-2">
                            <label class="block text-[10px] text-slate-400 mb-1">SMTP Password</label>
                            <input type="password" name="smtp_pass"
                                placeholder="********"
                                class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-yellow-500 focus:border-yellow-400">
                        </div>
                    </div>
                    <hr class="border-slate-700/60 my-4">
                    
                    <button type="submit"
                        class="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-2xl bg-gradient-to-r from-indigo-500 via-sky-500 to-fuchsia-500 text-white text-[11px] font-medium shadow-lg hover:-translate-y-0.5 hover:shadow-xl transition-all">
                        💾 Lưu toàn bộ cấu hình
                    </button>
                </form>
                
                <form method="post" action="{{ url_for('test_email') }}" class="mt-3">
                    <button type="submit" 
                            class="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-2xl bg-gradient-to-r from-yellow-500 to-orange-600 text-white text-[11px] font-medium shadow-lg hover:-translate-y-0.5 hover:shadow-xl transition-all">
                        ✉️ Gửi Email Test (Thủ công)
                    </button>
                </form>
            </div>

            <div class="bg-slate-900/80 border border-slate-800 rounded-3xl p-5 shadow-2xl backdrop-blur-xl">
                <div class="flex items-center justify-between mb-3">
                    <h2 class="text-sm font-semibold text-cyan-300 uppercase tracking-[0.16em]">Quản lý Bot Telegram</h2>
                </div>
                <form method="post" action="{{ url_for('add_bot') }}" class="space-y-3 mb-4">
                    <div>
                        <label class="block text-[10px] text-slate-400 mb-1">Tên bot</label>
                        <input type="text" name="bot_name" required
                            placeholder="Bot Cảnh báo chính"
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
                                  onsubmit="return confirm('Xoá bot này?');">
                                <input type="hidden" name="bot_id" value="{{ bot.id }}">
                                <button class="px-2 py-1 rounded-xl bg-slate-900 text-rose-400 hover:bg-rose-600/20 hover:text-rose-300 text-[9px]">
                                    Xoá
                                </button>
                            </form>
                        </div>
                    </div>
                    {% else %}
                    <div class="text-[9px] text-slate-500">
                        Chưa có bot nào.
                    </div>
                    {% endfor %}
                </div>
            </div>

            <div class="bg-slate-900/80 border border-slate-800 rounded-3xl p-5 shadow-2xl backdrop-blur-xl">
                <div class="flex items-center justify-between mb-3">
                    <h2 class="text-sm font-semibold text-fuchsia-300 uppercase tracking-[0.16em]">Backup / Restore</h2>
                </div>

                <p class="text-[10px] text-slate-400 mb-2">Tải xuống & phục hồi dữ liệu <span class="text-sky-300 font-semibold">JSON</span>.</p>

                <div class="grid grid-cols-1 md:grid-cols-2 gap-2 mb-4">
                    <a href="{{ url_for('download_backup') }}"
                       class="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-2xl bg-slate-800 text-slate-100 text-[11px] border border-slate-600 hover:bg-slate-700 hover:border-fuchsia-500/60 hover:text-fuchsia-200 transition-all md:col-span-2">
                        📦 Tải toàn bộ backup (.json)
                    </a>
                </div>

                <form method="post" action="{{ url_for('restore_backup') }}" enctype="multipart/form-data" class="space-y-3">
                    <label class="block text-[10px] text-slate-400 mb-1">Phục hồi từ file backup (.json)</label>
                    <input type="file" name="backup_file" accept="application/json"
                           class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-fuchsia-500 focus:border-fuchsia-400">
                    <label class="inline-flex items-center gap-2 text-[10px] text-slate-400">
                        <input type="checkbox" name="wipe" value="1" class="rounded border-slate-600 bg-slate-900">
                        Xoá hết dữ liệu cũ trước khi Restore
                    </label>
                    <button type="submit"
                            class="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-2xl bg-gradient-to-r from-fuchsia-500 to-purple-600 text-white text-[11px] font-medium shadow-lg hover:-translate-y-0.5 hover:shadow-xl transition-all">
                        ♻️ Restore từ JSON
                    </button>
                </form>
            </div>
        </div>

        <div class="lg:col-span-2 space-y-5">
            <div class="bg-slate-900/80 border border-slate-800 rounded-3xl p-5 shadow-2xl backdrop-blur-xl">
                <div class="flex items-center justify-between gap-2 mb-3">
                    <h2 class="text-sm font-semibold text-sky-300 uppercase tracking-[0.16em]">Thêm API số dư</h2>
                </div>
                <form method="post" action="{{ url_for('add_api') }}" class="grid grid-cols-1 md:grid-cols-2 gap-3 text-[10px]">
                    <div>
                        <label class="block text-slate-400 mb-1">Tên hiển thị</label>
                        <input type="text" name="name" required
                            placeholder="VD: ShopAccMMO chính"
                            class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-400">
                    </div>
                    <div>
                        <label class="block text-slate-400 mb-1">URL API</label>
                        <input type="text" name="url" required
                            placeholder="https://.../api"
                            class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-400">
                    </div>
                    <div>
                        <label class="block text-slate-400 mb-1">Trường số dư (JSON Key)</label>
                        <input type="text" name="balance_field"
                            placeholder="Để trống = auto detect"
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
                    <h2 class="text-sm font-semibold text-indigo-300 uppercase tracking-[0.16em]">Danh sách API</h2>
                    <span class="text-[9px] text-slate-500">
                        Lần chạy gần nhất: <span class="text-sky-300">{{ last_run_vn or 'chưa có' }}</span>
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
                                <th class="px-3 py-2 text-left text-slate-400 uppercase tracking-[0.14em]">Số dư</th>
                                <th class="px-3 py-2 text-left text-slate-400 uppercase tracking-[0.14em]">Update</th>
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
                                    {{ api.last_change_vn or '-' }}
                                </td>
                                <td class="px-3 py-2 text-right">
                                    <form method="post" action="{{ url_for('delete_api', api_id=api.id) }}"
                                          onsubmit="return confirm('Xoá API này khỏi danh sách theo dõi?');">
                                        <button class="px-2 py-1 rounded-xl bg-slate-950 text-rose-400 hover:bg-rose-600/20 hover:text-rose-300">
                                            ✖
                                        </button>
                                    </form>
                                </td>
                            </tr>
                            {% else %}
                            <tr>
                                <td colspan="7" class="px-3 py-4 text-center text-slate-500 text-[10px]">
                                    Chưa có API nào.
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

        setting_keys = [
            "default_chat_id", "default_bot_id", "last_run", "poll_interval", "global_threshold",
            "report_email", "smtp_server", "smtp_port", "smtp_user", "smtp_pass"
        ]
        for k in setting_keys:
            c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, '')", (k,))

        c.execute("""
        CREATE TABLE IF NOT EXISTS apis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            balance_field TEXT NOT NULL,
            last_balance REAL,
            last_change TEXT
        )
        """)

        c.execute("""
        CREATE TABLE IF NOT EXISTS balance_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            change_amount REAL NOT NULL,
            new_balance REAL NOT NULL,
            FOREIGN KEY(api_id) REFERENCES apis(id) ON DELETE CASCADE
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

def add_api_db(name: str, url: str, balance_field: str) -> int:
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT INTO apis (name, url, balance_field, last_balance, last_change) "
            "VALUES (?, ?, ?, NULL, NULL)",
            (name, url, balance_field or ""),
        )
        new_id = c.lastrowid
        conn.commit()
        conn.close()
    return int(new_id)

def delete_api_db(api_id: int):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM apis WHERE id=?", (api_id,))
        c.execute("DELETE FROM balance_history WHERE api_id=?", (api_id,)) 
        conn.commit()
        conn.close()

def update_api_state(api_id: int, balance: float, changed_at: str):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "UPDATE apis SET last_balance=?, last_change=? WHERE id=?",
            (balance, changed_at, api_id),
        )
        conn.commit()
        conn.close()

def log_transaction(api_id: int, name: str, timestamp: str, change_amount: float, new_balance: float):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "INSERT INTO balance_history (api_id, name, timestamp, change_amount, new_balance) "
            "VALUES (?, ?, ?, ?, ?)",
            (api_id, name, timestamp, change_amount, new_balance)
        )
        conn.commit()
        conn.close()


def wipe_table(table: str):
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(f"DELETE FROM {table}")
        conn.commit()
        conn.close()

# =========================
# UTIL BALANCE
# =========================
def _get_by_path(data: Any, path: str) -> Any:
    if not path:
        return None
    cur = data
    for part in str(path).split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur

def _parse_float_like(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val)
    cleaned = "".join(ch for ch in s if (ch.isdigit() or ch in ",.-"))
    if not cleaned:
        return None
    try:
        return float(cleaned.replace(",", ""))
    except Exception:
        return None

def _search_balance_recursive(data: Any) -> Optional[float]:
    if isinstance(data, dict):
        for k, v in data.items():
            key = k.lower()
            if any(x in key for x in ["bal", "sodu", "so_du", "money", "credit"]):
                num = _parse_float_like(v)
                if num is not None:
                    return num
        for v in data.values():
            found = _search_balance_recursive(v)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _search_balance_recursive(item)
            if found is not None:
                return found
    return None

def extract_balance_auto(data: Any, balance_field: str) -> Optional[float]:
    candidates: List[str] = []
    if balance_field:
        candidates.append(balance_field.strip())
    candidates.extend([
        "balance",
        "data.balance",
        "user.balance",
        "Data.balance",
        "result.balance",
        "info.balance",
        "sodu",
        "so_du",
        "data.sodu",
        "data.so_du",
        "money",
        "Money",
    ])
    seen = set()
    for path in candidates:
        p = path.strip()
        if not p or p in seen:
            continue
        seen.add(p)
        val = _get_by_path(data, p)
        num = _parse_float_like(val)
        if num is not None:
            return num
    return _search_balance_recursive(data)

def send_telegram(tokens: List[str], chat_id: str, text: str):
    if not chat_id or not tokens:
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
            continue

# =========================
# WATCHER THREAD
# =========================
def watcher_loop():
    global watcher_running
    watcher_running = True
    while True:
        try:
            settings = get_settings()
            apis = get_apis()
            bots = get_bots()

            poll_interval = to_float(settings.get("poll_interval") or "", None)
            if poll_interval is None or poll_interval < 5:
                poll_interval = POLL_INTERVAL_DEFAULT

            default_chat_id = (settings.get("default_chat_id") or "").strip()
            default_bot_id = settings.get("default_bot_id") or ""
            global_threshold = to_float(settings.get("global_threshold") or "", None)

            last_run_str = datetime.utcnow().isoformat() + "Z"
            set_setting("last_run", last_run_str)

            tokens_to_use: List[str] = []
            if default_bot_id:
                try:
                    bid = int(default_bot_id)
                    for b in bots:
                        if b["id"] == bid:
                            tokens_to_use = [b["bot_token"]]
                            break
                except ValueError:
                    pass
            if not tokens_to_use:
                tokens_to_use = [b["bot_token"] for b in bots]

            for api in apis:
                api_id = api["id"]
                name = api["name"]
                url = api["url"]
                field = api["balance_field"] or ""
                old_balance = api["last_balance"]

                if not url:
                    continue

                try:
                    resp = requests.get(url, timeout=15)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception:
                    continue

                new_balance = extract_balance_auto(data, field)
                if new_balance is None:
                    continue

                now = datetime.utcnow()
                time_label = fmt_time_label_vn(now)

                if old_balance is None:
                    update_api_state(api_id, new_balance, now.isoformat() + "Z")
                    continue

                old_balance = float(old_balance)
                diff = new_balance - old_balance

                if abs(diff) >= 1e-9:
                    if diff < 0:
                        msg = (
                            f"🔻 <b>THANH TOÁN THÀNH CÔNG</b> ({name})\n\n"
                            f"Nội dung: Thanh toán / trừ số dư\n"
                            f"Tổng trừ: <b>-{fmt_amount(abs(diff))}</b>\n"
                            f"Số dư cuối: <b>{fmt_amount(new_balance)}</b>\n"
                            f"Thời gian: {time_label}"
                        )
                    else:
                        msg = (
                            f"💰 <b>NẠP TIỀN THÀNH CÔNG</b> ({name})\n\n"
                            f"Nội dung: Nạp tiền vào tài khoản\n"
                            f"Biến động: <b>+{fmt_amount(diff)}</b>\n"
                            f"Số dư cuối: <b>{fmt_amount(new_balance)}</b>\n"
                            f"Thời gian: {time_label}"
                        )

                    settings = get_settings() 
                    default_chat_id = (settings.get("default_chat_id") or "").strip()
                    if default_chat_id and tokens_to_use:
                        send_telegram(tokens_to_use, default_chat_id, msg)

                    update_api_state(api_id, new_balance, now.isoformat() + "Z")
                    log_transaction(api_id, name, now.isoformat() + "Z", diff, new_balance)
                else:
                    update_api_state(api_id, new_balance, api.get("last_change") or now.isoformat() + "Z")

                if global_threshold is not None:
                    try:
                        thr = float(global_threshold)
                        if old_balance >= thr and new_balance < thr:
                            alert_msg = (
                                f"🚨 <b>CẢNH BÁO SỐ DƯ THẤP</b> ({name})\n\n"
                                f"Tài khoản chỉ còn: <b>{fmt_amount(new_balance)}</b>\n"
                                f"Ngưỡng cảnh báo: <b>{fmt_amount(thr)}</b>\n"
                                f"Vui lòng nạp thêm để tránh gián đoạn dịch vụ."
                            )
                            settings = get_settings()
                            default_chat_id = (settings.get("default_chat_id") or "").strip()
                            if default_chat_id and tokens_to_use:
                                send_telegram(tokens_to_use, default_chat_id, alert_msg)
                    except Exception:
                        pass

        except Exception:
            pass

        try:
            settings = get_settings()
            poll_interval = to_float(settings.get("poll_interval") or "", None)
            if poll_interval is None or poll_interval < 5:
                poll_interval = POLL_INTERVAL_DEFAULT
        except Exception:
            poll_interval = POLL_INTERVAL_DEFAULT
        time.sleep(poll_interval)

def start_watcher_once():
    global watcher_started
    if not watcher_started:
        watcher_started = True
        t = threading.Thread(target=watcher_loop, daemon=True)
        t.start()

# =========================
# EMAIL HELPER (CHỈ ĐỂ TEST THỦ CÔNG)
# =========================
def send_email(to_email: str, subject: str, html_body: str) -> Optional[str]:
    settings = get_settings()
    smtp_server = (settings.get("smtp_server") or "").strip()
    smtp_port_str = (settings.get("smtp_port") or "").strip()
    smtp_user = (settings.get("smtp_user") or "").strip()
    smtp_pass = (settings.get("smtp_pass") or "").strip()

    if not all([to_email, smtp_server, smtp_port_str, smtp_user, smtp_pass]):
        return "Thiếu thông tin cấu hình SMTP."

    try:
        smtp_port = int(smtp_port_str)
    except ValueError:
        return f"SMTP Port không hợp lệ: {smtp_port_str}."

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = smtp_user
    msg['To'] = to_email
    msg.set_content("Vui lòng xem nội dung email bằng trình duyệt hỗ trợ HTML.")
    msg.add_alternative(html_body, subtype='html')

    try:
        context = ssl.create_default_context()
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=10, context=context) as server:
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_server, smtp_port, timeout=10) as server:
                server.starttls(context=context)
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
        return None 
    except Exception as e:
        return f"Lỗi gửi email: {e}"

# =========================
# BACKUP IMPORT LOGIC (DÙNG CHUNG CHO RESTORE & STARTUP)
# =========================
def import_backup_data(payload: Dict, wipe: bool = False):
    """Logic cốt lõi để import dữ liệu từ JSON vào DB"""
    
    # Khôi phục settings
    settings = payload.get("settings", {})
    if isinstance(settings, dict):
        setting_keys = [
            "default_chat_id", "default_bot_id", "poll_interval", "global_threshold",
            "report_email", "smtp_server", "smtp_port", "smtp_user", "smtp_pass"
        ]
        for k in setting_keys:
            if k in settings:
                set_setting(k, str(settings.get(k) if settings.get(k) is not None else ""))

    if wipe:
        wipe_table("telegram_bots")
        wipe_table("apis")
        wipe_table("balance_history")

    # Khôi phục bots
    bots = payload.get("bots", [])
    if isinstance(bots, list):
        for b in bots:
            try:
                name = (b.get("bot_name") or "").strip()
                token = (b.get("bot_token") or "").strip()
                if name and token:
                    try:
                        add_bot_db(name, token)
                    except sqlite3.IntegrityError:
                        pass
            except Exception:
                continue

    # Khôi phục apis
    apis = payload.get("apis", [])
    apis_id_map = {} 
    if isinstance(apis, list):
        for a in apis:
            try:
                name = (a.get("name") or "").strip()
                url = (a.get("url") or "").strip()
                field = (a.get("balance_field") or "").strip()
                if name and url:
                    old_id = a.get("id")
                    new_id = add_api_db(name, url, field)
                    if old_id is not None:
                        apis_id_map[int(old_id)] = new_id
                    try:
                        last_bal = a.get("last_balance", None)
                        last_chg = a.get("last_change", None)
                        if last_bal is not None and last_chg:
                            update_api_state(new_id, float(last_bal), str(last_chg))
                    except Exception:
                        pass
            except Exception:
                continue

    # Khôi phục Lịch sử (nếu có)
    history = payload.get("history", [])
    if isinstance(history, list) and apis_id_map:
        for h in history:
            try:
                old_api_id = h.get("api_id")
                new_api_id = apis_id_map.get(int(old_api_id))
                if new_api_id:
                    log_transaction(
                        new_api_id,
                        h.get("name", ""),
                        h.get("timestamp", ""),
                        float(h.get("change_amount", 0)),
                        float(h.get("new_balance", 0))
                    )
            except Exception:
                continue

# =========================
# AUTH & ROUTES
# =========================
def is_logged_in() -> bool:
    return session.get("logged_in") is True

@app.before_request
def require_login():
    if request.endpoint in ("login", "health", "static"):
        return
    if not is_logged_in():
        return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        pwd = request.form.get("password", "")
        if pwd == ADMIN_PASSWORD:
            session["logged_in"] = True
            flash("Đăng nhập thành công. Chào mừng Admin Văn Linh.", "ok")
            return redirect(url_for("dashboard"))
        else:
            flash("Sai mật khẩu.", "error")
    return render_template_string(LOGIN_TEMPLATE, title=APP_TITLE)

@app.route("/logout")
def logout():
    session.clear
    flash("Đã đăng xuất.", "ok")
    return redirect(url_for("login"))

@app.route("/")
def dashboard():
    start_watcher_once()
    settings_raw = get_settings()
    bots = get_bots()
    apis_raw = get_apis()

    class SettingsObj:
        def __init__(self, d):
            self.default_chat_id = d.get("default_chat_id", "")
            self.default_bot_id = int(d["default_bot_id"]) if d.get("default_bot_id", "").isdigit() else None
            self.last_run = d.get("last_run", "") or ""
            self.poll_interval = d.get("poll_interval", "")
            self.global_threshold = d.get("global_threshold", "")
            self.report_email = d.get("report_email", "")
            self.smtp_server = d.get("smtp_server", "")
            self.smtp_port = d.get("smtp_port", "")
            self.smtp_user = d.get("smtp_user", "")

    settings = SettingsObj(settings_raw)

    last_run_iso = settings_raw.get("last_run", "") or ""
    dt_last = parse_iso_utc(last_run_iso)
    last_run_vn = fmt_time_label_vn(dt_last) if dt_last else ""

    apis = []
    for a in apis_raw:
        a2 = dict(a)
        dt_chg = parse_iso_utc(a2.get("last_change") or "")
        a2["last_change_vn"] = fmt_time_label_vn(dt_chg) if dt_chg else "-"
        apis.append(a2)

    effective_poll_interval = to_float(settings.poll_interval or "", None)
    if effective_poll_interval is None or effective_poll_interval < 5:
        effective_poll_interval = POLL_INTERVAL_DEFAULT

    global_threshold = to_float(settings.global_threshold or "", None)

    return render_template_string(
        DASHBOARD_TEMPLATE,
        title=APP_TITLE,
        bots=bots,
        apis=apis,
        settings=settings,
        poll_interval=POLL_INTERVAL_DEFAULT,
        watcher_running=watcher_running,
        last_run_vn=last_run_vn,
        effective_poll_interval=int(effective_poll_interval),
        global_threshold=global_threshold,
    )

@app.route("/save_settings", methods=["POST"])
def save_settings():
    default_chat_id = (request.form.get("default_chat_id") or "").strip()
    default_bot_id = (request.form.get("default_bot_id") or "").strip()
    poll_interval = (request.form.get("poll_interval") or "").strip()
    global_threshold = (request.form.get("global_threshold") or "").strip()

    if poll_interval:
        try:
            pi = int(float(poll_interval))
            if pi < 5:
                flash("Chu kỳ quét tối thiểu là 5 giây.", "error")
                return redirect(url_for("dashboard"))
        except Exception:
            flash("Chu kỳ quét không hợp lệ.", "error")
            return redirect(url_for("dashboard"))

    set_setting("default_chat_id", default_chat_id)
    set_setting("default_bot_id", default_bot_id)
    set_setting("poll_interval", poll_interval)
    set_setting("global_threshold", global_threshold)
    
    set_setting("report_email", (request.form.get("report_email") or "").strip())
    set_setting("smtp_server", (request.form.get("smtp_server") or "").strip())
    set_setting("smtp_port", (request.form.get("smtp_port") or "").strip())
    set_setting("smtp_user", (request.form.get("smtp_user") or "").strip())
    
    smtp_pass = (request.form.get("smtp_pass") or "").strip()
    if smtp_pass:
        set_setting("smtp_pass", smtp_pass)

    flash("Đã lưu cấu hình hệ thống.", "ok")
    return redirect(url_for("dashboard"))

@app.route("/add_bot", methods=["POST"])
def add_bot():
    name = (request.form.get("bot_name") or "").strip()
    token = (request.form.get("bot_token") or "").strip()
    if not name or not token:
        flash("Thiếu tên hoặc token bot.", "error")
        return redirect(url_for("dashboard"))
    try:
        add_bot_db(name, token)
        flash("Đã thêm bot mới.", "ok")
    except sqlite3.IntegrityError:
        flash("Token bot này đã tồn tại.", "error")
    except Exception as e:
        flash(f"Lỗi khi thêm bot: {e}", "error")
    return redirect(url_for("dashboard"))

@app.route("/delete_bot", methods=["POST"])
def delete_bot():
    try:
        bot_id = int(request.form.get("bot_id") or "0")
    except ValueError:
        flash("ID bot không hợp lệ.", "error")
        return redirect(url_for("dashboard"))

    delete_bot_db(bot_id)

    settings = get_settings()
    if settings.get("default_bot_id") == str(bot_id):
        set_setting("default_bot_id", "")

    flash("Đã xoá bot.", "ok")
    return redirect(url_for("dashboard"))

@app.route("/test_bot", methods=["POST"])
def test_bot():
    try:
        bot_id = int(request.form.get("bot_id") or "0")
    except ValueError:
        flash("ID bot không hợp lệ.", "error")
        return redirect(url_for("dashboard"))

    bots = get_bots()
    bot = next((b for b in bots if b["id"] == bot_id), None)
    if not bot:
        flash("Không tìm thấy bot.", "error")
        return redirect(url_for("dashboard"))

    settings = get_settings()
    chat_id = (settings.get("default_chat_id") or "").strip()
    if not chat_id:
        flash("Chưa cấu hình TELEGRAM_CHAT_ID.", "error")
        return redirect(url_for("dashboard"))

    send_telegram([bot["bot_token"]], chat_id,
                  "✅ <b>Test thành công</b>\nBot đã kết nối và sẵn sàng gửi cảnh báo biến động số dư.")
    flash("Đã gửi test message đến Telegram.", "ok")
    return redirect(url_for("dashboard"))

@app.route("/test_email", methods=["POST"])
def test_email():
    if not is_logged_in():
        return redirect(url_for("login"))

    settings = get_settings()
    to_email = (settings.get("report_email") or "").strip()

    if not to_email:
        flash("Vui lòng nhập 'Email nhận' và Lưu, trước khi test.", "error")
        return redirect(url_for("dashboard"))

    subject = f"Email Test từ {APP_TITLE}"
    content_html = f"""
    <p>Xin chào Admin,</p>
    <p>Đây là email kiểm tra tự động từ hệ thống <strong>{APP_TITLE}</strong>.</p>
    """
    
    error = send_email(to_email, subject, content_html)
    
    if error:
        flash(f"Gửi email test thất bại: {error}", "error")
    else:
        flash(f"Đã gửi email test thành công đến {to_email}", "ok")
        
    return redirect(url_for("dashboard"))

@app.route("/add_api", methods=["POST"])
def add_api():
    name = (request.form.get("name") or "").strip()
    url = (request.form.get("url") or "").strip()
    balance_field = (request.form.get("balance_field") or "").strip()
    if not name or not url:
        flash("Thiếu tên hoặc URL API.", "error")
        return redirect(url_for("dashboard"))
    add_api_db(name, url, balance_field)
    flash(f"Đã thêm API [{name}].", "ok")
    return redirect(url_for("dashboard"))

@app.route("/delete_api/<int:api_id>", methods=["POST"])
def delete_api(api_id: int):
    delete_api_db(api_id)
    flash(f"Đã xoá API ID {api_id}.", "ok")
    return redirect(url_for("dashboard"))

# =========================
# BACKUP & RESTORE
# =========================
def _get_balance_history():
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM balance_history ORDER BY id")
        rows = c.fetchall()
        conn.close()
    return [dict(r) for r in rows]

@app.route("/download_backup")
def download_backup():
    data = {
        "settings": get_settings(),
        "bots": get_bots(),
        "apis": get_apis(),
        "history": _get_balance_history(),
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "version": 3,
    }
    backup_json = json.dumps(data, ensure_ascii=False, indent=2)
    return Response(
        backup_json,
        mimetype="application/json",
        headers={"Content-Disposition": 'attachment; filename="balance_watcher_backup.json"'},
    )

@app.route("/restore_backup", methods=["POST"])
def restore_backup():
    file = request.files.get("backup_file")
    if not file or not file.filename.lower().endswith(".json"):
        flash("Vui lòng chọn file .json hợp lệ.", "error")
        return redirect(url_for("dashboard"))

    try:
        payload = json.loads(file.read().decode("utf-8"))
    except Exception as e:
        flash(f"Không đọc được JSON: {e}", "error")
        return redirect(url_for("dashboard"))

    if not isinstance(payload, dict):
        flash("Định dạng backup không hợp lệ.", "error")
        return redirect(url_for("dashboard"))

    wipe = (request.form.get("wipe") == "1")
    
    # Gọi logic import
    import_backup_data(payload, wipe)

    flash("Phục hồi dữ liệu từ JSON thành công.", "ok")
    return redirect(url_for("dashboard"))

@app.route("/health")
def health():
    return {"status": "ok", "watcher_running": watcher_running}

# =========================
# KHỞI ĐỘNG & AUTO RESTORE
# =========================
def init_and_run():
    init_db()
    
    # ! TÍNH NĂNG MỚI: AUTO RESTORE TỪ SECRET FILE KHI KHỞI ĐỘNG
    if SECRET_BACKUP_FILE_PATH and os.path.exists(SECRET_BACKUP_FILE_PATH):
        print(f"[{datetime.now()}] Phát hiện Secret Backup tại: {SECRET_BACKUP_FILE_PATH}. Đang tự động khôi phục...")
        try:
            with open(SECRET_BACKUP_FILE_PATH, 'r', encoding='utf-8') as f:
                backup_data = json.load(f)
            
            # Kiểm tra xem DB có trống không, nếu trống thì mới nạp (hoặc nạp đè)
            # Ở đây ta sẽ nạp đè các cấu hình nhưng KHÔNG xoá dữ liệu cũ (wipe=False) 
            # để đảm bảo an toàn, trừ khi bạn muốn force wipe.
            # Nếu Render khởi động lại (re-deploy), DB trong /data vẫn còn, nên ta chỉ merge config.
            # Nếu không dùng disk /data, DB sẽ trống, nó sẽ nạp mới.
            import_backup_data(backup_data, wipe=False)
            print(">> Đã khôi phục dữ liệu từ Secret File thành công.")
        except Exception as e:
            print(f"!! Lỗi khi đọc Secret Backup: {e}")
    
    start_watcher_once()

init_and_run()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
