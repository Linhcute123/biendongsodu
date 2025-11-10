import os
import json
import time
import requests
from flask import Flask, render_template_string, request, redirect, url_for, session, send_file
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from io import BytesIO

# --- 1. Cấu Hình Ứng Dụng và Biến Môi Trường ---
load_dotenv() # Tải biến môi trường từ file .env (chỉ dùng khi phát triển local)

# Lấy các biến môi trường bắt buộc
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123") # Mật khẩu mặc định nếu không set, KHUYẾN CÁO nên set
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN_BOT")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
# URL mẫu của API. Ví dụ: https://www.shopaccmmo.com/api/profile.php?api_key={api_key}
# KHUYẾN CÁO: Dùng biến môi trường API_URL_TEMPLATE thay vì mã cứng
API_URL_TEMPLATE = os.getenv("API_URL_TEMPLATE", "https://example.com/api?key={api_key}") 

DATA_FILE = "data.json"
app = Flask(__name__)
# Key ngẫu nhiên để mã hóa session (Bảo mật cho việc lưu trạng thái đăng nhập)
app.secret_key = os.urandom(24) 

# --- 2. Xử Lý Dữ Liệu (Lưu Trữ/Tải Dữ Liệu bằng File JSON) ---

def load_data():
    """Tải dữ liệu từ file JSON. Nếu file không tồn tại, trả về cấu trúc rỗng."""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            # Xử lý trường hợp file bị hỏng
            print("LỖI: File data.json bị hỏng. Bắt đầu với dữ liệu mới.")
            return {"api_keys": {}, "last_balances": {}}
    return {"api_keys": {}, "last_balances": {}}

def save_data(data):
    """Lưu dữ liệu vào file JSON."""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# --- 3. Chức Năng Thông Báo Telegram ---

def send_telegram_notification(message):
    """Gửi thông báo đến Telegram Chat ID đã cấu hình."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("LỖI: Thiếu TELEGRAM_TOKEN_BOT hoặc TELEGRAM_CHAT_ID. Không thể gửi thông báo.")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }
    
    try:
        response = requests.post(url, data=payload)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        print(f"LỖI GỬI TELEGRAM: {e}")
        return False

# --- 4. Logic Kiểm Tra Số Dư Cốt Lõi ---

def get_current_balance(api_key):
    """
    Lấy số dư hiện tại từ API của bên thứ ba.
    NOTE: Cần tùy chỉnh phần này theo cấu trúc JSON thực tế của API.
    Ví dụ: API trả về {'success': 1, 'info': {'balance': 12345.67}}
    """
    try:
        url = API_URL_TEMPLATE.format(api_key=api_key)
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # --- PHẦN TÙY CHỈNH CẤU TRÚC DỮ LIỆU ---
        # Giả sử cấu trúc JSON trả về có trường số dư là ['info']['balance']
        if data.get('success') == 1 and 'info' in data and 'balance' in data['info']:
            return float(data['info']['balance'])
        
        # Nếu API có cấu trúc khác, cần điều chỉnh ở đây.
        return None 
    except (requests.exceptions.RequestException, KeyError, ValueError, TypeError) as e:
        print(f"LỖI KHI LẤY SỐ DƯ cho key {api_key}: {e}")
        return None

def check_balances():
    """Kiểm tra biến động số dư cho TẤT CẢ các API Key đã lưu."""
    data = load_data()
    api_keys = data["api_keys"]
    last_balances = data["last_balances"]
    
    if not api_keys:
        print("Không có API Key nào được cấu hình.")
        return
        
    log_messages = []
    
    for key_alias, api_key in api_keys.items():
        current_balance = get_current_balance(api_key)
        last_balance = last_balances.get(api_key)
        
        if current_balance is None:
            log_messages.append(f"🔴 *{key_alias}* ({api_key[:8]}...): Lỗi khi lấy số dư.")
            continue

        if last_balance is None:
            # Lần kiểm tra đầu tiên
            notification = (
                f"🌟 *[{key_alias}] Khởi tạo Theo Dõi* 🌟\n"
                f"Đã bắt đầu theo dõi số dư cho tài khoản này.\n"
                f"Số dư hiện tại: *{current_balance:,.0f} VNĐ*"
            )
            log_messages.append(f"🟢 *{key_alias}*: Lần kiểm tra đầu tiên, số dư: {current_balance:,.0f} VNĐ.")
            send_telegram_notification(notification)
        
        elif current_balance != last_balance:
            # Số dư đã thay đổi
            diff = current_balance - last_balance
            
            if diff > 0:
                action = "CỘNG TIỀN/NHẬN"
                emoji = "✅"
            else:
                action = "THANH TOÁN/TRỪ"
                emoji = "💸"

            notification = (
                f"{emoji} *BIẾN ĐỘNG SỐ DƯ* - Tài khoản: *{key_alias}* {emoji}\n"
                f"----------------------------------------\n"
                f"➡️ *Hành Động:* {action}\n"
                f"➡️ *Biến Động:* {diff:+,0f} VNĐ\n"
                f"➡️ *Số Dư CUỐI:* *{current_balance:,.0f} VNĐ*\n"
                f"----------------------------------------\n"
            )
            log_messages.append(f"🟡 *{key_alias}*: Biến động {diff:+,0f} VNĐ. Số dư cuối: {current_balance:,.0f} VNĐ. Đã gửi Telegram.")
            send_telegram_notification(notification)
        else:
            log_messages.append(f"🔵 *{key_alias}*: Số dư không đổi. ({current_balance:,.0f} VNĐ)")

        # Cập nhật số dư cuối cùng (quan trọng!)
        last_balances[api_key] = current_balance
        
    data["last_check"] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    save_data(data)
    return "\n".join(log_messages)

# --- 5. Lên Lịch Tự Động (Dễ bị Render Stop) ---

scheduler = BackgroundScheduler()

def start_scheduler():
    """Khởi động bộ lập lịch. Chạy check_balances mỗi 5 phút."""
    # Chỉ thêm job nếu chưa có
    if not scheduler.get_jobs():
        # KHUYẾN CÁO: Thay vì dùng scheduler, nên dùng Cron Job bên ngoài gọi endpoint /check_balances
        # Vì Render Free có thể ngủ (sleep) hoặc kill các Background Process
        scheduler.add_job(check_balances, 'interval', minutes=5, id='balance_check_job')
        scheduler.start()
        print("Scheduler đã khởi động thành công.")

# Bắt đầu scheduler khi server chạy
with app.app_context():
    start_scheduler()

# --- 6. Giao Diện Người Dùng (HTML/CSS/JS) ---

# CSS cho giao diện "Vũ trụ"
COSMIC_CSS = """
    body {
        font-family: 'Inter', sans-serif;
        background: linear-gradient(135deg, #0f0a28 0%, #1a0f4a 50%, #0f0a28 100%);
        color: #e0e7ff;
        min-height: 100vh;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 20px;
    }
    .card {
        background: rgba(2, 6, 23, 0.8); /* Blue-Black Nebula */
        border-radius: 16px;
        backdrop-filter: blur(10px);
        border: 1px solid rgba(59, 7, 100, 0.5); /* Cosmic Border */
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
        padding: 30px;
        max-width: 90%;
        width: 450px;
        animation: fadeIn 1s ease-out;
    }
    .dashboard {
        max-width: 1200px;
        width: 100%;
    }
    h1 {
        font-size: 2.2rem;
        font-weight: 700;
        color: #c7d2fe;
        text-align: center;
        margin-bottom: 20px;
        text-shadow: 0 0 10px rgba(165, 180, 252, 0.5);
    }
    input[type="password"], input[type="text"] {
        width: 100%;
        padding: 12px;
        margin: 8px 0;
        box-sizing: border-box;
        border: 1px solid #4f46e5;
        border-radius: 8px;
        background: #1e1b4b;
        color: #e0e7ff;
        transition: border-color 0.3s;
    }
    input[type="password"]:focus, input[type="text"]:focus {
        border-color: #a5b4fc;
        outline: none;
        box-shadow: 0 0 0 3px rgba(165, 180, 252, 0.3);
    }
    button {
        width: 100%;
        padding: 12px;
        border: none;
        border-radius: 8px;
        cursor: pointer;
        font-size: 1rem;
        font-weight: 600;
        margin-top: 15px;
        transition: background-color 0.3s, transform 0.1s, box-shadow 0.3s;
        background: linear-gradient(90deg, #8b5cf6, #a855f7); /* Purple Gradient */
        color: white;
        box-shadow: 0 4px 15px rgba(139, 92, 246, 0.5);
    }
    button:hover {
        background: linear-gradient(90deg, #a78bfa, #c4b5fd);
        transform: translateY(-2px);
    }
    .footer {
        text-align: center;
        margin-top: 25px;
        font-size: 0.85rem;
        color: #9ca3af;
    }
    .verified-badge {
        display: inline-block;
        margin-left: 5px;
        color: #22c55e;
        font-size: 1.1em;
        vertical-align: middle;
    }
    .error {
        color: #fca5a5;
        text-align: center;
        margin-bottom: 15px;
    }
    /* Dashboard Specific Styles */
    .table-container {
        overflow-x: auto;
        margin-top: 20px;
        border-radius: 8px;
        border: 1px solid rgba(59, 7, 100, 0.5);
    }
    table {
        width: 100%;
        border-collapse: collapse;
        text-align: left;
    }
    th, td {
        padding: 12px 15px;
        border-bottom: 1px solid #3730a3;
    }
    th {
        background: #1e1b4b;
        color: #c7d2fe;
        font-weight: 700;
        text-transform: uppercase;
    }
    td {
        background: #110b33;
    }
    .action-group button {
        margin-top: 0;
        padding: 10px 15px;
        width: auto;
        display: inline-block;
        margin-left: 10px;
        font-size: 0.9rem;
    }
    .form-add-key {
        display: flex;
        gap: 10px;
        margin-bottom: 20px;
    }
    .form-add-key input {
        flex-grow: 1;
        margin: 0;
    }
    .form-add-key button {
        width: 100px;
        margin: 0;
        flex-shrink: 0;
    }
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(20px); }
        to { opacity: 1; transform: translateY(0); }
    }
    @media (max-width: 600px) {
        .form-add-key {
            flex-direction: column;
        }
        .form-add-key button {
            width: 100%;
        }
    }
"""

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AstroBot - Đăng Nhập Hệ Thống</title>
    <style>
        {css}
    </style>
</head>
<body>
    <div class="card">
        <h1>🌌 AstroBot Balance Monitor 🔑</h1>
        {error_message}
        <form method="POST" action="{login_url}">
            <input type="password" name="password" placeholder="Nhập Mật Khẩu Truy Cập..." required>
            <button type="submit">Đăng Nhập vào Hệ Thống</button>
        </form>
        <div class="footer">
            Bot được bảo dưỡng và phát triển bởi Admin Văn Linh
            <span class="verified-badge" title="Tích Xanh Đã Xác Minh">✅</span>
        </div>
    </div>
</body>
</html>
"""

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard - AstroBot</title>
    <style>
        {css}
        body { align-items: flex-start; } /* Dashboard alignment */
    </style>
</head>
<body>
    <div class="dashboard">
        <div class="card" style="width: 100%; margin-bottom: 20px; padding: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
                <h1>🔭 Bảng Điều Khiển Giám Sát Số Dư</h1>
                <div class="action-group" style="margin-bottom: 10px;">
                    <a href="{backup_url}"><button type="button" style="width: auto; background: #ca8a04;">💾 Sao Lưu Dữ Liệu (JSON)</button></a>
                    <a href="{check_url}"><button type="button" style="width: auto; background: #059669;">⚡ Kích hoạt Kiểm tra Ngay</button></a>
                    <a href="{logout_url}"><button type="button" style="width: auto; background: #dc2626;">🚪 Đăng Xuất</button></a>
                </div>
            </div>
            <p style="text-align: center; color: #a5b4fc; font-style: italic;">Lần kiểm tra cuối: {last_check}</p>
        </div>

        <!-- Thêm API Key -->
        <div class="card" style="width: 100%; margin-bottom: 20px;">
            <h2 style="font-size: 1.5rem; color: #a5b4fc; margin-bottom: 15px;">➕ Thêm API Key Mới</h2>
            <form method="POST" action="{add_key_url}" class="form-add-key">
                <input type="text" name="alias" placeholder="Tên Gợi Nhớ (Ví dụ: Web A - API 1)" required style="flex-basis: 30%;">
                <input type="text" name="api_key" placeholder="Nhập API Key Dài..." required style="flex-basis: 60%;">
                <button type="submit" style="flex-basis: 10%; margin: 0;">Thêm Key</button>
            </form>
        </div>
        
        <!-- Bảng Hiển Thị API Keys -->
        <div class="card dashboard" style="width: 100%;">
            <h2 style="font-size: 1.5rem; color: #a5b4fc; margin-bottom: 15px;">📋 Danh Sách API Keys Đang Theo Dõi ({key_count})</h2>
            {status_message}
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th>Tên Gợi Nhớ</th>
                            <th>API Key (Đã Ẩn)</th>
                            <th>Số Dư Lần Cuối</th>
                            <th>Thời Gian Cập Nhật</th>
                            <th>Hành Động</th>
                        </tr>
                    </thead>
                    <tbody>
                        {table_rows}
                    </tbody>
                </table>
            </div>
        </div>
        <div class="footer">
            Bot được bảo dưỡng và phát triển bởi Admin Văn Linh
            <span class="verified-badge" title="Tích Xanh Đã Xác Minh">✅</span>
        </div>
    </div>
</body>
</html>
"""

# --- 7. Định Tuyến (Routes) của Flask ---

# Middleware kiểm tra đăng nhập
@app.before_request
def check_authentication():
    """Kiểm tra xem người dùng đã đăng nhập chưa trước khi truy cập Dashboard."""
    if request.path.startswith('/dashboard') and 'logged_in' not in session:
        return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
def login():
    """Trang Đăng Nhập."""
    error_message = ""
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        else:
            error_message = '<p class="error">Mật khẩu không chính xác. Thử lại.</p>'
    
    return render_template_string(LOGIN_HTML, 
                                  css=COSMIC_CSS, 
                                  error_message=error_message,
                                  login_url=url_for('login'))

@app.route('/logout')
def logout():
    """Đăng Xuất."""
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/dashboard', methods=['GET'])
def dashboard():
    """Trang Dashboard chính."""
    data = load_data()
    api_keys_map = data["api_keys"]
    last_balances = data["last_balances"]
    
    table_rows = ""
    
    for alias, api_key in api_keys_map.items():
        # Lấy số dư cuối cùng và định dạng
        balance = last_balances.get(api_key, 0.0)
        formatted_balance = f"{balance:,.0f} VNĐ"
        
        # Lấy thời gian cập nhật cuối
        last_update_time = data.get("last_check", "Chưa rõ")

        # Tạo hàng cho bảng
        table_rows += f"""
        <tr>
            <td>{alias}</td>
            <td>{api_key[:8]}...</td>
            <td>{formatted_balance}</td>
            <td>{last_update_time}</td>
            <td>
                <form method="POST" action="{url_for('delete_key', key_alias=alias)}" style="display:inline;">
                    <button type="submit" style="width: auto; background: #dc2626; margin: 0; padding: 5px 10px;">Xóa</button>
                </form>
            </td>
        </tr>
        """
        
    status_msg = ""
    if 'status' in session:
        status_msg = f'<p class="error" style="color:#22c55e;">{session.pop("status", None)}</p>'
        
    return render_template_string(DASHBOARD_HTML,
                                  css=COSMIC_CSS,
                                  key_count=len(api_keys_map),
                                  table_rows=table_rows if table_rows else '<tr><td colspan="5" style="text-align: center;">Chưa có API Key nào được thêm.</td></tr>',
                                  last_check=data.get("last_check", "Chưa từng kiểm tra"),
                                  add_key_url=url_for('add_key'),
                                  delete_url=url_for('delete_key', key_alias='placeholder'),
                                  check_url=url_for('check_balances_route'),
                                  backup_url=url_for('backup_data'),
                                  logout_url=url_for('logout'),
                                  status_message=status_msg)

@app.route('/dashboard/add_key', methods=['POST'])
def add_key():
    """Thêm API Key mới."""
    if 'logged_in' not in session: return redirect(url_for('login'))
    
    alias = request.form.get('alias')
    api_key = request.form.get('api_key')
    
    if alias and api_key:
        data = load_data()
        if alias in data["api_keys"]:
            session['status'] = f"❌ Lỗi: Tên gợi nhớ '{alias}' đã tồn tại."
        elif api_key in data["api_keys"].values():
            session['status'] = "❌ Lỗi: API Key này đã được thêm."
        else:
            data["api_keys"][alias] = api_key
            # Khởi tạo số dư lần cuối là None để kích hoạt thông báo khởi tạo
            data["last_balances"][api_key] = None 
            save_data(data)
            session['status'] = f"✅ Đã thêm Key '{alias}' thành công! Vui lòng bấm 'Kiểm tra Ngay' để khởi tạo số dư."
    else:
        session['status'] = "❌ Lỗi: Thiếu Tên Gợi Nhớ hoặc API Key."
        
    return redirect(url_for('dashboard'))

@app.route('/dashboard/delete_key/<key_alias>', methods=['POST'])
def delete_key(key_alias):
    """Xóa API Key."""
    if 'logged_in' not in session: return redirect(url_for('login'))
    
    data = load_data()
    if key_alias in data["api_keys"]:
        api_key_to_delete = data["api_keys"].pop(key_alias)
        data["last_balances"].pop(api_key_to_delete, None) # Xóa cả số dư cuối
        save_data(data)
        session['status'] = f"✅ Đã xóa Key '{key_alias}' thành công."
    else:
        session['status'] = f"❌ Lỗi: Không tìm thấy Key '{key_alias}'."
        
    return redirect(url_for('dashboard'))

@app.route('/check_balances', methods=['GET'])
def check_balances_route():
    """Kích hoạt kiểm tra số dư thủ công (hoặc qua Cron Job bên ngoài)."""
    if 'logged_in' not in session and request.args.get('external') != 'true':
        # Cho phép gọi bên ngoài bằng /check_balances?external=true (không trả về log chi tiết)
        return redirect(url_for('login'))

    print("--- BẮT ĐẦU KIỂM TRA BIẾN ĐỘNG SỐ DƯ ---")
    log = check_balances()
    print("--- KẾT THÚC KIỂM TRA BIẾN ĐỘNG SỐ DƯ ---")
    
    if request.args.get('external') == 'true':
        # Trả về kết quả cho dịch vụ Cron Job
        return "Balance check completed.", 200
        
    session['status'] = f"✅ Kiểm tra số dư đã hoàn tất. Chi tiết xem trong logs của server. {len(load_data().get('api_keys', []))} keys đã được xử lý."
    return redirect(url_for('dashboard'))

@app.route('/backup_data')
def backup_data():
    """Chức năng Sao Lưu Dữ Liệu Thủ Công."""
    if 'logged_in' not in session: return redirect(url_for('login'))
    
    # Đọc nội dung file data.json
    try:
        with open(DATA_FILE, 'rb') as f:
            data = f.read()
    except FileNotFoundError:
        return "Lỗi: Không tìm thấy file dữ liệu để sao lưu.", 404
        
    # Tạo đối tượng BytesIO từ nội dung file
    return send_file(
        BytesIO(data),
        mimetype='application/json',
        as_attachment=True,
        download_name='astrobot_balance_backup.json'
    )

if __name__ == '__main__':
    # Chạy ứng dụng trong môi trường phát triển
    print(f"Mật khẩu Admin: {ADMIN_PASSWORD}")
    print(f"Token/Chat ID TG: {TELEGRAM_TOKEN is not None}/{TELEGRAM_CHAT_ID is not None}")
    app.run(debug=True, port=5000)
