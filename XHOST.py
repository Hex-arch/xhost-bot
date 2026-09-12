# -*- coding: utf-8 -*-
import telebot
import subprocess
import os
import zipfile
import tempfile
import shutil
from telebot import types
import time
from datetime import datetime, timedelta
import psutil
import sqlite3
import json
import logging
import signal
import threading
import re
import sys
import atexit
import requests
import socket
import secrets
from urllib.parse import urljoin

# --- Flask Keep Alive ---
from flask import Flask, request, Response
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return Response(
        """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>XHOST</title>
<style>
body{margin:0;background:#0b0d12;color:#f5f7fb;font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;display:grid;place-items:center;min-height:100vh}
.card{width:min(92vw,520px);padding:30px;border:1px solid #252a35;border-radius:22px;background:#11141b;box-shadow:0 20px 60px rgba(0,0,0,.35)}
.brand{font-size:13px;letter-spacing:.18em;text-transform:uppercase;color:#9da7b8}.title{font-size:36px;font-weight:800;margin:8px 0}.sub{color:#9da7b8}.status{display:inline-flex;gap:8px;align-items:center;margin-top:22px;padding:9px 13px;border-radius:999px;background:#171c25;color:#dce4ef;font-size:14px}.dot{width:8px;height:8px;border-radius:50%;background:#6ee7a0}
</style></head><body><main class="card"><div class="brand">XHOST // CLOUD HOST</div><div class="title">Service Online</div><div class="sub">Telegram hosting gateway is running.</div><div class="status"><span class="dot"></span> Proxy ready</div></main></body></html>""",
        mimetype='text/html'
    )

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    print("Flask Keep-Alive server started.")
# --- End Flask Keep Alive ---

# --- Configuration ---
TOKEN = os.environ.get('BOT_TOKEN', '')
if not TOKEN:
    raise RuntimeError('BOT_TOKEN environment variable is required.')
OWNER_ID = 7305141058
ADMIN_ID = 7305141058
YOUR_USERNAME = '@X1n0q'
UPDATE_CHANNEL = 'https://t.me/Hexmaincuh'
CHANNEL_USERNAME = '@Hexmaincuh'

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_BOTS_DIR = os.path.join(BASE_DIR, 'upload_bots')
IROTECH_DIR = os.path.join(BASE_DIR, 'inf')
DATABASE_PATH = os.path.join(IROTECH_DIR, 'bot_data.db')

FREE_USER_LIMIT = 1
SUBSCRIBED_USER_LIMIT = 5
ADMIN_LIMIT = 10
OWNER_LIMIT = float('inf')

os.makedirs(UPLOAD_BOTS_DIR, exist_ok=True)
os.makedirs(IROTECH_DIR, exist_ok=True)

bot = telebot.TeleBot(TOKEN)

# --- Data structures ---
bot_scripts = {}
user_subscriptions = {}
user_files = {}
active_users = set()
admin_ids = {ADMIN_ID, OWNER_ID}
bot_locked = False
verified_users = set()
# Web-app registry: token -> running uploaded web application.
web_apps = {}
WEB_PORT_MIN = int(os.environ.get('WEB_PORT_MIN', '10000'))
WEB_PORT_MAX = int(os.environ.get('WEB_PORT_MAX', '20000'))
# Prefer Render's own service URL so the web-app button always points at
# the XHOST service that is actually running this proxy. PUBLIC_BASE_URL
# remains available as a fallback for other hosting providers.
PUBLIC_BASE_URL = (os.environ.get('RENDER_EXTERNAL_URL') or
                   os.environ.get('PUBLIC_BASE_URL') or
                   os.environ.get('RENDER_EXTERNAL_HOSTNAME'))
if PUBLIC_BASE_URL and not PUBLIC_BASE_URL.startswith(('http://', 'https://')):
    PUBLIC_BASE_URL = 'https://' + PUBLIC_BASE_URL
PUBLIC_BASE_URL = PUBLIC_BASE_URL.rstrip('/') if PUBLIC_BASE_URL else None
VERIFIED_TABLE = 'verified_users'

# --- Logging ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Button layouts ---
COMMAND_BUTTONS_LAYOUT_USER_SPEC = [
    ["◈ Updates"],
    ["＋ Upload", "▣ My Files"],
    ["⚡ Ping", "◌ Statistics"],
    ["⌘ Command", "◎ Owner"]
]
ADMIN_COMMAND_BUTTONS_LAYOUT_USER_SPEC = [
    ["◈ Updates"],
    ["＋ Upload", "▣ My Files"],
    ["⚡ Ping", "◌ Statistics"],
    ["◇ Premium", "◉ Broadcast"],
    ["🔒 Lock Bot", "▶ Run All"],
    ["⌘ Command", "⚙ Admin Panel"],
    ["◎ Owner"]
]

# --- Database ---
def init_db():
    logger.info(f"Initializing database at: {DATABASE_PATH}")
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions
                     (user_id INTEGER PRIMARY KEY, expiry TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_files
                     (user_id INTEGER, file_name TEXT, file_type TEXT,
                      PRIMARY KEY (user_id, file_name))''')
        c.execute('''CREATE TABLE IF NOT EXISTS active_users
                     (user_id INTEGER PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS admins
                     (user_id INTEGER PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS verified_users
                     (user_id INTEGER PRIMARY KEY, verified_at TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS verification_messages
                     (user_id INTEGER PRIMARY KEY, message_id INTEGER)''')
        c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (OWNER_ID,))
        if ADMIN_ID != OWNER_ID:
            c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (ADMIN_ID,))
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}", exc_info=True)

def load_data():
    logger.info("Loading data from database...")
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT user_id, expiry FROM subscriptions')
        for user_id, expiry in c.fetchall():
            try:
                user_subscriptions[user_id] = {'expiry': datetime.fromisoformat(expiry)}
            except ValueError:
                logger.warning(f"⚠️ Invalid expiry format for {user_id}: {expiry}")

        c.execute('SELECT user_id, file_name, file_type FROM user_files')
        for user_id, file_name, file_type in c.fetchall():
            user_files.setdefault(user_id, []).append((file_name, file_type))

        c.execute('SELECT user_id FROM active_users')
        active_users.update(uid for (uid,) in c.fetchall())

        c.execute('SELECT user_id FROM admins')
        admin_ids.update(uid for (uid,) in c.fetchall())

        c.execute('SELECT user_id FROM verified_users')
        verified_users.update(uid for (uid,) in c.fetchall())

        conn.close()
        logger.info(f"Data loaded: {len(active_users)} users, {len(user_subscriptions)} subs, {len(admin_ids)} admins, {len(verified_users)} verified.")
    except Exception as e:
        logger.error(f"❌ Error loading data: {e}", exc_info=True)

init_db()
load_data()
# --- End Database ---

# --- Verification System ---
def is_user_verified(user_id):
    return user_id in verified_users

def save_verified_user(user_id):
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO verified_users (user_id, verified_at) VALUES (?, ?)',
                  (user_id, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        verified_users.add(user_id)
        return True
    except Exception as e:
        logger.error(f"❌ Save verified failed: {e}")
        return False

def remove_verified_user(user_id):
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('DELETE FROM verified_users WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        verified_users.discard(user_id)
        return True
    except Exception as e:
        logger.error(f"❌ Remove verified failed: {e}")
        return False

def check_channel_membership(user_id):
    try:
        if user_id in admin_ids:
            return True, "admin"
        chat_member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        status = chat_member.status
        if status in ['member', 'creator', 'administrator']:
            return True, status
        return False, status
    except telebot.apihelper.ApiTelegramException as e:
        err = str(e).lower()
        if "user not found" in err:
            return False, "not_found"
        if "chat not found" in err:
            return False, "channel_error"
        return False, "error"
    except Exception as e:
        logger.error(f"Membership check error for {user_id}: {e}")
        return False, "error"

def require_verification(func):
    def wrapper(message_or_call):
        user_id = None
        chat_id = None
        if hasattr(message_or_call, 'from_user'):
            user_id = message_or_call.from_user.id
            chat_id = message_or_call.chat.id if hasattr(message_or_call, 'chat') else message_or_call.message.chat.id
        else:
            logger.warning(f"Unknown object in require_verification: {type(message_or_call)}")
            return

        if user_id in admin_ids:
            return func(message_or_call)

        if is_user_verified(user_id):
            is_member, _ = check_channel_membership(user_id)
            if is_member:
                return func(message_or_call)
            remove_verified_user(user_id)
            send_verification_prompt(chat_id, user_id)
            return

        send_verification_prompt(chat_id, user_id)
        return
    return wrapper

def send_verification_prompt(chat_id, user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📢 Join Channel", url=UPDATE_CHANNEL),
        types.InlineKeyboardButton("✅ Verify Now", callback_data=f"verify_{user_id}")
    )
    msg = bot.send_message(
        chat_id,
        "🔒 **Channel Verification Required**\n\n"
        "You must join our channel before you can use this bot.\n\n"
        "👇 Join the channel below, then press **Verify Now**.",
        reply_markup=markup,
        parse_mode='Markdown'
    )
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO verification_messages (user_id, message_id) VALUES (?, ?)',
                  (user_id, msg.message_id))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error storing verification msg: {e}")

def clear_verification_prompt(chat_id, user_id):
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('SELECT message_id FROM verification_messages WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        conn.close()
        if result:
            try:
                bot.delete_message(chat_id, result[0])
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Error clearing verification prompt: {e}")

def process_verification(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    try:
        expected_user_id = int(call.data.split('_')[1])
    except Exception:
        return
    if user_id != expected_user_id:
        bot.answer_callback_query(call.id, "⚠️ You can only verify yourself.", show_alert=True)
        return

    is_member, _ = check_channel_membership(user_id)
    if is_member:
        save_verified_user(user_id)
        clear_verification_prompt(chat_id, user_id)
        bot.answer_callback_query(call.id, "✅ Verification Successful!")
        bot.send_message(chat_id, "✅ **Verification Successful!**\n\nLoading the main menu...", parse_mode='Markdown')
        _logic_send_welcome(call.message)
    else:
        bot.answer_callback_query(call.id, "❌ Verification Failed - You haven't joined the channel.", show_alert=True)
        clear_verification_prompt(chat_id, user_id)
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("📢 Join Channel", url=UPDATE_CHANNEL),
            types.InlineKeyboardButton("✅ Verify Now", callback_data=f"verify_{user_id}")
        )
        bot.send_message(
            chat_id,
            "❌ **Verification Failed**\n\nYou haven't joined the required channel yet.\n\nPlease join the channel and try again.",
            reply_markup=markup,
            parse_mode='Markdown'
        )

# --- Helper Functions ---
def get_user_folder(user_id):
    user_folder = os.path.join(UPLOAD_BOTS_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)
    return user_folder

def get_user_file_limit(user_id):
    if user_id == OWNER_ID:
        return OWNER_LIMIT
    if user_id in admin_ids:
        return ADMIN_LIMIT
    if user_id in user_subscriptions:
        expiry = user_subscriptions[user_id].get('expiry')
        if expiry and expiry > datetime.now():
            return SUBSCRIBED_USER_LIMIT
    return FREE_USER_LIMIT

def get_user_file_count(user_id):
    return len(user_files.get(user_id, []))

def is_bot_running(script_owner_id, file_name):
    script_key = f"{script_owner_id}_{file_name}"
    script_info = bot_scripts.get(script_key)
    if script_info and script_info.get('process'):
        try:
            proc = psutil.Process(script_info['process'].pid)
            is_running = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            if not is_running:
                if 'log_file' in script_info and hasattr(script_info['log_file'], 'close') and not script_info['log_file'].closed:
                    try: script_info['log_file'].close()
                    except Exception: pass
                if script_key in bot_scripts: del bot_scripts[script_key]
            return is_running
        except psutil.NoSuchProcess:
            if 'log_file' in script_info and hasattr(script_info['log_file'], 'close') and not script_info['log_file'].closed:
                try: script_info['log_file'].close()
                except Exception: pass
            if script_key in bot_scripts: del bot_scripts[script_key]
            return False
        except Exception as e:
            logger.error(f"Error checking process for {script_key}: {e}")
            return False
    return False

def kill_process_tree(process_info):
    pid = None
    script_key = process_info.get('script_key', 'N/A')
    try:
        if 'log_file' in process_info and hasattr(process_info['log_file'], 'close') and not process_info['log_file'].closed:
            try: process_info['log_file'].close()
            except Exception as e: logger.error(f"Log close failed for {script_key}: {e}")

        process = process_info.get('process')
        if process and hasattr(process, 'pid'):
            pid = process.pid
            if pid:
                try:
                    parent = psutil.Process(pid)
                    children = parent.children(recursive=True)
                    for child in children:
                        try: child.terminate()
                        except Exception:
                            try: child.kill()
                            except Exception: pass
                    psutil.wait_procs(children, timeout=1)
                    for p in children:
                        try: p.kill()
                        except Exception: pass
                    try:
                        parent.terminate()
                        try: parent.wait(timeout=1)
                        except psutil.TimeoutExpired:
                            parent.kill()
                    except psutil.NoSuchProcess:
                        pass
                    except Exception:
                        try: parent.kill()
                        except Exception: pass
                except psutil.NoSuchProcess:
                    pass
    except Exception as e:
        logger.error(f"Error killing process for {pid}: {e}")

# --- Package install helpers ---
TELEGRAM_MODULES = {
    'telebot': 'pyTelegramBotAPI',
    'telegram': 'python-telegram-bot',
    'python_telegram_bot': 'python-telegram-bot',
    'aiogram': 'aiogram',
    'pyrogram': 'pyrogram',
    'telethon': 'telethon',
    'telethon.sync': 'telethon',
    'telepot': 'telepot',
    'tgcrypto': 'tgcrypto',
    'bs4': 'beautifulsoup4',
    'requests': 'requests',
    'pillow': 'Pillow',
    'cv2': 'opencv-python',
    'yaml': 'PyYAML',
    'dotenv': 'python-dotenv',
    'dateutil': 'python-dateutil',
    'pandas': 'pandas',
    'numpy': 'numpy',
    'flask': 'Flask',
    'django': 'Django',
    'sqlalchemy': 'SQLAlchemy',
    'psutil': 'psutil',
}

def attempt_install_pip(module_name, message):
    package_name = TELEGRAM_MODULES.get(module_name.lower(), module_name)
    if package_name is None:
        return False
    try:
        bot.reply_to(message, f"🐍 Installing `{package_name}`...", parse_mode='Markdown')
        result = subprocess.run([sys.executable, '-m', 'pip', 'install', package_name],
                                capture_output=True, text=True, check=False,
                                encoding='utf-8', errors='ignore')
        if result.returncode == 0:
            bot.reply_to(message, f"✅ Installed `{package_name}`.", parse_mode='Markdown')
            return True
        error_msg = f"❌ Failed to install `{package_name}`:\n```\n{result.stderr or result.stdout}\n```"
        if len(error_msg) > 4000: error_msg = error_msg[:4000] + "\n...(truncated)"
        bot.reply_to(message, error_msg, parse_mode='Markdown')
        return False
    except Exception as e:
        bot.reply_to(message, f"❌ Error installing: {e}")
        return False

def attempt_install_npm(module_name, user_folder, message):
    try:
        bot.reply_to(message, f"🟠 Installing Node package `{module_name}`...", parse_mode='Markdown')
        result = subprocess.run(['npm', 'install', module_name], capture_output=True, text=True,
                                check=False, cwd=user_folder, encoding='utf-8', errors='ignore')
        if result.returncode == 0:
            bot.reply_to(message, f"✅ Installed `{module_name}`.", parse_mode='Markdown')
            return True
        error_msg = f"❌ Failed to install `{module_name}`:\n```\n{result.stderr or result.stdout}\n```"
        if len(error_msg) > 4000: error_msg = error_msg[:4000] + "\n...(truncated)"
        bot.reply_to(message, error_msg, parse_mode='Markdown')
        return False
    except FileNotFoundError:
        bot.reply_to(message, "❌ 'npm' not found.")
        return False
    except Exception as e:
        bot.reply_to(message, f"❌ Error installing Node package: {e}")
        return False

def is_web_app_script(script_path):
    """Best-effort detection for uploaded Flask/Flask-SocketIO apps."""
    try:
        with open(script_path, 'r', encoding='utf-8', errors='ignore') as f:
            source = f.read(30000)
        return bool(re.search(r"(?:from|import)\s+flask(?:_socketio)?|Flask\s*\(", source))
    except Exception:
        return False

def allocate_web_port():
    """Find an unused local TCP port for an uploaded web app."""
    used = {info.get('port') for info in web_apps.values() if info.get('port')}
    for port in range(WEB_PORT_MIN, WEB_PORT_MAX + 1):
        if port in used:
            continue
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('127.0.0.1', port))
            return port
        except OSError:
            continue
        finally:
            sock.close()
    raise RuntimeError('No free web-app ports available.')

def register_web_app(script_key, script_owner_id, file_name, port):
    token = secrets.token_urlsafe(18)
    web_apps[token] = {
        'script_key': script_key,
        'script_owner_id': script_owner_id,
        'file_name': file_name,
        'port': port,
    }
    return token

def unregister_web_app(script_key):
    for token, info in list(web_apps.items()):
        if info.get('script_key') == script_key:
            web_apps.pop(token, None)

def get_web_app_url(script_key):
    if not PUBLIC_BASE_URL:
        return None
    for token, info in web_apps.items():
        if info.get('script_key') == script_key:
            return f"{PUBLIC_BASE_URL}/web/{token}/"
    return None

def create_web_proxy_routes():
    """Proxy registered uploaded web apps through the XHOST public URL.

    Supports normal HTTP routes and Socket.IO polling. WebSocket upgrades are
    intentionally not required because the Devidciker frontend is rewritten
    to use polling through this HTTP proxy.
    """
    def _proxy(token, subpath=''):
        info = web_apps.get(token)
        if not info:
            return 'Web app not found or no longer running.', 404

        process_info = bot_scripts.get(info['script_key'])
        process = process_info.get('process') if process_info else None
        if not process or process.poll() is not None:
            unregister_web_app(info['script_key'])
            return 'Web app is not running.', 404

        clean_subpath = (subpath or '').lstrip('/')
        target = f"http://127.0.0.1:{info['port']}/"
        if clean_subpath:
            target += clean_subpath

        forward_headers = {}
        for key, value in request.headers.items():
            low = key.lower()
            if low not in {'host', 'content-length', 'connection', 'accept-encoding'}:
                forward_headers[key] = value
        forward_headers['X-Forwarded-Proto'] = request.headers.get('X-Forwarded-Proto', 'https')
        forward_headers['X-Forwarded-Host'] = request.host
        forward_headers['X-Forwarded-Prefix'] = f'/web/{token}'

        try:
            upstream = requests.request(
                method=request.method,
                url=target,
                params=request.args,
                data=request.get_data(cache=True),
                headers=forward_headers,
                cookies=request.cookies,
                allow_redirects=False,
                timeout=60,
            )
        except requests.RequestException as exc:
            logger.warning('Web proxy error for %s: %s', info['script_key'], exc)
            return 'Web app is not responding.', 502

        body = upstream.content
        content_type = upstream.headers.get('Content-Type', '')

        if 'text/html' in content_type.lower():
            try:
                html = body.decode(upstream.encoding or 'utf-8', errors='ignore')
                prefix = f'/web/{token}/'
                # Keep the uploaded app's absolute links inside its proxy path.
                replacements = {
                    'href="/static/': f'href="{prefix}static/',
                    "href='/static/": f"href='{prefix}static/",
                    'src="/static/': f'src="{prefix}static/',
                    "src='/static/": f"src='{prefix}static/",
                    'fetch("/api/': f'fetch("{prefix}api/',
                    "fetch('/api/": f"fetch('{prefix}api/",
                    'window.location.href = "/api/': f'window.location.href = "{prefix}api/',
                    "window.location.href = '/api/": f"window.location.href = '{prefix}api/",
                    "transports: ['websocket', 'polling']": "transports: ['polling']",
                    'transports: ["websocket", "polling"]': 'transports: ["polling"]',
                }
                for old, new in replacements.items():
                    html = html.replace(old, new)

                # Explicitly route Socket.IO through this app's proxy path.
                html = html.replace(
                    'const socket = io({',
                    f"const socket = io({{ path: '{prefix}socket.io',"
                )
                body = html.encode('utf-8')
            except Exception as exc:
                logger.debug('HTML rewrite skipped: %s', exc)

        out_headers = []
        excluded = {'content-encoding', 'content-length', 'transfer-encoding', 'connection', 'keep-alive'}
        for key, value in upstream.headers.items():
            if key.lower() in excluded:
                continue
            # Rewrite redirects so the browser stays under the proxy path.
            if key.lower() == 'location' and value.startswith('/'):
                value = f'/web/{token}{value}'
            if key.lower() == 'set-cookie':
                value = re.sub(r'(?i)path=/', f'Path=/web/{token}/', value)
            out_headers.append((key, value))

        return Response(body, status=upstream.status_code, headers=out_headers)

    @app.route('/web/<token>', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
    @app.route('/web/<token>/', defaults={'subpath': ''}, methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
    @app.route('/web/<token>/<path:subpath>', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'])
    def web_app_proxy(token, subpath=''):
        return _proxy(token, subpath)

create_web_proxy_routes()

@app.route('/healthz')
def healthz():
    return Response('ok', mimetype='text/plain')

def run_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1):
    max_attempts = 2
    if attempt > max_attempts:
        bot.reply_to(message_obj_for_reply, f"❌ Failed to run '{file_name}' after {max_attempts} attempts.")
        return

    script_key = f"{script_owner_id}_{file_name}"
    logger.info(f"Attempt {attempt} to run: {script_path} (Key: {script_key})")
    web_app = is_web_app_script(script_path)
    web_port = None
    web_token = None
    if web_app:
        try:
            web_port = allocate_web_port()
        except Exception as e:
            bot.reply_to(message_obj_for_reply, f"❌ Could not allocate a web port: {e}")
            return

    try:
        if not os.path.exists(script_path):
            bot.reply_to(message_obj_for_reply, f"❌ Script '{file_name}' not found!")
            if script_owner_id in user_files:
                user_files[script_owner_id] = [f for f in user_files.get(script_owner_id, []) if f[0] != file_name]
            remove_user_file_db(script_owner_id, file_name)
            return

        if attempt == 1:
            check_proc = None
            try:
                env = os.environ.copy()
                if web_app and web_port:
                    env['PORT'] = str(web_port)
                    env['HOST'] = '0.0.0.0'
                check_proc = subprocess.Popen([get_script_python(script_path, user_folder), script_path], cwd=user_folder, env=env,
                                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                              text=True, encoding='utf-8', errors='ignore')
                stdout, stderr = check_proc.communicate(timeout=5)
                return_code = check_proc.returncode
                if return_code != 0 and stderr:
                    match_py = re.search(r"ModuleNotFoundError: No module named '(.+?)'", stderr)
                    if match_py:
                        module_name = match_py.group(1).strip().strip("'\"")
                        if attempt_install_pip(module_name, message_obj_for_reply):
                            time.sleep(2)
                            threading.Thread(target=run_script, args=(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt + 1)).start()
                            return
                        else:
                            return
                    else:
                        error_summary = stderr[:500]
                        bot.reply_to(message_obj_for_reply, f"❌ Error in '{file_name}':\n```\n{error_summary}\n```", parse_mode='Markdown')
                        return
            except subprocess.TimeoutExpired:
                if check_proc and check_proc.poll() is None: check_proc.kill(); check_proc.communicate()
            except FileNotFoundError:
                bot.reply_to(message_obj_for_reply, f"❌ Python interpreter not found.")
                return
            except Exception as e:
                bot.reply_to(message_obj_for_reply, f"❌ Pre-check error: {e}")
                return
            finally:
                if check_proc and check_proc.poll() is None:
                    check_proc.kill(); check_proc.communicate()

        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = None
        process = None
        try:
            log_file = open(log_file_path, 'w', encoding='utf-8', errors='ignore')
        except Exception as e:
            bot.reply_to(message_obj_for_reply, f"❌ Cannot open log file: {e}")
            return

        try:
            startupinfo = None
            creationflags = 0
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            env = os.environ.copy()
            if web_app and web_port:
                env['PORT'] = str(web_port)
                env['HOST'] = '0.0.0.0'
            process = subprocess.Popen(
                [get_script_python(script_path, user_folder), script_path], cwd=user_folder, env=env,
                stdout=log_file, stderr=log_file, stdin=subprocess.PIPE,
                startupinfo=startupinfo, creationflags=creationflags,
                encoding='utf-8', errors='ignore'
            )
            bot_scripts[script_key] = {
                'process': process, 'log_file': log_file, 'file_name': file_name,
                'chat_id': message_obj_for_reply.chat.id if message_obj_for_reply else OWNER_ID,
                'script_owner_id': script_owner_id,
                'start_time': datetime.now(), 'user_folder': user_folder,
                'type': 'py', 'script_key': script_key,
                'web_app': web_app, 'web_port': web_port, 'web_token': None
            }
            if web_app and web_port:
                web_token = register_web_app(script_key, script_owner_id, file_name, web_port)
                bot_scripts[script_key]['web_token'] = web_token
            if web_app:
                web_url = get_web_app_url(script_key)
                if web_url:
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton('↗ Open Web App', url=web_url))
                    bot.reply_to(message_obj_for_reply, f"<b>WEB APP ONLINE</b>\n<code>{file_name}</code> · PID {process.pid}\n\nOpen your app using the button below.", reply_markup=markup)
                else:
                    bot.reply_to(message_obj_for_reply, f"✅ Web app '{file_name}' started! (PID: {process.pid})\n⚠️ Set PUBLIC_BASE_URL in your hosting environment to enable the Open Web App button.")
            else:
                bot.reply_to(message_obj_for_reply, f"✅ Python script '{file_name}' started! (PID: {process.pid})")
        except FileNotFoundError:
            bot.reply_to(message_obj_for_reply, f"❌ Python interpreter not found.")
            if log_file and not log_file.closed: log_file.close()
            if script_key in bot_scripts: del bot_scripts[script_key]
        except Exception as e:
            if log_file and not log_file.closed: log_file.close()
            bot.reply_to(message_obj_for_reply, f"❌ Error starting: {e}")
            if process and process.poll() is None:
                kill_process_tree({'process': process, 'log_file': log_file, 'script_key': script_key})
            if script_key in bot_scripts: del bot_scripts[script_key]
    except Exception as e:
        bot.reply_to(message_obj_for_reply, f"❌ Unexpected error: {e}")
        if script_key in bot_scripts:
            kill_process_tree(bot_scripts[script_key])
            del bot_scripts[script_key]

def run_js_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1):
    max_attempts = 2
    if attempt > max_attempts:
        bot.reply_to(message_obj_for_reply, f"❌ Failed to run '{file_name}' after {max_attempts} attempts.")
        return

    script_key = f"{script_owner_id}_{file_name}"
    logger.info(f"Attempt {attempt} to run JS: {script_path}")

    try:
        if not os.path.exists(script_path):
            bot.reply_to(message_obj_for_reply, f"❌ Script '{file_name}' not found!")
            if script_owner_id in user_files:
                user_files[script_owner_id] = [f for f in user_files.get(script_owner_id, []) if f[0] != file_name]
            remove_user_file_db(script_owner_id, file_name)
            return

        if attempt == 1:
            check_proc = None
            try:
                check_proc = subprocess.Popen(['node', script_path], cwd=user_folder,
                                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                              text=True, encoding='utf-8', errors='ignore')
                stdout, stderr = check_proc.communicate(timeout=5)
                return_code = check_proc.returncode
                if return_code != 0 and stderr:
                    match_js = re.search(r"Cannot find module '(.+?)'", stderr)
                    if match_js:
                        module_name = match_js.group(1).strip().strip("'\"")
                        if not module_name.startswith('.') and not module_name.startswith('/'):
                            if attempt_install_npm(module_name, user_folder, message_obj_for_reply):
                                time.sleep(2)
                                threading.Thread(target=run_js_script, args=(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt + 1)).start()
                                return
                            else:
                                return
                    error_summary = stderr[:500]
                    bot.reply_to(message_obj_for_reply, f"❌ Error in '{file_name}':\n```\n{error_summary}\n```", parse_mode='Markdown')
                    return
            except subprocess.TimeoutExpired:
                if check_proc and check_proc.poll() is None: check_proc.kill(); check_proc.communicate()
            except FileNotFoundError:
                bot.reply_to(message_obj_for_reply, "❌ 'node' not found.")
                return
            except Exception as e:
                bot.reply_to(message_obj_for_reply, f"❌ Pre-check error: {e}")
                return
            finally:
                if check_proc and check_proc.poll() is None:
                    check_proc.kill(); check_proc.communicate()

        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = None
        process = None
        try:
            log_file = open(log_file_path, 'w', encoding='utf-8', errors='ignore')
        except Exception as e:
            bot.reply_to(message_obj_for_reply, f"❌ Cannot open log file: {e}")
            return

        try:
            startupinfo = None
            creationflags = 0
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            process = subprocess.Popen(
                ['node', script_path], cwd=user_folder,
                stdout=log_file, stderr=log_file, stdin=subprocess.PIPE,
                startupinfo=startupinfo, creationflags=creationflags,
                encoding='utf-8', errors='ignore'
            )
            bot_scripts[script_key] = {
                'process': process, 'log_file': log_file, 'file_name': file_name,
                'chat_id': message_obj_for_reply.chat.id if message_obj_for_reply else OWNER_ID,
                'script_owner_id': script_owner_id,
                'start_time': datetime.now(), 'user_folder': user_folder,
                'type': 'js', 'script_key': script_key
            }
            bot.reply_to(message_obj_for_reply, f"✅ JS script '{file_name}' started! (PID: {process.pid})")
        except FileNotFoundError:
            bot.reply_to(message_obj_for_reply, "❌ 'node' not found.")
            if log_file and not log_file.closed: log_file.close()
            if script_key in bot_scripts: del bot_scripts[script_key]
        except Exception as e:
            if log_file and not log_file.closed: log_file.close()
            bot.reply_to(message_obj_for_reply, f"❌ Error starting: {e}")
            if process and process.poll() is None:
                kill_process_tree({'process': process, 'log_file': log_file, 'script_key': script_key})
            if script_key in bot_scripts: del bot_scripts[script_key]
    except Exception as e:
        bot.reply_to(message_obj_for_reply, f"❌ Unexpected error: {e}")
        if script_key in bot_scripts:
            kill_process_tree(bot_scripts[script_key])
            del bot_scripts[script_key]

# --- Database Operations ---
DB_LOCK = threading.Lock()

def save_user_file(user_id, file_name, file_type='py'):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR REPLACE INTO user_files (user_id, file_name, file_type) VALUES (?, ?, ?)',
                      (user_id, file_name, file_type))
            conn.commit()
            user_files.setdefault(user_id, [])
            user_files[user_id] = [(fn, ft) for fn, ft in user_files[user_id] if fn != file_name]
            user_files[user_id].append((file_name, file_type))
        except sqlite3.Error as e:
            logger.error(f"SQLite error saving file: {e}")
        finally:
            conn.close()

def remove_user_file_db(user_id, file_name):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM user_files WHERE user_id = ? AND file_name = ?', (user_id, file_name))
            conn.commit()
            if user_id in user_files:
                user_files[user_id] = [f for f in user_files[user_id] if f[0] != file_name]
                if not user_files[user_id]: del user_files[user_id]
        except sqlite3.Error as e:
            logger.error(f"SQLite error removing file: {e}")
        finally:
            conn.close()

def add_active_user(user_id):
    active_users.add(user_id)
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR IGNORE INTO active_users (user_id) VALUES (?)', (user_id,))
            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"SQLite error adding active user: {e}")
        finally:
            conn.close()

def save_subscription(user_id, expiry):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            expiry_str = expiry.isoformat()
            c.execute('INSERT OR REPLACE INTO subscriptions (user_id, expiry) VALUES (?, ?)', (user_id, expiry_str))
            conn.commit()
            user_subscriptions[user_id] = {'expiry': expiry}
        except sqlite3.Error as e:
            logger.error(f"SQLite error saving subscription: {e}")
        finally:
            conn.close()

def remove_subscription_db(user_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM subscriptions WHERE user_id = ?', (user_id,))
            conn.commit()
            if user_id in user_subscriptions: del user_subscriptions[user_id]
        except sqlite3.Error as e:
            logger.error(f"SQLite error removing subscription: {e}")
        finally:
            conn.close()

def add_admin_db(admin_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (admin_id,))
            conn.commit()
            admin_ids.add(admin_id)
        except sqlite3.Error as e:
            logger.error(f"SQLite error adding admin: {e}")
        finally:
            conn.close()

def remove_admin_db(admin_id):
    if admin_id == OWNER_ID:
        return False
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        removed = False
        try:
            c.execute('SELECT 1 FROM admins WHERE user_id = ?', (admin_id,))
            if c.fetchone():
                c.execute('DELETE FROM admins WHERE user_id = ?', (admin_id,))
                conn.commit()
                removed = c.rowcount > 0
                if removed: admin_ids.discard(admin_id)
            else:
                admin_ids.discard(admin_id)
            return removed
        except sqlite3.Error as e:
            logger.error(f"SQLite error removing admin: {e}")
            return False
        finally:
            conn.close()
# --- End Database Operations ---

# --- Menu creation ---
def create_main_menu_inline(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton('◈ Updates', url=UPDATE_CHANNEL),
        types.InlineKeyboardButton('＋ Upload', callback_data='upload'),
        types.InlineKeyboardButton('▣ My Files', callback_data='check_files'),
        types.InlineKeyboardButton('⚡ Ping', callback_data='speed'),
        types.InlineKeyboardButton('⌘ Command', callback_data='send_command'),
        types.InlineKeyboardButton('◎ Owner', url=f'https://t.me/{YOUR_USERNAME.replace("@", "")}')
    ]
    if user_id in admin_ids:
        admin_buttons = [
            types.InlineKeyboardButton('◇ Premium', callback_data='subscription'),
            types.InlineKeyboardButton('◌ Statistics', callback_data='stats'),
            types.InlineKeyboardButton('🔒 Lock Bot' if not bot_locked else '🔓 Unlock Bot',
                                     callback_data='lock_bot' if not bot_locked else 'unlock_bot'),
            types.InlineKeyboardButton('◉ Broadcast', callback_data='broadcast'),
            types.InlineKeyboardButton('⚙ Admin Panel', callback_data='admin_panel'),
            types.InlineKeyboardButton('▶ Run All', callback_data='run_all_scripts')
        ]
        markup.add(buttons[0])
        markup.add(buttons[1], buttons[2])
        markup.add(buttons[3], admin_buttons[0])
        markup.add(admin_buttons[1], admin_buttons[3])
        markup.add(admin_buttons[2], admin_buttons[5])
        markup.add(buttons[4])
        markup.add(admin_buttons[4])
        markup.add(buttons[5])
    else:
        markup.add(buttons[0])
        markup.add(buttons[1], buttons[2])
        markup.add(buttons[3])
        markup.add(buttons[4])
        markup.add(types.InlineKeyboardButton('◌ Statistics', callback_data='stats'))
        markup.add(buttons[5])
    return markup

def create_reply_keyboard_main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    layout = ADMIN_COMMAND_BUTTONS_LAYOUT_USER_SPEC if user_id in admin_ids else COMMAND_BUTTONS_LAYOUT_USER_SPEC
    for row in layout:
        markup.add(*[types.KeyboardButton(text) for text in row])
    return markup

def create_control_buttons(script_owner_id, file_name, is_running=True):
    markup = types.InlineKeyboardMarkup(row_width=2)
    script_key = f"{script_owner_id}_{file_name}"
    script_info = bot_scripts.get(script_key, {})
    web_url = get_web_app_url(script_key) if script_info.get('web_app') else None
    if is_running:
        if web_url:
            markup.add(types.InlineKeyboardButton('↗ Open Web App', url=web_url))
        markup.row(
            types.InlineKeyboardButton("🔴 Stop", callback_data=f'stop_{script_owner_id}_{file_name}'),
            types.InlineKeyboardButton("🔄 Restart", callback_data=f'restart_{script_owner_id}_{file_name}')
        )
        markup.row(
            types.InlineKeyboardButton("🗑️ Delete", callback_data=f'delete_{script_owner_id}_{file_name}'),
            types.InlineKeyboardButton("📜 Logs", callback_data=f'logs_{script_owner_id}_{file_name}')
        )
    else:
        markup.row(
            types.InlineKeyboardButton("🟢 Start", callback_data=f'start_{script_owner_id}_{file_name}'),
            types.InlineKeyboardButton("🗑️ Delete", callback_data=f'delete_{script_owner_id}_{file_name}')
        )
        markup.row(
            types.InlineKeyboardButton("📜 View Logs", callback_data=f'logs_{script_owner_id}_{file_name}')
        )
    markup.add(types.InlineKeyboardButton("🔙 Back to Files", callback_data='check_files'))
    return markup

def create_admin_panel():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        types.InlineKeyboardButton('➕ Add Admin', callback_data='add_admin'),
        types.InlineKeyboardButton('➖ Remove Admin', callback_data='remove_admin')
    )
    markup.row(types.InlineKeyboardButton('📋 List Admins', callback_data='list_admins'))
    markup.row(types.InlineKeyboardButton('‹ Back to Main', callback_data='back_to_main'))
    return markup

def create_subscription_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        types.InlineKeyboardButton('➕ Add Subscription', callback_data='add_subscription'),
        types.InlineKeyboardButton('➖ Remove Subscription', callback_data='remove_subscription')
    )
    markup.row(types.InlineKeyboardButton('🔍 Check Subscription', callback_data='check_subscription'))
    markup.row(types.InlineKeyboardButton('‹ Back to Main', callback_data='back_to_main'))
    return markup

def create_send_command_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        types.InlineKeyboardButton('📝 Send to Process', callback_data='send_to_process'),
        types.InlineKeyboardButton('🔍 View All Logs', callback_data='view_all_logs')
    )
    markup.row(types.InlineKeyboardButton('‹ Back to Main', callback_data='back_to_main'))
    return markup
# --- End Menu Creation ---

# --- Isolated app environment helpers ---
def get_app_python(user_folder):
    """Return the per-upload virtualenv Python if it exists, otherwise host Python."""
    if os.name == 'nt':
        candidate = os.path.join(user_folder, '.venv', 'Scripts', 'python.exe')
    else:
        candidate = os.path.join(user_folder, '.venv', 'bin', 'python')
    return candidate if os.path.exists(candidate) else sys.executable


def install_requirements_isolated(user_folder, req_path, message):
    """Install uploaded-app requirements into its own venv with a hard timeout."""
    import venv
    venv_dir = os.path.join(user_folder, '.venv')
    try:
        if not os.path.exists(venv_dir):
            bot.reply_to(message, "🧪 Creating isolated Python environment...")
            venv.EnvBuilder(with_pip=True, clear=False, symlinks=False).create(venv_dir)
        app_python = get_app_python(user_folder)
        if app_python == sys.executable:
            raise RuntimeError("Could not create the app virtual environment.")

        bot.reply_to(message, "🔄 Installing Python deps in the app environment...")
        command = [app_python, '-m', 'pip', 'install', '--disable-pip-version-check',
                   '--prefer-binary', '-r', req_path]
        logger.info("Installing app requirements: %s", ' '.join(command))
        result = subprocess.run(
            command, cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='ignore', timeout=300, check=False
        )
        output = result.stdout or ''
        for line in output.splitlines()[-80:]:
            logger.info('[app pip] %s', line)
        if result.returncode != 0:
            tail = '\n'.join(output.splitlines()[-30:])
            raise RuntimeError(tail or f"pip exited with code {result.returncode}")
        bot.reply_to(message, "✅ Python deps installed.")
        return app_python
    except subprocess.TimeoutExpired:
        logger.error("Isolated dependency installation timed out after 5 minutes.")
        bot.reply_to(message, "❌ Python dependency installation timed out after 5 minutes.")
        return None
    except Exception as e:
        logger.error("Isolated dependency installation failed", exc_info=True)
        err = str(e)
        if len(err) > 3500:
            err = err[-3500:]
        bot.reply_to(message, f"❌ Python dependency installation failed:\n```\n{err}\n```",
                     parse_mode='Markdown')
        return None


def get_script_python(script_path, user_folder):
    """Use the uploaded app venv when available."""
    app_python = get_app_python(user_folder)
    if app_python != sys.executable:
        return app_python
    return sys.executable

# --- File Handling (NO security scanning) ---
def handle_zip_file(downloaded_file_content, file_name_zip, message):
    user_id = message.from_user.id
    user_folder = get_user_folder(user_id)
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp(prefix=f"user_{user_id}_zip_")
        zip_path = os.path.join(temp_dir, file_name_zip)
        with open(zip_path, 'wb') as new_file:
            new_file.write(downloaded_file_content)

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # Reject unsafe archive paths before extraction.
            for member in zip_ref.infolist():
                target = os.path.abspath(os.path.join(temp_dir, member.filename))
                if not target.startswith(os.path.abspath(temp_dir) + os.sep):
                    raise ValueError(f"Unsafe ZIP path: {member.filename}")
            zip_ref.extractall(temp_dir)

        target_dir = temp_dir
        root_files = os.listdir(target_dir)
        if not any(f.endswith(('.py', '.js')) for f in root_files):
            for root, dirs, files in os.walk(temp_dir):
                dirs[:] = [d for d in dirs if not d.startswith('.') and not d.startswith('__')]
                if any(f.endswith(('.py', '.js')) for f in files):
                    target_dir = root
                    break

        if target_dir != temp_dir:
            for item in os.listdir(target_dir):
                if item == file_name_zip:
                    continue
                s = os.path.join(target_dir, item)
                d = os.path.join(temp_dir, item)
                if os.path.exists(d):
                    if os.path.isdir(d): shutil.rmtree(d)
                    else: os.remove(d)
                shutil.move(s, d)
            extracted_items = os.listdir(temp_dir)
        else:
            extracted_items = root_files

        py_files = [f for f in extracted_items if f.endswith('.py')]
        js_files = [f for f in extracted_items if f.endswith('.js')]
        req_file = 'requirements.txt' if 'requirements.txt' in extracted_items else None
        pkg_json = 'package.json' if 'package.json' in extracted_items else None

        main_script_name = None
        file_type = None
        preferred_py = ['main.py', 'bot.py', 'app.py']
        preferred_js = ['index.js', 'main.js', 'bot.js', 'app.js']
        for preferred in preferred_py:
            if preferred in py_files:
                main_script_name, file_type = preferred, 'py'
                break
        if not main_script_name:
            for preferred in preferred_js:
                if preferred in js_files:
                    main_script_name, file_type = preferred, 'js'
                    break
        if not main_script_name:
            if py_files:
                main_script_name, file_type = py_files[0], 'py'
            elif js_files:
                main_script_name, file_type = js_files[0], 'js'
        if not main_script_name:
            bot.reply_to(message, "❌ No `.py` or `.js` script found in archive!")
            return

        # Move the actual application into its permanent user directory first.
        for item_name in os.listdir(temp_dir):
            if item_name == file_name_zip:
                continue
            src_path = os.path.join(temp_dir, item_name)
            dest_path = os.path.join(user_folder, item_name)
            if os.path.isdir(dest_path):
                shutil.rmtree(dest_path)
            elif os.path.exists(dest_path):
                os.remove(dest_path)
            shutil.move(src_path, dest_path)

        # Install Python dependencies in an isolated venv instead of XHOST's global Python.
        if req_file and file_type == 'py':
            req_path = os.path.join(user_folder, req_file)
            if install_requirements_isolated(user_folder, req_path, message) is None:
                return

        if pkg_json:
            bot.reply_to(message, "🔄 Installing Node deps...")
            try:
                result = subprocess.run(['npm', 'install'], capture_output=True, text=True,
                                        check=True, cwd=user_folder, encoding='utf-8', errors='ignore',
                                        timeout=300)
                bot.reply_to(message, "✅ Node deps installed.")
            except FileNotFoundError:
                bot.reply_to(message, "❌ `npm` not found.")
                return
            except subprocess.TimeoutExpired:
                bot.reply_to(message, "❌ npm install timed out after 5 minutes.")
                return
            except subprocess.CalledProcessError as e:
                err = e.stderr or e.stdout or 'Unknown npm error'
                if len(err) > 3500: err = err[-3500:]
                bot.reply_to(message, f"❌ npm install failed:\n```\n{err}\n```", parse_mode='Markdown')
                return

        save_user_file(user_id, main_script_name, file_type)
        main_script_path = os.path.join(user_folder, main_script_name)
        bot.reply_to(message, f"✅ Files extracted. Starting `{main_script_name}`...", parse_mode='Markdown')

        if file_type == 'py':
            threading.Thread(target=run_script, args=(main_script_path, user_id, user_folder, main_script_name, message)).start()
        else:
            threading.Thread(target=run_js_script, args=(main_script_path, user_id, user_folder, main_script_name, message)).start()

    except zipfile.BadZipFile as e:
        bot.reply_to(message, f"❌ Invalid ZIP: {e}")
    except Exception as e:
        logger.error("Error processing ZIP", exc_info=True)
        bot.reply_to(message, f"❌ Error processing zip: {e}")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            try: shutil.rmtree(temp_dir)
            except Exception: pass

def handle_js_file(file_path, script_owner_id, user_folder, file_name, message):
    try:
        save_user_file(script_owner_id, file_name, 'js')
        threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, message)).start()
    except Exception as e:
        bot.reply_to(message, f"❌ Error processing JS file: {e}")

def handle_py_file(file_path, script_owner_id, user_folder, file_name, message):
    try:
        save_user_file(script_owner_id, file_name, 'py')
        threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, message)).start()
    except Exception as e:
        bot.reply_to(message, f"❌ Error processing Python file: {e}")

# --- Send command / logs ---
def _logic_send_command(message):
    user_id = message.from_user.id
    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Bot locked by admin.")
        return
    bot.reply_to(message, "📤 Send Command Options:", reply_markup=create_send_command_menu())

def send_to_process_init(message):
    user_id = message.from_user.id
    user_running_scripts = []
    for script_key, script_info in bot_scripts.items():
        script_owner_id = script_info['script_owner_id']
        if (user_id == script_owner_id or user_id in admin_ids) and is_bot_running(script_owner_id, script_info['file_name']):
            user_running_scripts.append((script_key, script_info))
    if not user_running_scripts:
        bot.reply_to(message, "❌ No running scripts found.")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for script_key, script_info in user_running_scripts:
        btn_text = f"{script_info['file_name']} (User: {script_info['script_owner_id']})"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f'sendcmd_select_{script_key}'))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data='send_command'))
    bot.reply_to(message, "📝 Select a running script:", reply_markup=markup)

def process_send_command(message, script_key):
    if script_key not in bot_scripts:
        bot.reply_to(message, "❌ Script no longer running.")
        return
    script_info = bot_scripts[script_key]
    command_text = message.text
    try:
        process = script_info['process']
        if process and process.poll() is None:
            process.stdin.write(command_text + '\n')
            process.stdin.flush()
            bot.reply_to(message, f"✅ Command sent:\n`{command_text}`", parse_mode='Markdown')
            time.sleep(1)
            if process.poll() is not None:
                bot.reply_to(message, f"⚠️ Script stopped after receiving command.")
        else:
            bot.reply_to(message, f"❌ Script not running.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error sending command: {e}")

def view_all_logs(message):
    user_id = message.from_user.id
    user_logs = []
    user_folder = get_user_folder(user_id)
    if os.path.exists(user_folder):
        for file in os.listdir(user_folder):
            if file.endswith('.log'):
                log_path = os.path.join(user_folder, file)
                user_logs.append((file, os.path.getsize(log_path), log_path))
    if not user_logs:
        bot.reply_to(message, "📜 No log files found.")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for log_file, size, _ in sorted(user_logs):
        markup.add(types.InlineKeyboardButton(f"{log_file} ({size/1024:.1f} KB)",
                                              callback_data=f'viewlog_{user_id}_{log_file}'))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data='send_command'))
    bot.reply_to(message, "📜 Available Log Files:", reply_markup=markup)

def send_log_file(message, log_path, log_filename):
    try:
        if os.path.getsize(log_path) > 50 * 1024 * 1024:
            bot.reply_to(message, f"❌ Log too large.")
            return
        with open(log_path, 'rb') as log_file:
            bot.send_document(message.chat.id, log_file, caption=f"📜 {log_filename}")
    except Exception as e:
        bot.reply_to(message, f"❌ Error sending log: {e}")

# --- Logic Functions ---
@require_verification
def _logic_send_welcome(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_name = message.from_user.first_name
    user_username = message.from_user.username

    if bot_locked and user_id not in admin_ids:
        bot.send_message(chat_id, "⚠️ Bot locked by admin.")
        return

    user_bio = "Could not fetch bio"
    photo_file_id = None
    try: user_bio = bot.get_chat(user_id).bio or "No bio"
    except Exception: pass
    try:
        user_profile_photos = bot.get_user_profile_photos(user_id, limit=1)
        if user_profile_photos.photos: photo_file_id = user_profile_photos.photos[0][-1].file_id
    except Exception: pass

    if user_id not in active_users:
        add_active_user(user_id)
        try:
            bot.send_message(OWNER_ID, f"🎉 New user!\n👤 {user_name}\n✳️ @{user_username or 'N/A'}\n🆔 `{user_id}`\n📝 Bio: {user_bio}", parse_mode='Markdown')
            if photo_file_id: bot.send_photo(OWNER_ID, photo_file_id, caption=f"Pic of new user {user_id}")
        except Exception as e: logger.error(f"Owner notify failed: {e}")

    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
    expiry_info = ""

    if user_id == OWNER_ID: user_status = "👑 Owner"
    elif user_id in admin_ids: user_status = "🛡️ Admin"
    elif user_id in user_subscriptions:
        expiry_date = user_subscriptions[user_id].get('expiry')
        if expiry_date and expiry_date > datetime.now():
            user_status = "⭐ Premium"
            days_left = (expiry_date - datetime.now()).days
            expiry_info = f"\n⏳ Premium expires in: {days_left} days"
        else:
            user_status = "🆓 Free User (Expired Premium)"
            remove_subscription_db(user_id)
    else: user_status = "🆓 Free User"

    welcome_msg_text = (f"<b>XHOST // CLOUD HOST</b>\n\n"
                        f"Welcome, <b>{user_name}</b>.\n"
                        f"<code>ID {user_id}</code> · {user_status}{expiry_info}\n"
                        f"Files: <b>{current_files} / {limit_str}</b>\n\n"
                        f"Run Python, JavaScript, and supported web apps directly from Telegram.\n\n"
                        f"Choose an action below.")
    main_reply_markup = create_reply_keyboard_main_menu(user_id)
    try:
        if photo_file_id: bot.send_photo(chat_id, photo_file_id)
        bot.send_message(chat_id, welcome_msg_text, reply_markup=main_reply_markup, parse_mode='HTML')
    except Exception as e:
        logger.error(f"Welcome send error: {e}")
        try: bot.send_message(chat_id, welcome_msg_text, reply_markup=main_reply_markup, parse_mode='HTML')
        except Exception as fe: logger.error(f"Fallback failed: {fe}")

@require_verification
def _logic_updates_channel(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('◈ Updates', url=UPDATE_CHANNEL))
    bot.reply_to(message, "Visit our Updates Channel:", reply_markup=markup)

@require_verification
def _logic_upload_file(message):
    user_id = message.from_user.id
    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Bot locked.")
        return
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    if user_id in admin_ids: tier = "Admin"
    elif user_id in user_subscriptions and user_subscriptions[user_id].get('expiry', datetime.min) > datetime.now(): tier = "Premium"
    else: tier = "Free"
    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.reply_to(message, f"⚠️ {tier} limit reached ({current_files}/{limit_str}).")
        return
    limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
    bot.reply_to(message, f"📤 Send your `.py`, `.js`, or `.zip` file.\n📊 {tier} limit: {current_files}/{limit_str}")

@require_verification
def _logic_check_files(message):
    user_id = message.from_user.id
    user_files_list = user_files.get(user_id, [])
    if not user_files_list:
        bot.reply_to(message, "📂 Your files:\n\n(No files uploaded yet)")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for file_name, file_type in sorted(user_files_list):
        is_running = is_bot_running(user_id, file_name)
        status_icon = "🟢 Running" if is_running else "🔴 Stopped"
        btn_text = f"{file_name} ({file_type}) - {status_icon}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f'file_{user_id}_{file_name}'))
    bot.reply_to(message, "📂 Your files:\nClick to manage.", reply_markup=markup, parse_mode='Markdown')

@require_verification
def _logic_bot_speed(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    start_time_ping = time.time()
    wait_msg = bot.reply_to(message, "🏃 Testing speed...")
    try:
        bot.send_chat_action(chat_id, 'typing')
        response_time = round((time.time() - start_time_ping) * 1000, 2)
        status = "🔓 Unlocked" if not bot_locked else "🔒 Locked"
        if user_id == OWNER_ID: user_level = "👑 Owner"
        elif user_id in admin_ids: user_level = "🛡️ Admin"
        elif user_id in user_subscriptions and user_subscriptions[user_id].get('expiry', datetime.min) > datetime.now(): user_level = "⭐ Premium"
        else: user_level = "🆓 Free User"
        speed_msg = (f"⚡ Bot Speed & Status:\n\n⏱️ API Response Time: {response_time} ms\n"
                     f"🚦 Bot Status: {status}\n👤 Your Level: {user_level}")
        bot.edit_message_text(speed_msg, chat_id, wait_msg.message_id)
    except Exception as e:
        logger.error(f"Speed test error: {e}")
        bot.edit_message_text("❌ Error during speed test.", chat_id, wait_msg.message_id)

@require_verification
def _logic_contact_owner(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('◎ Owner', url=f'https://t.me/{YOUR_USERNAME.replace("@", "")}'))
    bot.reply_to(message, "Click to contact Owner:", reply_markup=markup)

# --- Admin Logic ---
@require_verification
def _logic_subscriptions_panel(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    bot.reply_to(message, "💳 Subscription Management", reply_markup=create_subscription_menu())

@require_verification
def _logic_statistics(message):
    user_id = message.from_user.id
    total_users = len(active_users)
    total_files_records = sum(len(files) for files in user_files.values())
    running_bots_count = 0
    user_running_bots = 0
    for script_key_iter, script_info_iter in list(bot_scripts.items()):
        try:
            s_owner_id = int(script_key_iter.split('_', 1)[0])
        except Exception:
            continue
        if is_bot_running(s_owner_id, script_info_iter['file_name']):
            running_bots_count += 1
            if s_owner_id == user_id: user_running_bots += 1
    stats_msg_base = (f"📊 Bot Statistics:\n\n"
                      f"👥 Total Users: {total_users}\n"
                      f"📂 Total File Records: {total_files_records}\n"
                      f"🟢 Total Active Bots: {running_bots_count}\n")
    if user_id in admin_ids:
        stats_msg = stats_msg_base + (f"🔒 Bot Status: {'🔴 Locked' if bot_locked else '🟢 Unlocked'}\n"
                                       f"🤖 Your Running Bots: {user_running_bots}")
    else:
        stats_msg = stats_msg_base + f"🤖 Your Running Bots: {user_running_bots}"
    bot.reply_to(message, stats_msg)

@require_verification
def _logic_broadcast_init(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    msg = bot.reply_to(message, "📢 Send message to broadcast.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_broadcast_message)

@require_verification
def _logic_toggle_lock_bot(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    global bot_locked
    bot_locked = not bot_locked
    status = "locked" if bot_locked else "unlocked"
    bot.reply_to(message, f"🔒 Bot has been {status}.")

@require_verification
def _logic_admin_panel(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin permissions required.")
        return
    bot.reply_to(message, "👑 Admin Panel", reply_markup=create_admin_panel())

@require_verification
def _logic_run_all_scripts(message_or_call):
    if isinstance(message_or_call, telebot.types.Message):
        admin_user_id = message_or_call.from_user.id
        admin_chat_id = message_or_call.chat.id
        reply_func = lambda text, **kwargs: bot.reply_to(message_or_call, text, **kwargs)
        msg_obj = message_or_call
    elif isinstance(message_or_call, telebot.types.CallbackQuery):
        admin_user_id = message_or_call.from_user.id
        admin_chat_id = message_or_call.message.chat.id
        bot.answer_callback_query(message_or_call.id)
        reply_func = lambda text, **kwargs: bot.send_message(admin_chat_id, text, **kwargs)
        msg_obj = message_or_call.message
    else:
        return

    if admin_user_id not in admin_ids:
        reply_func("⚠️ Admin permissions required.")
        return

    reply_func("⏳ Starting all user scripts...")
    started_count = 0
    attempted_users = 0
    skipped_files = 0
    error_details = []
    snapshot = dict(user_files)
    for target_user_id, files_for_user in snapshot.items():
        if not files_for_user: continue
        attempted_users += 1
        user_folder = get_user_folder(target_user_id)
        for file_name, file_type in files_for_user:
            if not is_bot_running(target_user_id, file_name):
                file_path = os.path.join(user_folder, file_name)
                if os.path.exists(file_path):
                    try:
                        if file_type == 'py':
                            threading.Thread(target=run_script, args=(file_path, target_user_id, user_folder, file_name, msg_obj)).start()
                            started_count += 1
                        elif file_type == 'js':
                            threading.Thread(target=run_js_script, args=(file_path, target_user_id, user_folder, file_name, msg_obj)).start()
                            started_count += 1
                        else:
                            error_details.append(f"`{file_name}` (User {target_user_id}) - Unknown type")
                            skipped_files += 1
                        time.sleep(0.7)
                    except Exception as e:
                        error_details.append(f"`{file_name}` (User {target_user_id}) - Start error")
                        skipped_files += 1
                else:
                    error_details.append(f"`{file_name}` (User {target_user_id}) - File not found")
                    skipped_files += 1

    summary = (f"✅ All Users' Scripts - Complete:\n\n"
               f"▶️ Started: {started_count}\n"
               f"👥 Users processed: {attempted_users}\n")
    if skipped_files > 0:
        summary += f"⚠️ Skipped/Errors: {skipped_files}\n"
        if error_details:
            summary += "Details (first 5):\n" + "\n".join(f"  - {err}" for err in error_details[:5])
    reply_func(summary, parse_mode='Markdown')

# --- Command handlers ---
@bot.message_handler(commands=['start', 'help'])
def command_send_welcome(message):
    user_id = message.from_user.id
    if user_id in admin_ids:
        _logic_send_welcome(message)
        return
    is_member, _ = check_channel_membership(user_id)
    if is_member:
        save_verified_user(user_id)
        _logic_send_welcome(message)
    else:
        send_verification_prompt(message.chat.id, user_id)

@bot.message_handler(commands=['status'])
def command_show_status(message):
    _logic_statistics(message)

BUTTON_TEXT_TO_LOGIC = {
    # Current clean UI labels
    "◈ Updates": _logic_updates_channel,
    "＋ Upload": _logic_upload_file,
    "▣ My Files": _logic_check_files,
    "⚡ Ping": _logic_bot_speed,
    "◌ Statistics": _logic_statistics,
    "⌘ Command": _logic_send_command,
    "◎ Owner": _logic_contact_owner,
    "◇ Premium": _logic_subscriptions_panel,
    "◉ Broadcast": _logic_broadcast_init,
    "🔒 Lock Bot": _logic_toggle_lock_bot,
    "▶ Run All": _logic_run_all_scripts,
    "⚙ Admin Panel": _logic_admin_panel,
    # Backward-compatible labels
    "📢 Updates Channel": _logic_updates_channel,
    "📤 Upload File": _logic_upload_file,
    "📂 Check Files": _logic_check_files,
    "⚡ Bot Speed": _logic_bot_speed,
    "📤 Send Command": _logic_send_command,
    "📞 Contact Owner": _logic_contact_owner,
    "📊 Statistics": _logic_statistics,
    "💳 Subscriptions": _logic_subscriptions_panel,
    "📢 Broadcast": _logic_broadcast_init,
    "🟢 Running All Code": _logic_run_all_scripts,
    "👑 Admin Panel": _logic_admin_panel,
}


@bot.message_handler(func=lambda message: message.text in BUTTON_TEXT_TO_LOGIC)
def handle_button_text(message):
    user_id = message.from_user.id
    if user_id not in admin_ids:
        is_member, _ = check_channel_membership(user_id)
        if not is_member:
            send_verification_prompt(message.chat.id, user_id)
            return
    logic_func = BUTTON_TEXT_TO_LOGIC.get(message.text)
    if logic_func: logic_func(message)

@bot.message_handler(commands=['updateschannel'])
def command_updates_channel(message): _logic_updates_channel(message)
@bot.message_handler(commands=['uploadfile'])
def command_upload_file(message): _logic_upload_file(message)
@bot.message_handler(commands=['checkfiles'])
def command_check_files(message): _logic_check_files(message)
@bot.message_handler(commands=['botspeed'])
def command_bot_speed(message): _logic_bot_speed(message)
@bot.message_handler(commands=['sendcommand'])
def command_send_command(message): _logic_send_command(message)
@bot.message_handler(commands=['contactowner'])
def command_contact_owner(message): _logic_contact_owner(message)
@bot.message_handler(commands=['subscriptions'])
def command_subscriptions(message): _logic_subscriptions_panel(message)
@bot.message_handler(commands=['statistics'])
def command_statistics(message): _logic_statistics(message)
@bot.message_handler(commands=['broadcast'])
def command_broadcast(message): _logic_broadcast_init(message)
@bot.message_handler(commands=['lockbot'])
def command_lock_bot(message): _logic_toggle_lock_bot(message)
@bot.message_handler(commands=['adminpanel'])
def command_admin_panel(message): _logic_admin_panel(message)
@bot.message_handler(commands=['runningallcode'])
def command_run_all_code(message): _logic_run_all_scripts(message)

@bot.message_handler(commands=['ping'])
def ping(message):
    start_ping_time = time.time()
    msg = bot.reply_to(message, "Pong!")
    latency = round((time.time() - start_ping_time) * 1000, 2)
    bot.edit_message_text(f"Pong! Latency: {latency} ms", message.chat.id, msg.message_id)

# --- File handler ---
@bot.message_handler(content_types=['document'])
def handle_file_upload_doc(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if user_id not in admin_ids:
        is_member, _ = check_channel_membership(user_id)
        if not is_member:
            send_verification_prompt(chat_id, user_id)
            return

    doc = message.document
    logger.info(f"Doc from {user_id}: {doc.file_name} ({doc.mime_type}), Size: {doc.file_size}")

    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Bot locked, cannot accept files.")
        return

    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)

    if user_id in admin_ids: tier = "Admin"
    elif user_id in user_subscriptions and user_subscriptions[user_id].get('expiry', datetime.min) > datetime.now(): tier = "Premium"
    else: tier = "Free"

    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.reply_to(message, f"⚠️ {tier} limit reached ({current_files}/{limit_str}). Delete files first.")
        return

    file_name = doc.file_name
    if not file_name:
        bot.reply_to(message, "⚠️ No file name.")
        return
    file_ext = os.path.splitext(file_name)[1].lower()
    if file_ext not in ['.py', '.js', '.zip']:
        bot.reply_to(message, "⚠️ Unsupported type! Only `.py`, `.js`, `.zip` allowed.")
        return
    max_file_size = 20 * 1024 * 1024
    if doc.file_size > max_file_size:
        bot.reply_to(message, f"⚠️ File too large (Max: 20 MB).")
        return

    try:
        try:
            bot.forward_message(OWNER_ID, chat_id, message.message_id)
            bot.send_message(OWNER_ID, f"⬆️ File '{file_name}' from {message.from_user.first_name} (`{user_id}`)", parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Forward failed: {e}")

        download_wait_msg = bot.reply_to(message, f"⏳ Downloading `{file_name}`...")
        file_info_tg_doc = bot.get_file(doc.file_id)
        downloaded_file_content = bot.download_file(file_info_tg_doc.file_path)

        bot.edit_message_text(f"✅ Downloaded `{file_name}`. Processing...", chat_id, download_wait_msg.message_id)
        logger.info(f"Downloaded {file_name} for user {user_id}")
        user_folder = get_user_folder(user_id)

        if file_ext == '.zip':
            handle_zip_file(downloaded_file_content, file_name, message)
        else:
            file_path = os.path.join(user_folder, file_name)
            with open(file_path, 'wb') as f: f.write(downloaded_file_content)
            logger.info(f"Saved single file to {file_path}")
            if file_ext == '.js': handle_js_file(file_path, user_id, user_folder, file_name, message)
            elif file_ext == '.py': handle_py_file(file_path, user_id, user_folder, file_name, message)
    except telebot.apihelper.ApiTelegramException as e:
        logger.error(f"TG API Error: {e}", exc_info=True)
        if "file is too big" in str(e).lower():
            bot.reply_to(message, f"❌ File too large to download.")
        else:
            bot.reply_to(message, f"❌ Telegram API Error: {str(e)}")
    except Exception as e:
        logger.error(f"❌ General error handling file: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Unexpected error: {str(e)}")

# --- Callbacks ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    data = call.data
    logger.info(f"Callback: User={user_id}, Data='{data}'")

    if data.startswith('verify_'):
        process_verification(call)
        return

    if bot_locked and user_id not in admin_ids and data not in ['back_to_main', 'speed', 'stats']:
        bot.answer_callback_query(call.id, "⚠️ Bot locked by admin.", show_alert=True)
        return

    if user_id not in admin_ids:
        is_member, _ = check_channel_membership(user_id)
        if not is_member:
            send_verification_prompt(call.message.chat.id, user_id)
            bot.answer_callback_query(call.id, "❌ Please join the channel first.", show_alert=True)
            return

    try:
        if data == 'upload': upload_callback(call)
        elif data == 'check_files': check_files_callback(call)
        elif data.startswith('file_'): file_control_callback(call)
        elif data.startswith('start_'): start_bot_callback(call)
        elif data.startswith('stop_'): stop_bot_callback(call)
        elif data.startswith('restart_'): restart_bot_callback(call)
        elif data.startswith('delete_'): delete_bot_callback(call)
        elif data.startswith('logs_'): logs_bot_callback(call)
        elif data == 'speed': speed_callback(call)
        elif data == 'back_to_main': back_to_main_callback(call)
        elif data.startswith('confirm_broadcast_'): handle_confirm_broadcast(call)
        elif data == 'cancel_broadcast': handle_cancel_broadcast(call)
        elif data == 'send_command': send_command_callback(call)
        elif data == 'send_to_process': send_to_process_callback(call)
        elif data.startswith('sendcmd_select_'): sendcmd_select_callback(call)
        elif data == 'view_all_logs': view_all_logs_callback(call)
        elif data.startswith('viewlog_'): viewlog_callback(call)
        elif data == 'subscription': admin_required_callback(call, subscription_management_callback)
        elif data == 'stats': stats_callback(call)
        elif data == 'lock_bot': admin_required_callback(call, lock_bot_callback)
        elif data == 'unlock_bot': admin_required_callback(call, unlock_bot_callback)
        elif data == 'run_all_scripts': admin_required_callback(call, run_all_scripts_callback)
        elif data == 'broadcast': admin_required_callback(call, broadcast_init_callback)
        elif data == 'admin_panel': admin_required_callback(call, admin_panel_callback)
        elif data == 'add_admin': owner_required_callback(call, add_admin_init_callback)
        elif data == 'remove_admin': owner_required_callback(call, remove_admin_init_callback)
        elif data == 'list_admins': admin_required_callback(call, list_admins_callback)
        elif data == 'add_subscription': admin_required_callback(call, add_subscription_init_callback)
        elif data == 'remove_subscription': admin_required_callback(call, remove_subscription_init_callback)
        elif data == 'check_subscription': admin_required_callback(call, check_subscription_init_callback)
        else:
            bot.answer_callback_query(call.id, "Unknown action.")
    except Exception as e:
        logger.error(f"Error in callback '{data}': {e}", exc_info=True)
        try: bot.answer_callback_query(call.id, "Error processing request.", show_alert=True)
        except Exception: pass

def admin_required_callback(call, func_to_run):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "⚠️ Admin permissions required.", show_alert=True)
        return
    func_to_run(call)

def owner_required_callback(call, func_to_run):
    if call.from_user.id != OWNER_ID:
        bot.answer_callback_query(call.id, "⚠️ Owner permissions required.", show_alert=True)
        return
    func_to_run(call)

# --- Callback implementations ---
def send_command_callback(call):
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text("📤 Send Command Options:", call.message.chat.id, call.message.message_id, reply_markup=create_send_command_menu())
    except Exception as e: logger.error(f"Error: {e}")

def send_to_process_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "📝 Send the command you want to execute:")
    bot.register_next_step_handler(msg, lambda m: send_to_process_init(m))

def sendcmd_select_callback(call):
    try:
        script_key = call.data.replace('sendcmd_select_', '')
        bot.answer_callback_query(call.id, f"Selected script: {script_key}")
        msg = bot.send_message(call.message.chat.id, f"📝 Enter command to send to {script_key}:")
        bot.register_next_step_handler(msg, lambda m: process_send_command(m, script_key))
    except Exception as e:
        logger.error(f"Error in sendcmd_select: {e}")
        bot.answer_callback_query(call.id, "Error selecting script.")

def view_all_logs_callback(call):
    bot.answer_callback_query(call.id)
    view_all_logs(call.message)

def viewlog_callback(call):
    try:
        _, user_id_str, log_filename = call.data.split('_', 2)
        user_id = int(user_id_str)
        requesting_user_id = call.from_user.id
        if not (requesting_user_id == user_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ You can only view your own logs.", show_alert=True)
            return
        user_folder = get_user_folder(user_id)
        log_path = os.path.join(user_folder, log_filename)
        if not os.path.exists(log_path):
            bot.answer_callback_query(call.id, "❌ Log file not found.", show_alert=True)
            return
        bot.answer_callback_query(call.id, "📜 Sending log file...")
        send_log_file(call.message, log_path, log_filename)
    except Exception as e:
        logger.error(f"Error in viewlog: {e}")
        bot.answer_callback_query(call.id, "Error viewing log.")

def upload_callback(call):
    user_id = call.from_user.id
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    if user_id in admin_ids: tier = "Admin"
    elif user_id in user_subscriptions and user_subscriptions[user_id].get('expiry', datetime.min) > datetime.now(): tier = "Premium"
    else: tier = "Free"
    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.answer_callback_query(call.id, f"⚠️ {tier} limit reached ({current_files}/{limit_str}).", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    limit_str = str(file_limit) if file_limit != float('inf') else "∞"
    bot.send_message(call.message.chat.id, f"📤 Send your Python (`.py`), JS (`.js`), or ZIP (`.zip`) file.\n📊 {tier} limit: {current_files}/{limit_str}")

def check_files_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    user_files_list = user_files.get(user_id, [])
    if not user_files_list:
        bot.answer_callback_query(call.id, "⚠️ No files uploaded.", show_alert=True)
        try:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Back to Main", callback_data='back_to_main'))
            bot.edit_message_text("📂 Your files:\n\n(No files uploaded)", chat_id, call.message.message_id, reply_markup=markup)
        except Exception as e: logger.error(f"Error: {e}")
        return
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup(row_width=1)
    for file_name, file_type in sorted(user_files_list):
        is_running = is_bot_running(user_id, file_name)
        status_icon = "🟢 Running" if is_running else "🔴 Stopped"
        markup.add(types.InlineKeyboardButton(f"{file_name} ({file_type}) - {status_icon}", callback_data=f'file_{user_id}_{file_name}'))
    markup.add(types.InlineKeyboardButton("🔙 Back to Main", callback_data='back_to_main'))
    try:
        bot.edit_message_text("📂 Your files:\nClick to manage.", chat_id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    except Exception as e: logger.error(f"Error editing msg: {e}")

def file_control_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ You can only manage your own files.", show_alert=True)
            check_files_callback(call)
            return
        user_files_list = user_files.get(script_owner_id, [])
        if not any(f[0] == file_name for f in user_files_list):
            bot.answer_callback_query(call.id, "⚠️ File not found.", show_alert=True)
            check_files_callback(call)
            return
        bot.answer_callback_query(call.id)
        is_running = is_bot_running(script_owner_id, file_name)
        status_text = '🟢 Running' if is_running else '🔴 Stopped'
        file_type = next((f[1] for f in user_files_list if f[0] == file_name), '?')
        try:
            bot.edit_message_text(
                f"⚙️ Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: {status_text}",
                call.message.chat.id, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, is_running),
                parse_mode='Markdown'
            )
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" not in str(e): raise
    except (ValueError, IndexError) as ve:
        logger.error(f"Error parsing file control: {ve}")
        bot.answer_callback_query(call.id, "Error: Invalid action data.", show_alert=True)
    except Exception as e:
        logger.error(f"Error in file_control: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "An error occurred.", show_alert=True)

def start_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True); return
        user_files_list = user_files.get(script_owner_id, [])
        file_info = next((f for f in user_files_list if f[0] == file_name), None)
        if not file_info:
            bot.answer_callback_query(call.id, "⚠️ File not found.", show_alert=True); check_files_callback(call); return
        file_type = file_info[1]
        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)
        if not os.path.exists(file_path):
            bot.answer_callback_query(call.id, f"⚠️ File `{file_name}` missing!", show_alert=True)
            remove_user_file_db(script_owner_id, file_name); check_files_callback(call); return
        if is_bot_running(script_owner_id, file_name):
            bot.answer_callback_query(call.id, f"⚠️ Already running.", show_alert=True)
            return
        bot.answer_callback_query(call.id, f"⏳ Starting {file_name}...")
        if file_type == 'py':
            threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        time.sleep(1.5)
        is_now_running = is_bot_running(script_owner_id, file_name)
        status_text = '🟢 Running' if is_now_running else '🟡 Starting (or failed)'
        try:
            bot.edit_message_text(
                f"⚙️ Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: {status_text}",
                chat_id_for_reply, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, is_now_running), parse_mode='Markdown'
            )
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" not in str(e): raise
    except Exception as e:
        logger.error(f"Error in start_bot: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error starting script.", show_alert=True)

def stop_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True); return
        user_files_list = user_files.get(script_owner_id, [])
        file_info = next((f for f in user_files_list if f[0] == file_name), None)
        if not file_info:
            bot.answer_callback_query(call.id, "⚠️ File not found.", show_alert=True); check_files_callback(call); return
        file_type = file_info[1]
        script_key = f"{script_owner_id}_{file_name}"
        if not is_bot_running(script_owner_id, file_name):
            bot.answer_callback_query(call.id, f"⚠️ Already stopped.", show_alert=True)
            return
        bot.answer_callback_query(call.id, f"⏳ Stopping {file_name}...")
        process_info = bot_scripts.get(script_key)
        if process_info:
            kill_process_tree(process_info)
            unregister_web_app(script_key)
            if script_key in bot_scripts: del bot_scripts[script_key]
        try:
            bot.edit_message_text(
                f"⚙️ Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: 🔴 Stopped",
                chat_id_for_reply, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, False), parse_mode='Markdown'
            )
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" not in str(e): raise
    except Exception as e:
        logger.error(f"Error in stop_bot: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error stopping script.", show_alert=True)

def restart_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True); return
        user_files_list = user_files.get(script_owner_id, [])
        file_info = next((f for f in user_files_list if f[0] == file_name), None)
        if not file_info:
            bot.answer_callback_query(call.id, "⚠️ File not found.", show_alert=True); check_files_callback(call); return
        file_type = file_info[1]
        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)
        script_key = f"{script_owner_id}_{file_name}"
        if not os.path.exists(file_path):
            bot.answer_callback_query(call.id, f"⚠️ File missing!", show_alert=True)
            remove_user_file_db(script_owner_id, file_name)
            if script_key in bot_scripts: del bot_scripts[script_key]
            check_files_callback(call); return
        bot.answer_callback_query(call.id, f"⏳ Restarting {file_name}...")
        if is_bot_running(script_owner_id, file_name):
            process_info = bot_scripts.get(script_key)
            if process_info: kill_process_tree(process_info)
            unregister_web_app(script_key)
            if script_key in bot_scripts: del bot_scripts[script_key]
            time.sleep(1.5)
        if file_type == 'py':
            threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        time.sleep(1.5)
        is_now_running = is_bot_running(script_owner_id, file_name)
        status_text = '🟢 Running' if is_now_running else '🟡 Starting (or failed)'
        try:
            bot.edit_message_text(
                f"⚙️ Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: {status_text}",
                chat_id_for_reply, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, is_now_running), parse_mode='Markdown'
            )
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" not in str(e): raise
    except Exception as e:
        logger.error(f"Error in restart: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error restarting.", show_alert=True)

def delete_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True); return
        user_files_list = user_files.get(script_owner_id, [])
        if not any(f[0] == file_name for f in user_files_list):
            bot.answer_callback_query(call.id, "⚠️ File not found.", show_alert=True); check_files_callback(call); return
        bot.answer_callback_query(call.id, f"🗑️ Deleting {file_name}...")
        script_key = f"{script_owner_id}_{file_name}"
        if is_bot_running(script_owner_id, file_name):
            process_info = bot_scripts.get(script_key)
            if process_info: kill_process_tree(process_info)
            unregister_web_app(script_key)
            if script_key in bot_scripts: del bot_scripts[script_key]
            time.sleep(0.5)
        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)
        log_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        deleted_disk = []
        if os.path.exists(file_path):
            try: os.remove(file_path); deleted_disk.append(file_name)
            except OSError as e: logger.error(f"Delete file error: {e}")
        if os.path.exists(log_path):
            try: os.remove(log_path); deleted_disk.append(os.path.basename(log_path))
            except OSError as e: logger.error(f"Delete log error: {e}")
        remove_user_file_db(script_owner_id, file_name)
        deleted_str = ", ".join(f"`{f}`" for f in deleted_disk) if deleted_disk else "associated files"
        try:
            bot.edit_message_text(
                f"🗑️ `{file_name}` (User `{script_owner_id}`) and {deleted_str} deleted!",
                chat_id_for_reply, call.message.message_id, reply_markup=None, parse_mode='Markdown'
            )
        except Exception as e:
            bot.send_message(chat_id_for_reply, f"🗑️ `{file_name}` deleted.", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in delete: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error deleting.", show_alert=True)

def logs_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True); return
        user_files_list = user_files.get(script_owner_id, [])
        if not any(f[0] == file_name for f in user_files_list):
            bot.answer_callback_query(call.id, "⚠️ File not found.", show_alert=True); check_files_callback(call); return
        user_folder = get_user_folder(script_owner_id)
        log_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        if not os.path.exists(log_path):
            bot.answer_callback_query(call.id, f"⚠️ No logs for '{file_name}'.", show_alert=True); return
        bot.answer_callback_query(call.id)
        try:
            log_content = ""
            file_size = os.path.getsize(log_path)
            max_log_kb = 100
            max_tg_msg = 4096
            if file_size == 0: log_content = "(Log empty)"
            elif file_size > max_log_kb * 1024:
                with open(log_path, 'rb') as f:
                    f.seek(-max_log_kb * 1024, os.SEEK_END)
                    log_bytes = f.read()
                log_content = log_bytes.decode('utf-8', errors='ignore')
                log_content = f"(Last {max_log_kb} KB)\n...\n" + log_content
            else:
                with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    log_content = f.read()
            if len(log_content) > max_tg_msg:
                log_content = log_content[-max_tg_msg:]
                first_nl = log_content.find('\n')
                if first_nl != -1: log_content = "...\n" + log_content[first_nl+1:]
                else: log_content = "...\n" + log_content
            if not log_content.strip(): log_content = "(No visible content)"
            bot.send_message(chat_id_for_reply, f"📜 Logs for `{file_name}` (User `{script_owner_id}`):\n```\n{log_content}\n```", parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error reading log: {e}", exc_info=True)
            bot.send_message(chat_id_for_reply, f"❌ Error reading log for `{file_name}`.")
    except Exception as e:
        logger.error(f"Error in logs callback: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error fetching logs.", show_alert=True)

def speed_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    start_cb_ping_time = time.time()
    try:
        bot.edit_message_text("🏃 Testing speed...", chat_id, call.message.message_id)
        bot.send_chat_action(chat_id, 'typing')
        response_time = round((time.time() - start_cb_ping_time) * 1000, 2)
        status = "🔓 Unlocked" if not bot_locked else "🔒 Locked"
        if user_id == OWNER_ID: user_level = "👑 Owner"
        elif user_id in admin_ids: user_level = "🛡️ Admin"
        elif user_id in user_subscriptions and user_subscriptions[user_id].get('expiry', datetime.min) > datetime.now(): user_level = "⭐ Premium"
        else: user_level = "🆓 Free User"
        speed_msg = (f"⚡ Bot Speed & Status:\n\n⏱️ API Response Time: {response_time} ms\n"
                     f"🚦 Bot Status: {status}\n👤 Your Level: {user_level}")
        bot.answer_callback_query(call.id)
        bot.edit_message_text(speed_msg, chat_id, call.message.message_id, reply_markup=create_main_menu_inline(user_id))
    except Exception as e:
        logger.error(f"Error in speed test: {e}", exc_info=True)
        bot.answer_callback_query(call.id, "Error in speed test.", show_alert=True)
        try: bot.edit_message_text("〽️ Main Menu", chat_id, call.message.message_id, reply_markup=create_main_menu_inline(user_id))
        except Exception: pass

def back_to_main_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
    expiry_info = ""
    if user_id == OWNER_ID: user_status = "👑 Owner"
    elif user_id in admin_ids: user_status = "🛡️ Admin"
    elif user_id in user_subscriptions:
        expiry_date = user_subscriptions[user_id].get('expiry')
        if expiry_date and expiry_date > datetime.now():
            user_status = "⭐ Premium"
            days_left = (expiry_date - datetime.now()).days
            expiry_info = f"\n⏳ Premium expires in: {days_left} days"
        else:
            user_status = "🆓 Free User (Expired Premium)"
    else: user_status = "🆓 Free User"
    main_menu_text = (f"〽️ Welcome back, {call.from_user.first_name}!\n\n🆔 ID: `{user_id}`\n"
                      f"🔰 Status: {user_status}{expiry_info}\n📁 Files: {current_files} / {limit_str}\n\n"
                      f"👇 Use buttons or type commands.")
    try:
        bot.answer_callback_query(call.id)
        bot.edit_message_text(main_menu_text, chat_id, call.message.message_id,
                              reply_markup=create_main_menu_inline(user_id), parse_mode='Markdown')
    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" not in str(e):
            logger.error(f"API error on back_to_main: {e}")
    except Exception as e:
        logger.error(f"Error handling back_to_main: {e}", exc_info=True)

# --- Admin Callback Implementations ---
def subscription_management_callback(call):
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text("💳 Subscription Management\nSelect action:",
                              call.message.chat.id, call.message.message_id, reply_markup=create_subscription_menu())
    except Exception as e: logger.error(f"Error: {e}")

def stats_callback(call):
    bot.answer_callback_query(call.id)
    _logic_statistics(call.message)
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                      reply_markup=create_main_menu_inline(call.from_user.id))
    except Exception as e: logger.error(f"Error: {e}")

def lock_bot_callback(call):
    global bot_locked; bot_locked = True
    bot.answer_callback_query(call.id, "🔒 Bot locked.")
    try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=create_main_menu_inline(call.from_user.id))
    except Exception as e: logger.error(f"Error: {e}")

def unlock_bot_callback(call):
    global bot_locked; bot_locked = False
    bot.answer_callback_query(call.id, "🔓 Bot unlocked.")
    try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=create_main_menu_inline(call.from_user.id))
    except Exception as e: logger.error(f"Error: {e}")

def run_all_scripts_callback(call):
    _logic_run_all_scripts(call)

def broadcast_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "📢 Send message to broadcast.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_broadcast_message)

def process_broadcast_message(message):
    user_id = message.from_user.id
    if user_id not in admin_ids: bot.reply_to(message, "⚠️ Not authorized."); return
    if message.text and message.text.lower() == '/cancel': bot.reply_to(message, "Broadcast cancelled."); return
    broadcast_content = message.text
    if not broadcast_content and not (message.photo or message.video or message.document or message.sticker or message.voice or message.audio):
        bot.reply_to(message, "⚠️ Cannot broadcast empty message.")
        msg = bot.send_message(message.chat.id, "📢 Send broadcast message or /cancel.")
        bot.register_next_step_handler(msg, process_broadcast_message)
        return
    target_count = len(active_users)
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("✅ Confirm & Send", callback_data=f"confirm_broadcast_{message.message_id}"),
               types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast"))
    preview_text = broadcast_content[:1000].strip() if broadcast_content else "(Media message)"
    bot.reply_to(message, f"⚠️ Confirm Broadcast:\n\n```\n{preview_text}\n```\nTo **{target_count}** users.",
                 reply_markup=markup, parse_mode='Markdown')

def handle_confirm_broadcast(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    if user_id not in admin_ids:
        bot.answer_callback_query(call.id, "⚠️ Admin only.", show_alert=True); return
    try:
        original_message = call.message.reply_to_message
        if not original_message: raise ValueError("Could not retrieve original message.")
        broadcast_text = None
        broadcast_photo_id = None
        broadcast_video_id = None
        if original_message.text: broadcast_text = original_message.text
        elif original_message.photo: broadcast_photo_id = original_message.photo[-1].file_id
        elif original_message.video: broadcast_video_id = original_message.video.file_id
        else: raise ValueError("No text or supported media.")
        bot.answer_callback_query(call.id, "🚀 Starting broadcast...")
        bot.edit_message_text(f"📢 Broadcasting to {len(active_users)} users...",
                              chat_id, call.message.message_id, reply_markup=None)
        threading.Thread(target=execute_broadcast, args=(
            broadcast_text, broadcast_photo_id, broadcast_video_id,
            original_message.caption if (broadcast_photo_id or broadcast_video_id) else None,
            chat_id)).start()
    except ValueError as ve:
        bot.edit_message_text(f"❌ Error: {ve}", chat_id, call.message.message_id, reply_markup=None)
    except Exception as e:
        logger.error(f"Error in confirm broadcast: {e}", exc_info=True)
        bot.edit_message_text("❌ Unexpected error.", chat_id, call.message.message_id, reply_markup=None)

def handle_cancel_broadcast(call):
    bot.answer_callback_query(call.id, "Broadcast cancelled.")
    bot.delete_message(call.message.chat.id, call.message.message_id)
    if call.message.reply_to_message:
        try: bot.delete_message(call.message.chat.id, call.message.reply_to_message.message_id)
        except Exception: pass

def execute_broadcast(broadcast_text, photo_id, video_id, caption, admin_chat_id):
    sent_count = 0; failed_count = 0; blocked_count = 0
    start_exec_time = time.time()
    users_to_broadcast = list(active_users)
    total_users = len(users_to_broadcast)
    batch_size = 25
    delay_batches = 1.5
    for i, user_id_bc in enumerate(users_to_broadcast):
        try:
            if broadcast_text: bot.send_message(user_id_bc, broadcast_text, parse_mode='Markdown')
            elif photo_id: bot.send_photo(user_id_bc, photo_id, caption=caption, parse_mode='Markdown' if caption else None)
            elif video_id: bot.send_video(user_id_bc, video_id, caption=caption, parse_mode='Markdown' if caption else None)
            sent_count += 1
        except telebot.apihelper.ApiTelegramException as e:
            err_desc = str(e).lower()
            if any(s in err_desc for s in ["bot was blocked", "user is deactivated", "chat not found", "kicked from", "restricted"]):
                blocked_count += 1
            elif "flood control" in err_desc or "too many requests" in err_desc:
                retry_after = 5
                match = re.search(r"retry after (\d+)", err_desc)
                if match: retry_after = int(match.group(1)) + 1
                time.sleep(retry_after)
                try:
                    if broadcast_text: bot.send_message(user_id_bc, broadcast_text, parse_mode='Markdown')
                    elif photo_id: bot.send_photo(user_id_bc, photo_id, caption=caption, parse_mode='Markdown' if caption else None)
                    elif video_id: bot.send_video(user_id_bc, video_id, caption=caption, parse_mode='Markdown' if caption else None)
                    sent_count += 1
                except Exception: failed_count += 1
            else: failed_count += 1
        except Exception: failed_count += 1
        if (i + 1) % batch_size == 0 and i < total_users - 1:
            time.sleep(delay_batches)
        elif i % 5 == 0: time.sleep(0.2)
    duration = round(time.time() - start_exec_time, 2)
    result_msg = (f"📢 Broadcast Complete!\n\n✅ Sent: {sent_count}\n❌ Failed: {failed_count}\n"
                  f"🚫 Blocked/Inactive: {blocked_count}\n👥 Targets: {total_users}\n⏱️ Duration: {duration}s")
    try: bot.send_message(admin_chat_id, result_msg)
    except Exception as e: logger.error(f"Failed to send broadcast result: {e}")

def admin_panel_callback(call):
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text("👑 Admin Panel\nManage admins.",
                              call.message.chat.id, call.message.message_id, reply_markup=create_admin_panel())
    except Exception as e: logger.error(f"Error: {e}")

def add_admin_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "👑 Enter User ID to promote to Admin.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_add_admin_id)

def process_add_admin_id(message):
    owner_id_check = message.from_user.id
    if owner_id_check != OWNER_ID: bot.reply_to(message, "⚠️ Owner only."); return
    if message.text.lower() == '/cancel': bot.reply_to(message, "Cancelled."); return
    try:
        new_admin_id = int(message.text.strip())
        if new_admin_id <= 0: raise ValueError("Invalid ID")
        if new_admin_id == OWNER_ID: bot.reply_to(message, "⚠️ Already owner."); return
        if new_admin_id in admin_ids: bot.reply_to(message, f"⚠️ Already admin."); return
        add_admin_db(new_admin_id)
        bot.reply_to(message, f"✅ `{new_admin_id}` promoted to Admin.", parse_mode='Markdown')
        try: bot.send_message(new_admin_id, "🎉 You are now an Admin.")
        except Exception: pass
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid ID.")
        msg = bot.send_message(message.chat.id, "👑 Enter User ID or /cancel.")
        bot.register_next_step_handler(msg, process_add_admin_id)
    except Exception as e:
        logger.error(f"Error adding admin: {e}")
        bot.reply_to(message, "Error.")

def remove_admin_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "👑 Enter User ID to remove.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_remove_admin_id)

def process_remove_admin_id(message):
    owner_id_check = message.from_user.id
    if owner_id_check != OWNER_ID: bot.reply_to(message, "⚠️ Owner only."); return
    if message.text.lower() == '/cancel': bot.reply_to(message, "Cancelled."); return
    try:
        admin_id_remove = int(message.text.strip())
        if admin_id_remove <= 0: raise ValueError("Invalid ID")
        if admin_id_remove == OWNER_ID: bot.reply_to(message, "⚠️ Cannot remove owner."); return
        if admin_id_remove not in admin_ids: bot.reply_to(message, f"⚠️ Not an admin."); return
        if remove_admin_db(admin_id_remove):
            bot.reply_to(message, f"✅ Admin `{admin_id_remove}` removed.", parse_mode='Markdown')
            try: bot.send_message(admin_id_remove, "ℹ️ You are no longer an Admin.")
            except Exception: pass
        else:
            bot.reply_to(message, f"❌ Failed to remove.")
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid ID.")
        msg = bot.send_message(message.chat.id, "👑 Enter Admin ID or /cancel.")
        bot.register_next_step_handler(msg, process_remove_admin_id)
    except Exception as e:
        logger.error(f"Error removing admin: {e}")
        bot.reply_to(message, "Error.")

def list_admins_callback(call):
    bot.answer_callback_query(call.id)
    try:
        admin_list_str = "\n".join(f"- `{aid}` {'(Owner)' if aid == OWNER_ID else ''}" for aid in sorted(list(admin_ids)))
        if not admin_list_str: admin_list_str = "(No admins)"
        bot.edit_message_text(f"👑 Current Admins:\n\n{admin_list_str}", call.message.chat.id,
                              call.message.message_id, reply_markup=create_admin_panel(), parse_mode='Markdown')
    except Exception as e: logger.error(f"Error: {e}")

def add_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "💳 Enter User ID & days (e.g., `12345678 30`).\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_add_subscription_details)

def process_add_subscription_details(message):
    admin_id_check = message.from_user.id
    if admin_id_check not in admin_ids: bot.reply_to(message, "⚠️ Not authorized."); return
    if message.text.lower() == '/cancel': bot.reply_to(message, "Cancelled."); return
    try:
        parts = message.text.split()
        if len(parts) != 2: raise ValueError("Incorrect format")
        sub_user_id = int(parts[0].strip())
        days = int(parts[1].strip())
        if sub_user_id <= 0 or days <= 0: raise ValueError("Must be positive")
        current_expiry = user_subscriptions.get(sub_user_id, {}).get('expiry')
        start_date_new_sub = datetime.now()
        if current_expiry and current_expiry > start_date_new_sub:
            start_date_new_sub = current_expiry
        new_expiry = start_date_new_sub + timedelta(days=days)
        save_subscription(sub_user_id, new_expiry)
        bot.reply_to(message, f"✅ Premium for `{sub_user_id}` added for {days} days.\nNew expiry: {new_expiry:%Y-%m-%d}", parse_mode='Markdown')
        try: bot.send_message(sub_user_id, f"🎉 Premium activated for {days} days! Expires: {new_expiry:%Y-%m-%d}.")
        except Exception: pass
    except ValueError as e:
        bot.reply_to(message, f"⚠️ Invalid: {e}")
        msg = bot.send_message(message.chat.id, "💳 Enter User ID & days or /cancel.")
        bot.register_next_step_handler(msg, process_add_subscription_details)
    except Exception as e:
        logger.error(f"Error: {e}")
        bot.reply_to(message, "Error.")

def remove_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "💳 Enter User ID to remove premium.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_remove_subscription_id)

def process_remove_subscription_id(message):
    admin_id_check = message.from_user.id
    if admin_id_check not in admin_ids: bot.reply_to(message, "⚠️ Not authorized."); return
    if message.text.lower() == '/cancel': bot.reply_to(message, "Cancelled."); return
    try:
        sub_user_id_remove = int(message.text.strip())
        if sub_user_id_remove <= 0: raise ValueError("Invalid ID")
        if sub_user_id_remove not in user_subscriptions:
            bot.reply_to(message, f"⚠️ No active premium for `{sub_user_id_remove}`."); return
        remove_subscription_db(sub_user_id_remove)
        bot.reply_to(message, f"✅ Premium for `{sub_user_id_remove}` removed.", parse_mode='Markdown')
        try: bot.send_message(sub_user_id_remove, "ℹ️ Your premium was removed.")
        except Exception: pass
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid ID.")
        msg = bot.send_message(message.chat.id, "💳 Enter User ID or /cancel.")
        bot.register_next_step_handler(msg, process_remove_subscription_id)
    except Exception as e:
        logger.error(f"Error: {e}")
        bot.reply_to(message, "Error.")

def check_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "💳 Enter User ID to check.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_check_subscription_id)

def process_check_subscription_id(message):
    admin_id_check = message.from_user.id
    if admin_id_check not in admin_ids: bot.reply_to(message, "⚠️ Not authorized."); return
    if message.text.lower() == '/cancel': bot.reply_to(message, "Cancelled."); return
    try:
        sub_user_id_check = int(message.text.strip())
        if sub_user_id_check <= 0: raise ValueError("Invalid ID")
        if sub_user_id_check in user_subscriptions:
            expiry_dt = user_subscriptions[sub_user_id_check].get('expiry')
            if expiry_dt:
                if expiry_dt > datetime.now():
                    days_left = (expiry_dt - datetime.now()).days
                    bot.reply_to(message, f"✅ `{sub_user_id_check}` has active Premium.\nExpires: {expiry_dt:%Y-%m-%d} ({days_left} days left).", parse_mode='Markdown')
                else:
                    bot.reply_to(message, f"⚠️ `{sub_user_id_check}` expired ({expiry_dt:%Y-%m-%d}).", parse_mode='Markdown')
                    remove_subscription_db(sub_user_id_check)
            else: bot.reply_to(message, f"⚠️ No expiry data.")
        else: bot.reply_to(message, f"ℹ️ `{sub_user_id_check}` no premium.", parse_mode='Markdown')
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid ID.")
        msg = bot.send_message(message.chat.id, "💳 Enter User ID or /cancel.")
        bot.register_next_step_handler(msg, process_check_subscription_id)
    except Exception as e:
        logger.error(f"Error: {e}")
        bot.reply_to(message, "Error.")

# --- Cleanup ---
def cleanup():
    logger.warning("Shutdown. Cleaning up processes...")
    script_keys_to_stop = list(bot_scripts.keys())
    if not script_keys_to_stop:
        return
    for key in script_keys_to_stop:
        if key in bot_scripts:
            kill_process_tree(bot_scripts[key])
            unregister_web_app(key)
atexit.register(cleanup)

# --- Main ---
if __name__ == '__main__':
    logger.info("="*40 + "\n🤖 Bot Starting Up...\n" + f"🐍 Python: {sys.version.split()[0]}\n" +
                f"🔧 Base Dir: {BASE_DIR}\n📁 Upload Dir: {UPLOAD_BOTS_DIR}\n" +
                f"📊 Data Dir: {IROTECH_DIR}\n🔑 Owner ID: {OWNER_ID}\n🛡️ Admins: {admin_ids}\n" + "="*40)
    keep_alive()
    logger.info("🚀 Starting polling...")
    while True:
        try:
            bot.infinity_polling(logger_level=logging.INFO, timeout=60, long_polling_timeout=30)
        except requests.exceptions.ReadTimeout:
            logger.warning("Polling ReadTimeout. Restarting in 5s...")
            time.sleep(5)
        except requests.exceptions.ConnectionError as ce:
            logger.error(f"Polling ConnectionError: {ce}. Retrying in 15s...")
            time.sleep(15)
        except Exception as e:
            logger.critical(f"💥 Unrecoverable polling error: {e}", exc_info=True)
            time.sleep(30)