import os
import json
import time
import requests
import sqlite3
import threading
from datetime import datetime
from flask import Flask, request, redirect, url_for, render_template_string, session, send_file
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash
import telegram
from telegram.ext import Updater

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'supersecretkey')
auth = HTTPBasicAuth()

# Set your password here (change it to your desired password)
PASSWORD_HASH = generate_password_hash('your_secure_password')  # Replace 'your_secure_password' with actual password

# Database setup
conn = sqlite3.connect('balance_monitor.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS apis (
        id INTEGER PRIMARY KEY,
        api_url TEXT NOT NULL
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS telegram_configs (
        id INTEGER PRIMARY KEY,
        bot_token TEXT NOT NULL,
        chat_id TEXT NOT NULL
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS balances (
        api_id INTEGER,
        last_balance REAL,
        last_check TIMESTAMP,
        FOREIGN KEY(api_id) REFERENCES apis(id)
    )
''')
conn.commit()

# Global variables
CHECK_INTERVAL = 60  # Check every 60 seconds
running = True

def get_balance(api_url):
    try:
        response = requests.get(api_url)
        data = response.json()
        # Assuming the balance is in 'balance' key; adjust based on actual API response
        return float(data.get('balance', 0))
    except Exception as e:
        print(f"Error fetching balance from {api_url}: {e}")
        return None

def send_telegram_message(bot_token, chat_id, message):
    try:
        bot = telegram.Bot(token=bot_token)
        bot.send_message(chat_id=chat_id, text=message)
    except Exception as e:
        print(f"Error sending Telegram message: {e}")

def monitor_balances():
    while running:
        cursor.execute('SELECT * FROM apis')
        apis = cursor.fetchall()
        configs = get_telegram_configs()
        
        for api in apis:
            api_id, api_url = api
            current_balance = get_balance(api_url)
            if current_balance is None:
                continue
            
            cursor.execute('SELECT last_balance FROM balances WHERE api_id = ?', (api_id,))
            result = cursor.fetchone()
            if result:
                last_balance = result[0]
                if current_balance != last_balance:
                    change_type = "thanh toán" if current_balance < last_balance else "cộng tiền"
                    message = f"Số dư thay đổi: {change_type}. Số dư cuối cùng: {current_balance}"
                    for config in configs:
                        send_telegram_message(config['bot_token'], config['chat_id'], message)
                    cursor.execute('UPDATE balances SET last_balance = ?, last_check = ? WHERE api_id = ?',
                                   (current_balance, datetime.now(), api_id))
            else:
                cursor.execute('INSERT INTO balances (api_id, last_balance, last_check) VALUES (?, ?, ?)',
                               (api_id, current_balance, datetime.now()))
            conn.commit()
        
        time.sleep(CHECK_INTERVAL)

# Start monitoring thread
threading.Thread(target=monitor_balances, daemon=True).start()

def get_apis():
    cursor.execute('SELECT * FROM apis')
    return [{'id': row[0], 'api_url': row[1]} for row in cursor.fetchall()]

def add_api(api_url):
    cursor.execute('INSERT INTO apis (api_url) VALUES (?)', (api_url,))
    conn.commit()

def delete_api(api_id):
    cursor.execute('DELETE FROM apis WHERE id = ?', (api_id,))
    cursor.execute('DELETE FROM balances WHERE api_id = ?', (api_id,))
    conn.commit()

def get_telegram_configs():
    cursor.execute('SELECT * FROM telegram_configs')
    return [{'id': row[0], 'bot_token': row[1], 'chat_id': row[2]} for row in cursor.fetchall()]

def add_telegram_config(bot_token, chat_id):
    cursor.execute('INSERT INTO telegram_configs (bot_token, chat_id) VALUES (?, ?)', (bot_token, chat_id))
    conn.commit()

def delete_telegram_config(config_id):
    cursor.execute('DELETE FROM telegram_configs WHERE id = ?', (config_id,))
    conn.commit()

@auth.verify_password
def verify_password(username, password):
    if username == '' and check_password_hash(PASSWORD_HASH, password):
        return True
    return False

# Login page
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form['password']
        if check_password_hash(PASSWORD_HASH, password):
            session['authenticated'] = True
            return redirect(url_for('dashboard'))
        else:
            return render_template_string(LOGIN_TEMPLATE, error="Invalid password")
    return render_template_string(LOGIN_TEMPLATE)

# Dashboard
@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if not session.get('authenticated'):
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        if 'add_api' in request.form:
            api_url = request.form['api_url']
            add_api(api_url)
        elif 'delete_api' in request.form:
            api_id = int(request.form['api_id'])
            delete_api(api_id)
        elif 'add_config' in request.form:
            bot_token = request.form['bot_token']
            chat_id = request.form['chat_id']
            add_telegram_config(bot_token, chat_id)
        elif 'delete_config' in request.form:
            config_id = int(request.form['config_id'])
            delete_telegram_config(config_id)
        elif 'backup' in request.form:
            return backup_data()
    
    apis = get_apis()
    configs = get_telegram_configs()
    return render_template_string(DASHBOARD_TEMPLATE, apis=apis, configs=configs)

def backup_data():
    data = {
        'apis': get_apis(),
        'configs': get_telegram_configs(),
        'balances': []
    }
    cursor.execute('SELECT * FROM balances')
    for row in cursor.fetchall():
        data['balances'].append({'api_id': row[0], 'last_balance': row[1], 'last_check': row[2]})
    
    with open('backup.json', 'w') as f:
        json.dump(data, f)
    
    return send_file('backup.json', as_attachment=True)

# Logout
@app.route('/logout')
def logout():
    session.pop('authenticated', None)
    return redirect(url_for('login'))

# Stop monitoring when app stops (for development)
@app.teardown_appcontext
def teardown(exception):
    global running
    running = False

# HTML Templates with Universe Theme
LOGIN_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Login - Balance Monitor</title>
    <style>
        body {
            background-image: url('https://source.unsplash.com/random/1920x1080/?space,universe');
            background-size: cover;
            font-family: 'Arial', sans-serif;
            color: white;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
        }
        .login-container {
            background: rgba(0, 0, 0, 0.7);
            padding: 40px;
            border-radius: 15px;
            box-shadow: 0 0 20px rgba(255, 255, 255, 0.5);
            text-align: center;
            width: 300px;
        }
        input[type="password"] {
            width: 100%;
            padding: 10px;
            margin: 10px 0;
            border: none;
            border-radius: 5px;
        }
        button {
            width: 100%;
            padding: 10px;
            background: #4CAF50;
            border: none;
            color: white;
            border-radius: 5px;
            cursor: pointer;
        }
        button:hover {
            background: #45a049;
        }
        .error {
            color: red;
        }
        .copyright {
            margin-top: 20px;
            font-size: 12px;
        }
        .verified {
            display: inline-block;
            width: 16px;
            height: 16px;
            background: #1DA1F2;
            border-radius: 50%;
            color: white;
            text-align: center;
            line-height: 16px;
            margin-left: 5px;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <h2>Enter Password</h2>
        <form method="POST">
            <input type="password" name="password" placeholder="Password" required>
            <button type="submit">Login</button>
        </form>
        {% if error %}
            <p class="error">{{ error }}</p>
        {% endif %}
        <div class="copyright">
            Bot được bảo dưỡng và phát triển bởi Admin Văn Linh <span class="verified">✓</span>
        </div>
    </div>
</body>
</html>
'''

DASHBOARD_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Dashboard - Balance Monitor</title>
    <style>
        body {
            background-image: url('https://source.unsplash.com/random/1920x1080/?space,universe');
            background-size: cover;
            font-family: 'Arial', sans-serif;
            color: white;
            padding: 20px;
        }
        .container {
            background: rgba(0, 0, 0, 0.7);
            padding: 20px;
            border-radius: 15px;
            box-shadow: 0 0 20px rgba(255, 255, 255, 0.5);
        }
        h2 {
            text-align: center;
        }
        form {
            margin-bottom: 20px;
        }
        input {
            padding: 10px;
            margin: 5px;
            border: none;
            border-radius: 5px;
        }
        button {
            padding: 10px;
            background: #4CAF50;
            border: none;
            color: white;
            border-radius: 5px;
            cursor: pointer;
        }
        button:hover {
            background: #45a049;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 20px;
        }
        th, td {
            padding: 10px;
            text-align: left;
            border-bottom: 1px solid white;
        }
        .delete-btn {
            background: #f44336;
        }
        .delete-btn:hover {
            background: #da190b;
        }
        .copyright {
            text-align: center;
            font-size: 12px;
            margin-top: 20px;
        }
        .verified {
            display: inline-block;
            width: 16px;
            height: 16px;
            background: #1DA1F2;
            border-radius: 50%;
            color: white;
            text-align: center;
            line-height: 16px;
            margin-left: 5px;
        }
        a {
            color: white;
            text-decoration: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <h2>Balance Monitor Dashboard</h2>
        
        <h3>Add API URL</h3>
        <form method="POST">
            <input type="text" name="api_url" placeholder="API URL" required>
            <button type="submit" name="add_api">Add API</button>
        </form>
        
        <h3>APIs List</h3>
        <table>
            <tr><th>ID</th><th>API URL</th><th>Action</th></tr>
            {% for api in apis %}
            <tr>
                <td>{{ api.id }}</td>
                <td>{{ api.api_url }}</td>
                <td>
                    <form method="POST" style="display:inline;">
                        <input type="hidden" name="api_id" value="{{ api.id }}">
                        <button type="submit" name="delete_api" class="delete-btn">Delete</button>
                    </form>
                </td>
            </tr>
            {% endfor %}
        </table>
        
        <h3>Add Telegram Config</h3>
        <form method="POST">
            <input type="text" name="bot_token" placeholder="Bot Token" required>
            <input type="text" name="chat_id" placeholder="Chat ID" required>
            <button type="submit" name="add_config">Add Config</button>
        </form>
        
        <h3>Telegram Configs List</h3>
        <table>
            <tr><th>ID</th><th>Bot Token</th><th>Chat ID</th><th>Action</th></tr>
            {% for config in configs %}
            <tr>
                <td>{{ config.id }}</td>
                <td>{{ config.bot_token }}</td>
                <td>{{ config.chat_id }}</td>
                <td>
                    <form method="POST" style="display:inline;">
                        <input type="hidden" name="config_id" value="{{ config.id }}">
                        <button type="submit" name="delete_config" class="delete-btn">Delete</button>
                    </form>
                </td>
            </tr>
            {% endfor %}
        </table>
        
        <h3>Backup Data</h3>
        <form method="POST">
            <button type="submit" name="backup">Download Backup</button>
        </form>
        
        <a href="{{ url_for('logout') }}">Logout</a>
    </div>
    <div class="copyright">
        Bot được bảo dưỡng và phát triển bởi Admin Văn Linh <span class="verified">✓</span>
    </div>
</body>
</html>
'''

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
