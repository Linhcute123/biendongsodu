import os
import sqlite3
import requests
import threading
import sys
import json
import io
import functools # Cần cho decorator đăng nhập

from flask import (
    Flask, render_template_string, request, redirect, url_for, 
    session, flash, send_file, abort, Response, jsonify
)
from apscheduler.schedulers.background import BackgroundScheduler
from urllib.parse import urlparse
from werkzeug.utils import secure_filename

# --- Cấu hình ---
# 1. KEY BÍ MẬT (DÙNG ĐỂ ĐĂNG NHẬP VÀ LÀM SECRET KEY)
# Lấy từ biến môi trường của Render
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')
if not ADMIN_PASSWORD:
    print("CẢNH BÁO: ADMIN_PASSWORD chưa được đặt. Đặt thành 'admin' cho mục đích test.", file=sys.stderr)
    ADMIN_PASSWORD = 'admin'

# Dùng chung một key cho cả hai việc
app = Flask(__name__)
app.secret_key = ADMIN_PASSWORD # Dùng ADMIN_PASSWORD làm SECRET_KEY


# --- Cấu hình CSDL (Render Free Tier) ---
# Luôn lưu CSDL ở thư mục gốc của dự án
DATABASE_FILE = 'accounts.db'
print(f"Sử dụng CSDL tại: {DATABASE_FILE}")


# --- Decorator: Yêu cầu đăng nhập ---
def login_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if 'authenticated' not in session:
            flash('Bạn phải đăng nhập để xem trang này.', 'error')
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

# --- Giao diện Web (HTML) ---

# Giao diện Đăng Nhập (Bản hoàn thiện)
HTML_LOGIN = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Đăng Nhập - Bot của Admin Văn Linh</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body { 
            font-family: 'Inter', sans-serif;
            background-color: #0B1120;
            background-image: radial-gradient(circle at 1px 1px, rgba(200, 200, 255, 0.1) 1px, transparent 0);
            background-size: 20px 20px;
        }
        /* Style cho vòng tròn tích xanh chuyên nghiệp */
        .verified-badge {
            display: inline-flex; /* Quan trọng: Xếp hàng cùng văn bản */
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
            width: 20px;    /* Kích thước badge */
            height: 20px;
            border-radius: 50%;
            background-color: #3b82f6; /* Màu xanh (blue-500) */
            color: white;      /* Màu dấu tick */
            font-weight: bold;
            font-size: 12px;
            margin-left: 6px;  /* Khoảng cách nhỏ với chữ "Linh" */
            vertical-align: middle; /* Căn giữa theo chiều dọc với văn bản */
        }
    </style>
</head>
<body class="text-gray-200 min-h-screen flex items-center justify-center p-4">
    <div class="max-w-md w-full bg-gray-800/70 backdrop-blur-sm rounded-lg shadow-2xl p-8 border border-gray-700">
        
        <h2 class="text-2xl font-bold text-center mb-6">
            <span class="bg-clip-text text-transparent bg-gradient-to-r from-purple-400 to-cyan-400">
                Bot được Build và phát triển bởi Admin Văn Linh
            </span>
            <span class="verified-badge">✓</span>
        </h2>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="bg-red-900 border-red-500 text-red-300 border-l-4 px-4 py-3 rounded-lg relative mb-4" role="alert">
                <span class="block sm:inline">{{ message }}</span>
              </div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        
        <form action="{{ url_for('login_handler') }}" method="POST" class="space-y-6">
            <div>
                <label for="secret_key" class="block text-sm font-medium text-gray-400">Secret Key</label>
                <input type="password" name="secret_key" id="secret_key" placeholder="Nhập key bí mật của bạn" class="mt-1 block w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-cyan-500 focus:border-cyan-500 text-white" required>
            </div>
            <button type="submit" class="w-full inline-flex justify-center py-2 px-4 border border-transparent shadow-sm text-sm font-medium rounded-md text-white bg-gradient-to-r from-blue-500 to-cyan-500 hover:from-blue-600 hover:to-cyan-600 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-gray-800 focus:ring-blue-500 transition-all">
                Truy Cập
            </button>
        </form>
    </div>
</body>
</html>
"""

# Giao diện Bảng Điều Khiển
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Saldo (Cosmic Edition)</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body { 
            font-family: 'Inter', sans-serif;
            background-color: #0B1120;
            background-image: radial-gradient(circle at 1px 1px, rgba(200, 200, 255, 0.1) 1px, transparent 0);
            background-size: 20px 20px;
        }
    </style>
</head>
<body class="text-gray-200 min-h-screen">
    <div class="container mx-auto p-4 md:p-8 max-w-7xl">
        
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="{% if category == 'error' %}bg-red-900 border-red-500 text-red-300{% else %}bg-green-900 border-green-500 text-green-300{% endif %} border-l-4 px-4 py-3 rounded-lg relative mb-4 shadow-lg" role="alert">
                <span class="block sm:inline">{{ message }}</span>
              </div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        
        <div class="flex flex-col md:flex-row justify-between md:items-center mb-6 space-y-2 md:space-y-0">
            <h1 class="text-4xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-purple-400 to-cyan-400">
                Bảng Điều Khiển Saldo Bot
            </h1>
            <a href="{{ url_for('logout') }}" class="text-sm text-gray-500 hover:text-red-400 transition-colors">Đăng Xuất</a>
        </div>
        
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
            
            <div class="lg:col-span-1 space-y-6">
                
                <div class="bg-gray-800/70 backdrop-blur-sm rounded-lg shadow-2xl p-6 border border-gray-700">
                    <h2 class="text-xl font-semibold text-cyan-400 mb-5 border-b border-gray-700 pb-2">Cài Đặt Chung</h2>
                    <form action="{{ url_for('update_settings') }}" method="POST" class="space-y-4">
                        <div>
                            <label for="default_chat_id" class="block text-sm font-medium text-gray-400">Chat ID Mặc Định</label>
                            <input type="text" name="default_chat_id" id="default_chat_id" value="{{ settings.get('default_chat_id', '') }}" placeholder="ID của bạn hoặc nhóm (ví dụ: -1001...)" class="mt-1 block w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-cyan-500 focus:border-cyan-500 text-white">
                        </div>
                        <div>
                            <label for="default_bot_id" class="block text-sm font-medium text-gray-400">Bot Gửi Mặc Định</label>
                            <select name="default_bot_id" id="default_bot_id" class="mt-1 block w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-cyan-500 focus:border-cyan-500 text-white">
                                <option value="">-- Không chọn --</option>
                                {% for bot in all_bots %}
                                <option value="{{ bot.id }}" {% if settings.get('default_bot_id') == bot.id|string %}selected{% endif %}>{{ bot.bot_name }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <button type="submit" class="w-full inline-flex justify-center py-2 px-4 border border-transparent shadow-sm text-sm font-medium rounded-md text-white bg-gradient-to-r from-indigo-500 to-purple-500 hover:from-indigo-600 hover:to-purple-600 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-gray-800 focus:ring-indigo-500 transition-all">
                            Lưu Cài Đặt
                        </button>
                    </form>
                </div>

                <div class="bg-gray-800/70 backdrop-blur-sm rounded-lg shadow-2xl p-6 border border-gray-700">
                    <h2 class="text-xl font-semibold text-cyan-400 mb-5 border-b border-gray-700 pb-2">Quản Lý Bot Telegram</h2>
                    <form action="{{ url_for('add_bot') }}" method="POST" class="space-y-4 mb-6">
                        <div>
                            <label for="bot_name" class="block text-sm font-medium text-gray-400">Tên Bot (để phân biệt)</label>
                            <input type="text" name="bot_name" id="bot_name" placeholder="Ví dụ: Bot Cảnh Báo" class="mt-1 block w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-cyan-500 focus:border-cyan-500 text-white" required>
                        </div>
                        <div>
                            <label for="bot_token" class="block text-sm font-medium text-gray-400">Token Bot (từ BotFather)</label>
                            <input type="text" name="bot_token" id="bot_token" placeholder="123456:ABC...XYZ" class="mt-1 block w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md shadow-sm focus:outline-none focus:ring-cyan-500 focus:border-cyan-500 text-white" required>
                        </div>
                        <button type="submit" class="w-full inline-flex justify-center py-2 px-4 border border-transparent shadow-sm text-sm font-medium rounded-md text-white bg-gradient-to-r from-green-500 to-teal-500 hover:from-green-600 hover:to-teal-600 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-gray-800 focus:ring-green-500 transition-all">
                            Thêm Bot Mới
                        </button>
                    </form>
                    
                    <h3 class="text-md font-semibold text-gray-300 mb-2">Bot Đang Quản Lý</h3>
                    <ul class="divide-y divide-gray-700">
                        {% for bot in all_bots %}
                        <li class="py-3 flex items-center justify-between">
                            <span class="text-sm text-gray-300">{{ bot.bot_name }} {% if settings.get('default_bot_id') == bot.id|string %}<span class="text-xs text-purple-400">(Mặc định)</span>{% endif %}</span>
                            <div class="flex space-x-3">
                                <form action="{{ url_for('test_bot') }}" method="POST" class="inline">
                                    <input type="hidden" name="bot_id" value="{{ bot.id }}">
                                    <input type="hidden" name="bot_name" value="{{ bot.bot_name }}">
                                    <button type="submit" class="text-cyan-400 hover:text-cyan-300 text-sm font-medium transition-colors">Test</button>
                                </form>
                                <form action="{{ url_for('delete_bot') }}" method="POST" class="inline" onsubmit="return confirm('Bạn có chắc chắn muốn xóa bot này?');">
                                    <input type="hidden" name="id" value="{{ bot.id }}">
                                    <button type="submit" class="text-red-500 hover:text-red-400 text-sm font-medium transition-colors">Xóa</button>
                                </form>
                            </div>
                        </li>
                        {% else %}
                        <li class="py-2 text-sm text-gray-500">Chưa có bot nào.</li>
                        {% endfor %}
                    </ul>
                </div>
                
                <div class="bg-gray-800/70 backdrop-blur-sm rounded-lg shadow-2xl p-6 border border-gray-700">
                    <h2 class="text-xl font-semibold text-cyan-400 mb-5 border-b border-gray-700 pb-2">Thêm Tài Khoản Web Mới</h2>
                    
                    {% if not all_bots %}
                    <div class="bg-yellow-900 border-yellow-500 text-yellow-300 border-l-4 px-4 py-3 rounded-lg relative mb-4" role="alert">
                        <strong class="font-bold">Lưu ý!</strong>
                        <span class="block sm:inline">Bạn phải <a href="#bot_name" class="font-medium underline hover:text-yellow-100">thêm ít nhất 1 bot Telegram</a> trước.</span>
                    </div>
                    {% endif %}
                    
                    <form action="{{ url_for('add_account') }}" method="POST" class="space-y-4">
                        <div>
                            <label for="web_name" class="block text-sm font-medium text-gray-400">Tên Website</label>
                            <input type="text" name="web_name" id="web_name" placeholder="Ví dụ: ShopACCMO" class="mt-1 block w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md shadow-sm text-white" required>
                        </div>
                        <div>
                            <label for="api_key" class="block text-sm font-medium text-gray-400">API Key</label>
                            <input type="text" name="api_key" id="api_key" placeholder="API key của bạn" class="mt-1 block w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md shadow-sm text-white" required>
                        </div>
                        <div>
                            <label for="api_url" class="block text-sm font-medium text-gray-400">URL API Profile</label>
                            <input type="text" name="api_url" id="api_url" value="https://www.shopaccmmo.com/api/profile.php" class="mt-1 block w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md shadow-sm text-white" required>
                        </div>
                        <div>
                            <label for="threshold" class="block text-sm font-medium text-gray-400">Ngưỡng Cảnh Báo (VND)</label>
                            <input type="number" name="threshold" id="threshold" placeholder="Ví dụ: 10000" class="mt-1 block w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md shadow-sm text-white" required>
                        </div>
                        
                        <div>
                            <label for="bot_id" class="block text-sm font-medium text-gray-400">Bot gửi thông báo</label>
                            <select name="bot_id" id="bot_id" class="mt-1 block w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md shadow-sm text-white" {% if not all_bots %}disabled{% endif %}>
                                <option value="">-- Dùng Bot Mặc Định --</option>
                                {% for bot in all_bots %}
                                <option value="{{ bot.id }}">{{ bot.bot_name }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        
                        <div>
                            <label for="chat_id" class="block text-sm font-medium text-gray-400">Chat ID (Người nhận)</label>
                            <input type="text" name="chat_id" id="chat_id" placeholder="Bỏ trống để dùng Chat ID Mặc định" class="mt-1 block w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md shadow-sm text-white">
                        </div>

                        <button type="submit" class="w-full inline-flex justify-center py-2 px-4 border border-transparent shadow-sm text-sm font-medium rounded-md text-white bg-gradient-to-r from-blue-500 to-cyan-500 hover:from-blue-600 hover:to-cyan-600 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-gray-800 focus:ring-blue-500 transition-all" {% if not all_bots %}disabled{% endif %}>
                            Thêm Tài Khoản Web
                        </button>
                    </form>
                </div>

                <div class="bg-gray-800/70 backdrop-blur-sm rounded-lg shadow-2xl p-6 border border-gray-700">
                    <h2 class="text-xl font-semibold text-cyan-400 mb-5 border-b border-gray-700 pb-2">Quản Lý Dữ Liệu (JSON)</h2>
                    <div class="grid grid-cols-1 gap-4">
                        <div>
                            <h3 class="text-lg font-medium text-gray-300 mb-2">Tải Backup (Export)</h3>
                            <a href="{{ url_for('export_json') }}" class="w-full inline-flex justify-center py-2 px-4 border border-gray-600 shadow-sm text-sm font-medium rounded-md text-gray-200 bg-gray-600 hover:bg-gray-500 transition-colors">
                                Tải Backup (.json)
                            </a>
                        </div>
                        <div>
                            <h3 class="text-lg font-medium text-gray-300 mb-2">Restore từ Backup (Import)</h3>
                            <form action="{{ url_for('import_json') }}" method="POST" enctype="multipart/form-data" 
                                  onsubmit="return confirm('BẠN CÓ CHẮC CHẮN MUỐN GHI ĐÈ TOÀN BỘ DỮ LIỆN HIỆN TẠI BẰNG FILE NÀY KHÔNG?');">
                                <input type="file" name="backup_file" accept=".json" required class="block w-full text-sm text-gray-400
                                  file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-semibold
                                  file:bg-gray-700 file:text-cyan-400 hover:file:bg-gray-600 mb-2 transition-colors"/>
                                <button type="submit" class="w-full inline-flex justify-center py-2 px-4 border border-transparent shadow-sm text-sm font-medium rounded-md text-white bg-gradient-to-r from-red-600 to-orange-500 hover:from-red-700 hover:to-orange-600 transition-all">
                                    Upload & Restore
                                </button>
                            </form>
                        </div>
                    </div>
                </div>
                </div>
            
            <div class="lg:col-span-2">
                <div class="bg-gray-800/70 backdrop-blur-sm rounded-lg shadow-2xl p-6 md:p-8 border border-gray-700">
                    <h2 class="text-xl font-semibold text-cyan-400 mb-5 border-b border-gray-700 pb-2">Trạng Thái Tài Khoản</h2>
                    <div class="overflow-x-auto">
                        <table class="min-w-full divide-y divide-gray-700">
                            <thead class="bg-gray-900/50">
                                <tr>
                                    <th class="px-5 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Tên Web</th>
                                    <th class="px-5 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Bot</th>
                                    <th class="px-5 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Chat ID</th>
                                    <th class="px-5 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Ngưỡng</th>
                                    
                                    <th class="px-5 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Số Dư Cuối</th>
                                    
                                    <th class="px-5 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wider">Trạng Thái</th>
                                    <th class="px-5 py-3 text-right text-xs font-semibold text-gray-400 uppercase tracking-wider">Xóa</th>
                                </tr>
                            </thead>
                            <tbody class="bg-gray-800 divide-y divide-gray-700">
                                {% for acc in accounts %}
                                <tr class="hover:bg-gray-700/50 transition-colors">
                                    <td class="px-5 py-4 whitespace-nowrap text-sm font-medium text-white">{{ acc.web_name }}</td>
                                    <td class="px-5 py-4 whitespace-nowrap text-sm text-gray-400">
                                        {% if acc.bot_name %}
                                            {{ acc.bot_name }} <span class="text-blue-400">(Chỉ định)</span>
                                        {% else %}
                                            <span class="text-gray-500">(Mặc định)</span>
                                        {% endif %}
                                    </td>
                                    <td class="px-5 py-4 whitespace-nowrap text-sm text-gray-400">
                                        {% if acc.chat_id %}
                                            {{ acc.chat_id }} <span class="text-blue-400">(Chỉ định)</span>
                                        {% else %}
                                            <span class="text-gray-500">(Mặc định)</span>
                                        {% endif %}
                                    </td>
                                    <td class="px-5 py-4 whitespace-nowrap text-sm text-gray-400">{{ "{:,.0f}đ".format(acc.threshold) }}</td>
                                    <td class="px-5 py-4 whitespace-nowrap text-sm text-gray-300 font-semibold">{{ "{:,.0f}đ".format(acc.last_balance) if acc.last_balance is not None else 'N/A' }}</td>
                                    <td class="px-5 py-4 whitespace-nowrap text-sm">
                                        {% if acc.last_status == 'OK' %}
                                            <span class="px-3 py-1 inline-flex text-xs leading-5 font-semibold rounded-full bg-green-900 text-green-300">OK</span>
                                        {% elif acc.last_status is not None and acc.last_status != 'OK' %}
                                            <span class="px-3 py-1 inline-flex text-xs leading-5 font-semibold rounded-full bg-red-900 text-red-300" title="{{ acc.last_status }}">Lỗi</span>
                                        {% else %}
                                            <span class="px-3 py-1 inline-flex text-xs leading-5 font-semibold rounded-full bg-gray-700 text-gray-400">Chưa rõ</span>
                                        {% endif %}
                                    </td>
                                    <td class="px-5 py-4 whitespace-nowrap text-right text-sm font-medium">
                                        <form action="{{ url_for('delete_account') }}" method="POST" onsubmit="return confirm('Bạn có chắc chắn muốn xóa tài khoản web này?');">
                                            <input type="hidden" name="id" value="{{ acc.id }}">
                                            <button type="submit" class="text-red-500 hover:text-red-400 transition-colors">Xóa</button>
                                        </form>
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


# --- Khởi tạo CSDL ---
def init_db():
    print(f"Kiểm tra và khởi tạo CSDL tại: {DATABASE_FILE}")
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        c = conn.cursor()
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS telegram_bots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_name TEXT NOT NULL,
                bot_token TEXT NOT NULL UNIQUE
            )
        ''')
        
        c.execute('''
            CREATE TABLE IF NOT EXISTS global_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT
            )
        ''')
        
        c.execute("INSERT OR IGNORE INTO global_settings (setting_key, setting_value) VALUES (?, ?)", ('default_chat_id', ''))
        c.execute("INSERT OR IGNORE INTO global_settings (setting_key, setting_value) VALUES (?, ?)", ('default_bot_id', ''))

        c.execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                web_name TEXT NOT NULL,
                api_key TEXT NOT NULL,
                api_url TEXT NOT NULL,
                threshold REAL NOT NULL,
                chat_id TEXT, 
                last_balance REAL,
                last_status TEXT,
                bot_id INTEGER REFERENCES telegram_bots(id) ON DELETE SET NULL
            )
        ''')
        
        # Logic kiểm tra và nâng cấp CSDL cũ
        try:
            c.execute("PRAGMA table_info(accounts)")
            cols = c.fetchall()
            has_bot_id = any(col[1] == 'bot_id' for col in cols)
            
            if not has_bot_id:
                 print("Phát hiện CSDL cũ, đang nâng cấp bảng 'accounts' (thêm bot_id)...")
                 c.execute("ALTER TABLE accounts ADD COLUMN bot_id INTEGER REFERENCES telegram_bots(id) ON DELETE SET NULL")
                 print("Nâng cấp bảng 'accounts' thành công.")

        except Exception as e:
            print(f"Lỗi khi kiểm tra nâng cấp CSDL: {e}")

        conn.commit()
        conn.close()
        print("Cơ sở dữ liệu đã sẵn sàng.")
    except Exception as e:
        print(f"Lỗi khi khởi tạo CSDL: {e}", file=sys.stderr)

# --- Hàm gửi thông báo Telegram ---
def send_telegram_message(message, chat_id, bot_token):
    if not bot_token:
        print(f"Lỗi: Không tìm thấy bot token. Bỏ qua gửi tin nhắn.", file=sys.stderr)
        return False, "Không tìm thấy bot token"
    if not chat_id:
        print(f"Lỗi: Không tìm thấy chat ID. Bỏ qua gửi tin nhắn.", file=sys.stderr)
        return False, "Không tìm thấy chat ID"

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = { 'chat_id': chat_id, 'text': message, 'parse_mode': 'Markdown' }
    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code == 200:
            print(f"Đã gửi thông báo tới {chat_id} (sử dụng token ...{bot_token[-6:]})")
            return True, "Thành công"
        else:
            error_msg = f"Lỗi Telegram: {response.text}"
            print(f"Lỗi khi gửi thông báo tới {chat_id}: {error_msg}", file=sys.stderr)
            return False, error_msg
    except Exception as e:
        error_msg = f"Lỗi Mạng: {str(e)}"
        print(f"Lỗi mạng khi gửi thông báo: {error_msg}", file=sys.stderr)
        return False, error_msg

# --- Lõi Bot: Hàm kiểm tra Saldo ---
def check_balances():
    print("Bắt đầu phiên kiểm tra saldo...")
        
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        c.execute("SELECT * FROM global_settings")
        settings_db = c.fetchall()
        settings = {row['setting_key']: row['setting_value'] for row in settings_db}
        
        default_chat_id = settings.get('default_chat_id')
        default_bot_id = settings.get('default_bot_id')
        default_bot_token = None

        if default_bot_id:
            c.execute("SELECT bot_token FROM telegram_bots WHERE id = ?", (default_bot_id,))
            bot_row = c.fetchone()
            if bot_row:
                default_bot_token = bot_row['bot_token']
            else:
                print(f"Cảnh báo: Không tìm thấy bot mặc định (ID: {default_bot_id})", file=sys.stderr)

        query = """
        SELECT 
            a.id, a.web_name, a.api_key, a.api_url, a.threshold, 
            a.chat_id, a.bot_id, 
            a.last_balance, a.last_status,
            b.bot_token 
        FROM accounts a
        LEFT JOIN telegram_bots b ON a.bot_id = b.id
        """
        c.execute(query)
        accounts = c.fetchall()
        
    except Exception as e:
        print(f"Lỗi khi đọc CSDL: {e}", file=sys.stderr)
        if "no such table" in str(e):
            init_db() # Cố gắng tạo lại CSDL nếu nó bị mất
        return

    for acc in accounts:
        web_name = acc['web_name']
        chat_id_to_use = acc['chat_id'] if acc['chat_id'] else default_chat_id
        bot_token_to_use = acc['bot_token'] if acc['bot_token'] else default_bot_token
        
        if not bot_token_to_use:
            print(f"Bỏ qua {web_name}: Không có bot (cụ thể hay mặc định) được gán.", file=sys.stderr)
            continue
        if not chat_id_to_use:
            print(f"Bỏ qua {web_name}: Không có Chat ID (cụ thể hay mặc định) được gán.", file=sys.stderr)
            continue

        api_key = acc['api_key']
        api_url = acc['api_url']
        threshold = acc['threshold']
        old_balance = acc['last_balance']
        full_api_url = f"{api_url}?api_key={api_key}"
        new_status = "Lỗi Request"
        new_balance = None

        try:
            r = requests.get(full_api_url, timeout=10)
            data = r.json()
            
            if data.get('status') == True or data.get('success') == True:
                user_data = data.get('data', data)
                new_balance = user_data.get('balance', user_data.get('sodu'))
                if new_balance is None:
                    new_status = "Lỗi: Không tìm thấy 'balance' hoặc 'sodu' trong API."
                else:
                    new_balance = float(new_balance)
                    new_status = "OK"
            else:
                new_status = f"Lỗi API: {data.get('msg', 'Lỗi không xác định')}"

            if new_status == "OK":
                print(f"Kiểm tra {web_name}: Thành công. Số dư: {new_balance:,.0f}đ")
                if old_balance is not None:
                    if new_balance < old_balance:
                        diff = old_balance - new_balance
                        msg = (f"✅ GIAO DỊCH THÀNH CÔNG ({web_name})\n\n"
                               f"Nội dung: Thanh toán đơn hàng\n"
                               f"Tổng trừ (Gồm phí): *-{diff:,.0f}đ*\n"
                               f"Số dư cuối: *{new_balance:,.0f}đ*")
                        send_telegram_message(msg, chat_id_to_use, bot_token_to_use)
                    elif new_balance > old_balance:
                        diff = new_balance - old_balance
                        msg = (f"💰 NHẬN TIỀN THÀNH CÔNG ({web_name})\n\n"
                               f"Nội dung: Nạp tiền vào tài khoản\n"
                               f"Biến động: *+{diff:,.0f}đ*\n"
                               f"Số dư cuối: *{new_balance:,.0f}đ*")
                        send_telegram_message(msg, chat_id_to_use, bot_token_to_use)
                
                if new_balance < threshold:
                    msg = (f"🔥 SỐ DƯ SẮP HẾT ({web_name}) 🔥\n\n"
                           f"Tài khoản chỉ còn *{new_balance:,.0f}đ* (Dưới ngưỡng *{threshold:,.0f}đ*).\n"
                           f"👉 Vui lòng nạp tiền GẤP!")
                    send_telegram_message(msg, chat_id_to_use, bot_token_to_use)

            else: 
                print(f"Lỗi API từ {web_name}: {new_status}", file=sys.stderr)
                if acc['last_status'] == 'OK' or acc['last_status'] is None: 
                    msg = (f"❌ LỖI API ({web_name})\n\n"
                           f"Không thể kiểm tra số dư. Server báo:\n"
                           f"`{new_status}`\n\n"
                           f"Kiểm tra lại API key hoặc liên hệ admin web.")
                    send_telegram_message(msg, chat_id_to_use, bot_token_to_use)

        except requests.exceptions.RequestException as e:
            new_status = f"Lỗi Mạng: {str(e)}"
            print(f"Lỗi Mạng {web_name}: {new_status}", file=sys.stderr)
        except Exception as e:
            new_status = f"Lỗi Phân Tích: {str(e)}"
            print(f"Lỗi Phân Tích {web_name}: {new_status}", file=sys.stderr)

        try:
            c.execute("UPDATE accounts SET last_balance = ?, last_status = ? WHERE id = ?",
                      (new_balance if new_balance is not None else old_balance, new_status, acc['id']))
            conn.commit()
        except Exception as e:
            print(f"Lỗi khi cập nhật CSDL cho {web_name}: {e}", file=sys.stderr)

    conn.close()
    print("Hoàn tất phiên kiểm tra.")

# --- Ứng dụng Web Flask ---

# Trang Đăng Nhập
@app.route('/')
def login_page():
    if 'authenticated' in session:
        return redirect(url_for('dashboard'))
    return render_template_string(HTML_LOGIN)

# Xử lý đăng nhập
@app.route('/login', methods=['POST'])
def login_handler():
    secret_key = request.form.get('secret_key')
    if secret_key == ADMIN_PASSWORD:
        session['authenticated'] = True
        return redirect(url_for('dashboard'))
    else:
        flash('Secret Key không chính xác!', 'error')
        return redirect(url_for('login_page'))

# Đăng xuất
@app.route('/logout')
def logout():
    session.pop('authenticated', None)
    flash('Bạn đã đăng xuất.', 'success')
    return redirect(url_for('login_page'))

# Trang chủ (Bảng điều khiển)
@app.route('/dashboard')
@login_required
def dashboard():
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        c.execute("SELECT * FROM global_settings")
        settings_db = c.fetchall()
        settings = {row['setting_key']: row['setting_value'] for row in settings_db}
        
        c.execute("""
            SELECT a.*, b.bot_name 
            FROM accounts a 
            LEFT JOIN telegram_bots b ON a.bot_id = b.id
            ORDER BY a.web_name
        """)
        accounts = c.fetchall()
        
        c.execute("SELECT * FROM telegram_bots ORDER BY bot_name")
        all_bots = c.fetchall()
        
        conn.close()
        return render_template_string(HTML_TEMPLATE, accounts=accounts, all_bots=all_bots, settings=settings)
    except Exception as e:
        flash(f"Lỗi khi tải dữ liệu: {e}", 'error')
        # Nếu lỗi là "no such table", hãy cố gắng tạo lại CSDL
        if 'no such table' in str(e):
            init_db()
            flash('Lỗi CSDL: Đã thử khởi tạo lại. Vui lòng F5 trang.', 'error')
        return render_template_string(HTML_TEMPLATE, accounts=[], all_bots=[], settings={})

# --- Các route chức năng ---

@app.route('/update_settings', methods=['POST'])
@login_required
def update_settings():
    try:
        default_chat_id = request.form['default_chat_id'].strip()
        default_bot_id = request.form['default_bot_id']
        
        conn = sqlite3.connect(DATABASE_FILE)
        c = conn.cursor()
        c.execute("UPDATE global_settings SET setting_value = ? WHERE setting_key = ?", (default_chat_id, 'default_chat_id'))
        c.execute("UPDATE global_settings SET setting_value = ? WHERE setting_key = ?", (default_bot_id, 'default_bot_id'))
        conn.commit()
        conn.close()
        flash('Lưu cài đặt chung thành công!', 'success')
    except Exception as e:
        flash(f"Lỗi khi lưu cài đặt: {e}", 'error')
    return redirect(url_for('dashboard'))

@app.route('/add_bot', methods=['POST'])
@login_required
def add_bot():
    try:
        bot_name = request.form['bot_name']
        bot_token = request.form['bot_token']
        conn = sqlite3.connect(DATABASE_FILE)
        c = conn.cursor()
        c.execute("INSERT INTO telegram_bots (bot_name, bot_token) VALUES (?, ?)", (bot_name, bot_token))
        conn.commit()
        conn.close()
        flash('Thêm bot mới thành công!', 'success')
    except sqlite3.IntegrityError:
        flash(f"Lỗi: Token này đã tồn tại.", 'error')
    except Exception as e:
        flash(f"Lỗi khi thêm bot: {e}", 'error')
    return redirect(url_for('dashboard'))

@app.route('/delete_bot', methods=['POST'])
@login_required
def delete_bot():
    try:
        bot_id = int(request.form['id'])
        conn = sqlite3.connect(DATABASE_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM telegram_bots WHERE id = ?", (bot_id,))
        c.execute("UPDATE global_settings SET setting_value = '' WHERE setting_key = 'default_bot_id' AND setting_value = ?", (str(bot_id),))
        conn.commit()
        conn.close()
        flash('Xóa bot thành công!', 'success')
    except Exception as e:
        flash(f"Lỗi khi xóa bot: {e}", 'error')
    return redirect(url_for('dashboard'))

@app.route('/test_bot', methods=['POST'])
@login_required
def test_bot():
    try:
        bot_id = int(request.form['bot_id'])
        bot_name = request.form['bot_name']
        
        conn = sqlite3.connect(DATABASE_FILE)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        c.execute("SELECT bot_token FROM telegram_bots WHERE id = ?", (bot_id,))
        bot_row = c.fetchone()
        if not bot_row:
            flash(f"Lỗi: Không tìm thấy bot '{bot_name}'.", 'error')
            return redirect(url_for('dashboard'))
        bot_token = bot_row['bot_token']
        
        c.execute("SELECT setting_value FROM global_settings WHERE setting_key = 'default_chat_id'")
        chat_id_row = c.fetchone()
        default_chat_id = chat_id_row['setting_value'] if chat_id_row else None
        
        if not default_chat_id:
            flash("Lỗi: Vui lòng nhập 'Chat ID Mặc Định' ở mục Cài Đặt Chung trước khi test.", 'error')
            conn.close()
            return redirect(url_for('dashboard'))

        test_msg = f"✅ [THỬ NGHIỆM THÀNH CÔNG]\n\nBot '{bot_name}' đã kết nối thành công tới Chat ID này. Đang lấy báo cáo tổng quan..."
        is_success, error_msg = send_telegram_message(test_msg, default_chat_id, bot_token)
        
        if is_success:
            flash(f"Đã gửi thử thành công (Bot '{bot_name}'). Đang gửi báo cáo tổng quan...", 'success')
            
            c.execute("SELECT web_name, last_balance, last_status FROM accounts ORDER BY web_name")
            accounts = c.fetchall()
            
            summary_msg = "📊 BÁO CÁO TỔNG QUAN (Từ lần quét cuối)\n\n"
            if not accounts:
                summary_msg += "Chưa có tài khoản web nào được cấu hình."
            else:
                for acc in accounts:
                    balance_str = f"{acc['last_balance']:,.0f}đ" if acc['last_balance'] is not None else "Chưa rõ"
                    
                    if acc['last_status'] == 'OK':
                        status_str = "✅ OK"
                    elif acc['last_status'] is None:
                        status_str = "Chưa quét"
                    else:
                        status_str = f"❌ Lỗi" 
                        
                    summary_msg += f"🌐 *{acc['web_name']}*:\n"
                    summary_msg += f"   SỐ DƯ: *{balance_str}*\n"
                    summary_msg += f"   TRẠNG THÁI: {status_str}\n\n"
            
            send_telegram_message(summary_msg, default_chat_id, bot_token)
            
        else:
            flash(f"Gửi thử THẤT BẠI (Bot '{bot_name}')! Lý do: {error_msg}", 'error')
            
    except Exception as e:
        flash(f"Lỗi khi gửi thử: {e}", 'error')
    finally:
        if 'conn' in locals() and conn:
            conn.close()
    return redirect(url_for('dashboard'))

@app.route('/add', methods=['POST'])
@login_required
def add_account():
    try:
        web_name = request.form['web_name']
        api_key = request.form['api_key']
        api_url = request.form['api_url']
        threshold = float(request.form['threshold'])
        
        chat_id = request.form['chat_id'].strip() or None
        bot_id = int(request.form['bot_id']) if request.form['bot_id'] else None
        
        if not urlparse(api_url).scheme:
            api_url = "https://" + api_url

        conn = sqlite3.connect(DATABASE_FILE)
        c = conn.cursor()
        c.execute("""
            INSERT INTO accounts (web_name, api_key, api_url, threshold, chat_id, bot_id, last_status) 
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (web_name, api_key, api_url, threshold, chat_id, bot_id, 'Mới'))
        conn.commit()
        conn.close()
        flash('Thêm tài khoản web thành công!', 'success')
    except Exception as e:
        flash(f"Lỗi khi thêm tài khoản: {e}", 'error')
    return redirect(url_for('dashboard'))

@app.route('/delete', methods=['POST'])
@login_required
def delete_account():
    try:
        account_id = int(request.form['id'])
        conn = sqlite3.connect(DATABASE_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        conn.commit()
        conn.close()
        flash('Xóa tài khoản web thành công!', 'success')
    except Exception as e:
        flash(f"Lỗi khi xóa tài khoản web: {e}", 'error')
    return redirect(url_for('dashboard'))

# --- HÀM BACKUP/RESTORE JSON ---

@app.route('/export_json')
@login_required
def export_json():
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        c.execute("SELECT * FROM global_settings")
        settings = [dict(row) for row in c.fetchall()]
        
        c.execute("SELECT * FROM telegram_bots")
        bots = [dict(row) for row in c.fetchall()]
        
        c.execute("SELECT * FROM accounts")
        accounts = [dict(row) for row in c.fetchall()]

        conn.close()
        
        backup_data = {
            "global_settings": settings,
            "telegram_bots": bots,
            "accounts": accounts
        }
        
        # Tạo file JSON trong bộ nhớ
        json_str = json.dumps(backup_data, indent=2, ensure_ascii=False)
        json_bytes = io.BytesIO(json_str.encode('utf-8'))
        
        return send_file(
            json_bytes,
            as_attachment=True,
            download_name='saldo_bot_backup.json',
            mimetype='application/json'
        )

    except Exception as e:
        flash(f"Lỗi khi xuất file JSON: {e}", 'error')
        return redirect(url_for('dashboard'))

@app.route('/import_json', methods=['POST'])
@login_required
def import_json():
    if 'backup_file' not in request.files:
        flash('Không có file nào được chọn.', 'error')
        return redirect(url_for('dashboard'))
    file = request.files['backup_file']
    if file.filename == '':
        flash('Không có file nào được chọn.', 'error')
        return redirect(url_for('dashboard'))
        
    if file and file.filename.endswith('.json'):
        try:
            # Đọc file JSON
            data = json.load(io.TextIOWrapper(file.stream, encoding='utf-8'))
            
            # Tạm dừng bot
            scheduler.pause()
            
            conn = sqlite3.connect(DATABASE_FILE)
            c = conn.cursor()

            # Bắt đầu 1 transaction (quan trọng)
            c.execute("BEGIN TRANSACTION")
            try:
                # 1. Xóa dữ liệu cũ
                c.execute("DELETE FROM accounts")
                c.execute("DELETE FROM telegram_bots")
                c.execute("DELETE FROM global_settings")
                
                # 2. Khôi phục Bảng settings
                if 'global_settings' in data:
                    for setting in data['global_settings']:
                        c.execute("INSERT INTO global_settings (setting_key, setting_value) VALUES (?, ?)",
                                  (setting['setting_key'], setting['setting_value']))
                
                # 3. Khôi phục Bảng bots
                if 'telegram_bots' in data:
                    for bot in data['telegram_bots']:
                        c.execute("INSERT INTO telegram_bots (id, bot_name, bot_token) VALUES (?, ?, ?)",
                                  (bot.get('id'), bot['bot_name'], bot['bot_token']))
                
                # 4. Khôi phục Bảng accounts
                if 'accounts' in data:
                    for acc in data['accounts']:
                        # Phải khớp với các cột trong CSDL
                        c.execute("""
                            INSERT INTO accounts (
                                id, web_name, api_key, api_url, threshold, 
                                chat_id, last_balance, last_status, bot_id
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            acc.get('id'), acc['web_name'], acc['api_key'], acc['api_url'], 
                            acc['threshold'], acc.get('chat_id'), acc.get('last_balance'), 
                            acc.get('last_status'), acc.get('bot_id')
                        ))
                
                # Lưu transaction
                conn.commit()
                flash('Restore CSDL từ file JSON thành công!', 'success')
                
            except Exception as e:
                conn.rollback() # Hoàn tác nếu có lỗi
                flash(f"Lỗi khi ghi dữ liệu restore: {e}", 'error')
            
        except json.JSONDecodeError:
            flash('Lỗi: File không phải là file JSON hợp lệ.', 'error')
        except Exception as e:
            flash(f"Lỗi khi restore: {e}", 'error')
        finally:
            if 'conn' in locals() and conn:
                conn.close()
            # Khởi động lại bot
            scheduler.resume()
    else:
        flash('File không hợp lệ. Chỉ chấp nhận file .json', 'error')
        
    return redirect(url_for('dashboard'))

# --- SỬA LỖI "no such table" CỦA GUNICORN ---
# Di chuyển 2 khối code này ra khỏi 'if __name__ == "__main__":'
# để Gunicorn có thể chạy chúng khi khởi động.

# 1. Khởi tạo CSDL ngay lập tức khi file được import
print("Đang khởi tạo CSDL...")
init_db()
print("Khởi tạo CSDL hoàn tất.")

# 2. Khởi động Scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(func=check_balances, trigger="interval", minutes=2)
scheduler.start()
print(f"Trình lập lịch đã bắt đầu, kiểm tra mỗi 2 PHÚT.")

import atexit
atexit.register(lambda: scheduler.shutdown())


# 3. Khối __name__ == "__main__" chỉ còn dùng để test local
if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    print(f"Khởi chạy web server (test local) tại http://0.0.0.0:{port}")
    print(f"Truy cập trang chủ để đăng nhập.")
    # Không chạy scheduler.start() hay init_db() ở đây nữa
    app.run(host='0.0.0.0', port=port)
