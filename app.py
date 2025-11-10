import os
import sqlite3
import threading
import time
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
    abort,
)

# =========================
# CẤU HÌNH CƠ BẢN
# =========================

APP_TITLE = "Balance Watcher Universe"
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))  # giây giữa các lần quét

# Dùng CHUNG 1 mật khẩu:
# - ADMIN_PASSWORD: dùng để đăng nhập dashboard
# - SECRET_KEY Flask: nếu không set riêng thì = ADMIN_PASSWORD
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
SECRET_KEY = os.getenv("SECRET_KEY", ADMIN_PASSWORD)

# Đường dẫn DB (Render dùng /data để giữ persistent)
DATA_DIR = "/data"
if not os.path.isdir(DATA_DIR):
    DATA_DIR = "."
DB_PATH = os.path.join(DATA_DIR, "balance_watcher.db")

app = Flask(__name__)
app.secret_key = SECRET_KEY

db_lock = threading.Lock()
watcher_started = False
watcher_running = False

# =========================
# TEMPLATE: LOGIN (VŨ TRỤ)
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
                    placeholder="Nhập mật khẩu do bạn cấu hình trong ADMIN_PASSWORD"
                    class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-slate-100 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-400 placeholder-slate-500 shadow-inner"
                />
                <button
                    type="submit"
                    class="w-full mt-2 inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-2xl bg-gradient-to-r from-indigo-500 via-sky-500 to-fuchsia-500 text-white text-sm font-medium shadow-xl hover:shadow-2xl hover:-translate-y-0.5 transition-all"
                >
                    <span>🚀 Vào Dashboard Vũ Trụ</span>
                </button>
            </form>

            <div class="mt-4 text-[10px] text-slate-500">
                Gợi ý triển khai:
                <ul class="list-disc list-inside">
                    <li>Set biến <span class="text-indigo-400 font-semibold">ADMIN_PASSWORD</span> trên Render.</li>
                    <li>(Tuỳ chọn) Set <span class="text-indigo-400 font-semibold">POLL_INTERVAL</span> để kiểm soát chu kỳ quét.</li>
                    <li>Chỉ chia sẻ link + mật khẩu cho người bạn tin tưởng tuyệt đối.</li>
                </ul>
            </div>
        </div>
    </div>
</body>
</html>
"""

# =========================
# TEMPLATE: DASHBOARD (COSMIC)
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
        .scrollbar-thin::-webkit-scrollbar {
            height: 5px;
            width: 5px;
        }
        .scrollbar-thin::-webkit-scrollbar-thumb {
            background-color: rgba(148, 163, 253, 0.4);
            border-radius: 999px;
        }
        .scrollbar-thin::-webkit-scrollbar-track {
            background-color: transparent;
        }
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
                Theo dõi biến động số dư nhiều website, phân loại tự động <span class="text-emerald-400 font-semibold">CỘNG TIỀN</span> /
                <span class="text-rose-400 font-semibold">THANH TOÁN</span> và gửi cảnh báo tức thời về Telegram.
            </p>
        </div>
        <div class="flex flex-col items-start md:items-end gap-1 text-[10px] text-slate-500">
            <div>Chu kỳ quét hiện tại: <span class="text-indigo-300 font-semibold">{{ poll_interval }} giây</span></div>
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
        <!-- Cột trái: Settings + Bots + Backup -->
        <div class="space-y-5">
            <!-- Cài đặt chung -->
            <div class="bg-slate-900/80 border border-slate-800 rounded-3xl p-5 shadow-2xl backdrop-blur-xl">
                <div class="flex items-center justify-between gap-2 mb-3">
                    <h2 class="text-sm font-semibold text-indigo-300 uppercase tracking-[0.16em]">Cài đặt chung</h2>
                    <span class="px-2 py-0.5 rounded-full bg-slate-800/90 text-[9px] text-slate-400">
                        Telegram: 1 Chat ID, nhiều Bot Token
                    </span>
                </div>
                <form method="post" action="{{ url_for('save_settings') }}" class="space-y-3">
                    <div>
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
                                <option value="{{ bot.id }}" {% if settings.default_bot_id and settings.default_bot_id == bot.id %}selected{% endif %}>
                                    {{ bot.bot_name }} (..{{ bot.bot_token[-6:] }})
                                </option>
                            {% endfor %}
                        </select>
                    </div>
                    <button type="submit"
                        class="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-2xl bg-gradient-to-r from-indigo-500 via-sky-500 to-fuchsia-500 text-white text-[11px] font-medium shadow-lg hover:-translate-y-0.5 hover:shadow-xl transition-all">
                        💾 Lưu cấu hình Telegram
                    </button>
                </form>
            </div>

            <!-- Quản lý Bot -->
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
                        Chưa có bot nào. Thêm ít nhất 1 bot để bắt đầu gửi cảnh báo.
                    </div>
                    {% endfor %}
                </div>
            </div>

            <!-- Backup -->
            <div class="bg-slate-900/80 border border-slate-800 rounded-3xl p-5 shadow-2xl backdrop-blur-xl">
                <div class="flex items-center justify-between mb-3">
                    <h2 class="text-sm font-semibold text-fuchsia-300 uppercase tracking-[0.16em]">Backup dữ liệu</h2>
                </div>
                <p class="text-[10px] text-slate-400 mb-3">
                    Tải xuống toàn bộ cấu hình (bots, API, trạng thái số dư cuối) để lưu trữ an toàn hoặc chuyển server.
                </p>
                <a href="{{ url_for('download_backup') }}"
                   class="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-2xl bg-slate-800 text-slate-100 text-[11px] border border-slate-600 hover:bg-slate-700 hover:border-fuchsia-500/60 hover:text-fuchsia-200 transition-all">
                    📦 Tải file backup (.json)
                </a>
            </div>
        </div>

        <!-- Cột phải: Danh sách API đang theo dõi -->
        <div class="lg:col-span-2 space-y-5">
            <!-- Thêm API mới -->
            <div class="bg-slate-900/80 border border-slate-800 rounded-3xl p-5 shadow-2xl backdrop-blur-xl">
                <div class="flex items-center justify-between gap-2 mb-3">
                    <h2 class="text-sm font-semibold text-sky-300 uppercase tracking-[0.16em]">Thêm API số dư</h2>
                    <span class="px-2 py-0.5 rounded-full bg-slate-800/90 text-[9px] text-slate-400">
                        Hỗ trợ nhiều website khác nhau
                    </span>
                </div>
                <form method="post" action="{{ url_for('add_api') }}" class="grid grid-cols-1 md:grid-cols-2 gap-3 text-[10px]">
                    <div class="md:col-span-1">
                        <label class="block text-slate-400 mb-1">Tên hiển thị</label>
                        <input type="text" name="name" required
                            placeholder="VD: ShopAccMMO chính"
                            class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-400">
                    </div>
                    <div class="md:col-span-1">
                        <label class="block text-slate-400 mb-1">URL API kiểm tra số dư</label>
                        <input type="text" name="url" required
                            placeholder="https://.../api/profile.php?api_key=XXXX"
                            class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-400">
                    </div>
                    <div class="md:col-span-1">
                        <label class="block text-slate-400 mb-1">Trường số dư trong JSON</label>
                        <input type="text" name="balance_field"
                            placeholder="VD: balance hoặc data.balance (mặc định: balance)"
                            class="w-full px-3 py-2 rounded-2xl bg-slate-950/80 border border-slate-700 text-[11px] text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-400">
                    </div>
                    <div class="md:col-span-1 flex items-end">
                        <button type="submit"
                            class="w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-2xl bg-gradient-to-r from-sky-500 to-indigo-500 text-white text-[11px] font-medium shadow-lg hover:-translate-y-0.5 hover:shadow-xl transition-all">
                            ➕ Thêm API
                        </button>
                    </div>
                </form>
            </div>

            <!-- Danh sách API -->
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
                                <th class="px-3 py-2 text-left font-semibold text-slate-400 uppercase tracking-[0.14em]">ID</th>
                                <th class="px-3 py-2 text-left font-semibold text-slate-400 uppercase tracking-[0.14em]">Tên</th>
                                <th class="px-3 py-2 text-left font-semibold text-slate-400 uppercase tracking-[0.14em]">URL</th>
                                <th class="px-3 py-2 text-left font-semibold text-slate-400 uppercase tracking-[0.14em]">Trường</th>
                                <th class="px-3 py-2 text-left font-semibold text-slate-400 uppercase tracking-[0.14em]">Số dư gần nhất</th>
                                <th class="px-3 py-2 text-left font-semibold text-slate-400 uppercase tracking-[0.14em]">Cập nhật</th>
                                <th class="px-3 py-2 text-right font-semibold text-slate-400 uppercase tracking-[0.14em]"></th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-slate-800">
                            {% for api in apis %}
                            <tr class="hover:bg-slate-800/80 transition-colors">
                                <td class="px-3 py-2 text-slate-400">#{{ api.id }}</td>
                                <td class="px-3 py-2 text-slate-100 font-medium">{{ api.name }}</td>
                                <td class="px-3 py-2 text-slate-500 max-w-[220px] truncate">{{ api.url }}</td>
                                <td class="px-3 py-2 text-slate-400">{{ api.balance_field }}</td>
                                <td class="px-3 py-2">
                                    {% if api.last_balance is not none %}
                                        <span class="inline-flex px-2 py-0.5 rounded-full bg-emerald-900/40 text-emerald-300">
                                            {{ api.last_balance }}
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
                                    Chưa có API nào. Thêm ít nhất một API số dư để bắt đầu giám sát.
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
        c.execute(
            "INSERT INTO telegram_bots (bot_name, bot_token) VALUES (?, ?)",
            (name, token),
        )
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
            "INSERT INTO apis (name, url, balance_field, last_balance, last_change) VALUES (?, ?, ?, NULL, NULL)",
            (name, url, balance_field),
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
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "UPDATE apis SET last_balance=?, last_change=? WHERE id=?",
            (balance, changed_at, api_id),
        )
        conn.commit()
        conn.close()

# =========================
# UTIL: JSON FIELD & BALANCE
# =========================

def extract_balance(data: Any, path: str) -> Optional[float]:
    """
    Lấy trường số dư từ JSON theo path dạng 'balance' hoặc 'data.balance'.
    """
    if not path:
        path = "balance"
    parts = path.split(".")
    val = data
    for p in parts:
        if isinstance(val, dict):
            val = val.get(p)
        else:
            return None
    if val is None:
        return None
    try:
        if isinstance(val, str):
            cleaned = "".join(ch for ch in val if (ch.isdigit() or ch in ",.-"))
            cleaned = cleaned.replace(",", "")
            return float(cleaned)
        return float(val)
    except Exception:
        return None

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

            default_chat_id = (settings.get("default_chat_id") or "").strip()
            default_bot_id = settings.get("default_bot_id") or ""
            last_run_str = datetime.utcnow().isoformat() + "Z"
            set_setting("last_run", last_run_str)

            # Xác định danh sách token sẽ dùng
            tokens_to_use: List[str] = []
            if default_bot_id:
                try:
                    bid = int(default_bot_id)
                    for b in bots:
                        if b["id"] == bid:
                            tokens_to_use = [b["bot_token"]]
                            break
                except ValueError:
                    tokens_to_use = [b["bot_token"] for b in bots]
            if not tokens_to_use:
                tokens_to_use = [b["bot_token"] for b in bots]

            for api in apis:
                api_id = api["id"]
                name = api["name"]
                url = api["url"]
                field = api["balance_field"] or "balance"
                old_balance = api["last_balance"]

                if not url:
                    continue

                try:
                    resp = requests.get(url, timeout=15)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception:
                    continue

                new_balance = extract_balance(data, field)
                if new_balance is None and field != "balance":
                    new_balance = extract_balance(data, "balance")

                if new_balance is None:
                    continue

                # Lần đầu chỉ lưu
                if old_balance is None:
                    update_api_state(api_id, new_balance, last_run_str)
                    continue

                diff = new_balance - float(old_balance)
                if abs(diff) < 1e-9:
                    # Không đổi
                    update_api_state(api_id, new_balance, api.get("last_change") or last_run_str)
                    continue

                # Phân loại biến động
                if diff > 0:
                    change_type = "CỘNG TIỀN"
                    icon = "🟢"
                    desc = "Nạp tiền / cộng số dư"
                else:
                    change_type = "THANH TOÁN"
                    icon = "🔴"
                    desc = "Thanh toán / trừ số dư"

                msg = (
                    f"{icon} <b>{change_type}</b> tại <b>{name}</b>\n"
                    f"Mô tả: {desc}\n"
                    f"Số dư cũ: <code>{old_balance}</code>\n"
                    f"Biến động: <code>{diff:+}</code>\n"
                    f"Số dư mới: <b><code>{new_balance}</code></b>\n"
                    f"Thời gian (UTC): <code>{last_run_str}</code>"
                )

                if default_chat_id and tokens_to_use:
                    send_telegram(tokens_to_use, default_chat_id, msg)

                update_api_state(api_id, new_balance, last_run_str)

        except Exception:
            pass

        time.sleep(POLL_INTERVAL)

def start_watcher_once():
    global watcher_started
    if not watcher_started:
        watcher_started = True
        t = threading.Thread(target=watcher_loop, daemon=True)
        t.start()

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
            flash("Đăng nhập thành công. Chào mừng Admin Văn Linh đến vũ trụ giám sát số dư.", "ok")
            return redirect(url_for("dashboard"))
        else:
            flash("Sai mật khẩu, vui lòng thử lại.", "error")
    return render_template_string(LOGIN_TEMPLATE, title=APP_TITLE)

@app.route("/logout")
def logout():
    session.clear()
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

    settings = SettingsObj(settings_raw)

    apis = [type("ApiObj", (), a) for a in apis_raw]
    last_run = settings_raw.get("last_run", "") or ""

    return render_template_string(
        DASHBOARD_TEMPLATE,
        title=APP_TITLE,
        bots=bots,
        apis=apis,
        settings=settings,
        poll_interval=POLL_INTERVAL,
        watcher_running=watcher_running,
        last_run=last_run,
    )

@app.route("/save_settings", methods=["POST"])
def save_settings():
    default_chat_id = (request.form.get("default_chat_id") or "").strip()
    default_bot_id = (request.form.get("default_bot_id") or "").strip()

    set_setting("default_chat_id", default_chat_id)
    set_setting("default_bot_id", default_bot_id)

    flash("Đã lưu cấu hình Telegram.", "ok")
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

    text = (
        "✅ <b>Test thành công</b>\n"
        "Bot đã kết nối và có thể gửi thông báo.\n"
        "Từ giờ các biến động số dư hợp lệ sẽ được đẩy về đây."
    )
    send_telegram([bot["bot_token"]], chat_id, text)
    flash("Đã gửi test message đến Telegram.", "ok")
    return redirect(url_for("dashboard"))

@app.route("/add_api", methods=["POST"])
def add_api():
    name = (request.form.get("name") or "").strip()
    url = (request.form.get("url") or "").strip()
    balance_field = (request.form.get("balance_field") or "").strip() or "balance"

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

@app.route("/download_backup")
def download_backup():
    import json
    from flask import Response

    data = {
        "settings": get_settings(),
        "bots": get_bots(),
        "apis": get_apis(),
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
    }
    backup_json = json.dumps(data, ensure_ascii=False, indent=2)
    return Response(
        backup_json,
        mimetype="application/json",
        headers={"Content-Disposition": 'attachment; filename="balance_watcher_backup.json"'},
    )

@app.route("/health")
def health():
    return {"status": "ok", "watcher_running": watcher_running}

# =========================
# KHỞI ĐỘNG
# =========================

init_db()
start_watcher_once()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
