# -*- coding: utf-8 -*-
"""
XHOST Bot — Auto-Restart Edition
Fixed and Verified — All Features Preserved
"""
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
import threading
import re
import sys
import atexit
import requests
import hashlib

# --- Flask Keep Alive (with PORT fallback) ---
from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "XHOST Bot is Running 24/7"

@app.route('/health')
def health():
    return {"status": "ok", "time": datetime.now().isoformat()}

def run_flask():
    # FIX #7: Port fallback — 8080 if PORT not set (Render/Railway sets PORT automatically)
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

def keep_alive():
    t = Thread(target=run_flask, daemon=True)
    t.start()
    print(f"✅ Keep-Alive running on port {os.environ.get('PORT', 8080)}")

# --- Configuration ---
TOKEN = '7561447303:AAFCTEYQiIzDTE_LymMf7fxeOp7r6K8Jsv4'
OWNER_ID = 7305141058
ADMIN_ID = 7305141058
YOUR_USERNAME = '@X1n0q'
UPDATE_CHANNEL = 'https://t.me/Hexmaincuh'
CHANNEL_USERNAME = '@Hexmaincuh'

# Folder setup
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_BOTS_DIR = os.path.join(BASE_DIR, 'upload_bots')
IROTECH_DIR = os.path.join(BASE_DIR, 'inf')
DATABASE_PATH = os.path.join(IROTECH_DIR, 'bot_data.db')
AUTORESTART_FILE = os.path.join(IROTECH_DIR, "autorestart.json")

# File upload limits
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

# --- Malware Detection Config ---
MALWARE_SIGNATURES = [b'MZ', b'\x7fELF', b'\xfe\xed\xfa', b'\xce\xfa\xed\xfe', b'PK', b'Rar!']
ENCRYPTED_FILE_INDICATORS = [b'openssl', b'encrypted', b'cipher', b'AES', b'DES', b'RSA', b'GPG', b'PGP']
SUSPICIOUS_KEYWORDS = [b'ransomware', b'trojan', b'virus', b'malware', b'backdoor', b'exploit',
                       b'payload', b'botnet', b'keylogger', b'rootkit']

# --- Logging ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================
# AUTO-RESTART SYSTEM
# ============================================================
AUTORESTART_LOCK = threading.Lock()

def save_autorestart_state():
    """Save currently running scripts to disk"""
    with AUTORESTART_LOCK:
        try:
            running_scripts = []
            for script_key, info in bot_scripts.items():
                if info.get('process') and info['process'].poll() is None:
                    running_scripts.append({
                        'script_key': script_key,
                        'script_owner_id': info['script_owner_id'],
                        'file_name': info['file_name'],
                        'file_type': info.get('type', 'py'),
                        'user_folder': info['user_folder'],
                        'chat_id': info['chat_id'],
                        'started_at': info['start_time'].isoformat() if info.get('start_time') else None,
                    })
            with open(AUTORESTART_FILE, 'w', encoding='utf-8') as f:
                json.dump(running_scripts, f, indent=2)
            if running_scripts:
                logger.info(f"💾 Saved {len(running_scripts)} running script(s) for auto-restart")
        except Exception as e:
            logger.error(f"Failed to save autorestart state: {e}")

def load_autorestart_state():
    """Load saved scripts from disk"""
    if not os.path.exists(AUTORESTART_FILE):
        return []
    try:
        with open(AUTORESTART_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load autorestart state: {e}")
        return []

def clear_autorestart_state():
    """Clear the saved state"""
    try:
        if os.path.exists(AUTORESTART_FILE):
            os.remove(AUTORESTART_FILE)
    except Exception as e:
        logger.error(f"Failed to clear autorestart state: {e}")

def auto_restart_scripts():
    """Restart all saved scripts on bot startup"""
    scripts = load_autorestart_state()
    if not scripts:
        logger.info("📂 No scripts to auto-restart")
        return

    logger.info(f"🔄 Auto-restarting {len(scripts)} script(s)...")
    restarted = 0
    failed = 0

    class FakeMessage:
        def __init__(self, chat_id, user_id):
            self.chat = type('obj', (object,), {'id': chat_id})()
            self.message_id = 0
            self.from_user = type('obj', (object,), {'id': user_id})()

    for script in scripts:
        try:
            script_owner_id = script['script_owner_id']
            file_name = script['file_name']
            file_type = script.get('file_type', 'py')
            user_folder = script['user_folder']
            chat_id = script['chat_id']

            file_path = os.path.join(user_folder, file_name)
            if not os.path.exists(file_path):
                logger.warning(f"⚠️ Script file missing: {file_path}")
                failed += 1
                continue

            script_key = f"{script_owner_id}_{file_name}"
            if script_key in bot_scripts:
                logger.info(f"⏭️ Script already running: {script_key}")
                continue

            fake_msg = FakeMessage(chat_id, script_owner_id)

            if file_type == 'py':
                threading.Thread(
                    target=run_script,
                    args=(file_path, script_owner_id, user_folder, file_name, fake_msg),
                    daemon=True
                ).start()
                restarted += 1
            elif file_type == 'js':
                threading.Thread(
                    target=run_js_script,
                    args=(file_path, script_owner_id, user_folder, file_name, fake_msg),
                    daemon=True
                ).start()
                restarted += 1

            time.sleep(0.7)

            try:
                bot.send_message(
                    chat_id,
                    f"🔄 <b>Script Auto-Restarted</b>\n\n"
                    f"📄 File: <code>{file_name}</code>\n"
                    f"✅ Your script is back online after bot maintenance.",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.warning(f"Could not notify {chat_id}: {e}")

        except Exception as e:
            logger.error(f"Failed to restart {script.get('script_key')}: {e}")
            failed += 1

    logger.info(f"🔄 Auto-restart complete: {restarted} restarted, {failed} failed")
    if restarted > 0:
        clear_autorestart_state()

def periodic_save_state():
    """Periodically save state every 30 seconds"""
    while True:
        time.sleep(30)
        try:
            save_autorestart_state()
        except Exception as e:
            logger.error(f"Periodic state save failed: {e}")

def start_state_saver():
    """Start the periodic state saver thread"""
    t = threading.Thread(target=periodic_save_state, daemon=True, name="state-saver")
    t.start()
    logger.info("💾 State saver started (saves every 30s)")

# ============================================================
# KEYBOARD LAYOUTS
# ============================================================
COMMAND_BUTTONS_LAYOUT_USER_SPEC = [
    ["📢 Updates Channel"],
    ["📤 Upload File", "📂 Check Files"],
    ["⚡ Bot Speed", "📊 Statistics"],
    ["📤 Send Command", "📞 Contact Owner"]
]
ADMIN_COMMAND_BUTTONS_LAYOUT_USER_SPEC = [
    ["📢 Updates Channel"],
    ["📤 Upload File", "📂 Check Files"],
    ["⚡ Bot Speed", "📊 Statistics"],
    ["💳 Subscriptions", "📢 Broadcast"],
    ["🔒 Lock Bot", "🟢 Running All Code"],
    ["📤 Send Command", "👑 Admin Panel"],
    ["📞 Contact Owner"]
]

# ============================================================
# DATABASE
# ============================================================
def init_db():
    logger.info(f"Initializing database at: {DATABASE_PATH}")
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('CREATE TABLE IF NOT EXISTS subscriptions (user_id INTEGER PRIMARY KEY, expiry TEXT)')
        c.execute('''CREATE TABLE IF NOT EXISTS user_files
                     (user_id INTEGER, file_name TEXT, file_type TEXT,
                      PRIMARY KEY (user_id, file_name))''')
        c.execute('CREATE TABLE IF NOT EXISTS active_users (user_id INTEGER PRIMARY KEY)')
        c.execute('CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)')
        c.execute('CREATE TABLE IF NOT EXISTS verified_users (user_id INTEGER PRIMARY KEY, verified_at TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS verification_messages (user_id INTEGER PRIMARY KEY, message_id INTEGER)')
        c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (OWNER_ID,))
        if ADMIN_ID != OWNER_ID:
            c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (ADMIN_ID,))
        conn.commit()
        conn.close()
        logger.info("Database initialized.")
    except Exception as e:
        logger.error(f"❌ DB init error: {e}", exc_info=True)

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
                pass
        c.execute('SELECT user_id, file_name, file_type FROM user_files')
        for user_id, file_name, file_type in c.fetchall():
            user_files.setdefault(user_id, []).append((file_name, file_type))
        c.execute('SELECT user_id FROM active_users')
        active_users.update(row[0] for row in c.fetchall())
        c.execute('SELECT user_id FROM admins')
        admin_ids.update(row[0] for row in c.fetchall())
        c.execute('SELECT user_id FROM verified_users')
        verified_users.update(row[0] for row in c.fetchall())
        conn.close()
        logger.info(f"Loaded: {len(active_users)} users, {len(admin_ids)} admins, {len(verified_users)} verified")
    except Exception as e:
        logger.error(f"❌ Load error: {e}", exc_info=True)

init_db()
load_data()

# ============================================================
# VERIFICATION
# ============================================================
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
        logger.error(f"Save verify error: {e}")
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
        logger.error(f"Remove verify error: {e}")
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
        logger.error(f"Membership check error: {e}")
        return False, "error"

def require_verification(func):
    def wrapper(message_or_call):
        user_id = None
        chat_id = None
        if hasattr(message_or_call, 'from_user'):
            user_id = message_or_call.from_user.id
            chat_id = message_or_call.chat.id if hasattr(message_or_call, 'chat') else message_or_call.message.chat.id
        elif hasattr(message_or_call, 'message') and hasattr(message_or_call.message, 'chat'):
            user_id = message_or_call.from_user.id
            chat_id = message_or_call.message.chat.id
        else:
            return
        if user_id in admin_ids:
            return func(message_or_call)
        if is_user_verified(user_id):
            is_member, status = check_channel_membership(user_id)
            if is_member:
                return func(message_or_call)
            remove_verified_user(user_id)
            send_verification_prompt(chat_id, user_id)
            return
        send_verification_prompt(chat_id, user_id)
    return wrapper

def send_verification_prompt(chat_id, user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📢 Join Channel", url=UPDATE_CHANNEL),
        types.InlineKeyboardButton("✅ Verify Now", callback_data=f"verify_{user_id}")
    )
    try:
        bot.send_message(
            chat_id,
            "🔒 **Channel Verification Required**\n\n"
            "Join our channel to use this bot.\n\n"
            "👇 Join then press **Verify Now**.",
            reply_markup=markup, parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Verify prompt send error: {e}")

def process_verification(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    try:
        expected = int(call.data.split('_')[1])
    except (IndexError, ValueError):
        bot.answer_callback_query(call.id, "⚠️ Invalid verification.")
        return
    if user_id != expected:
        bot.answer_callback_query(call.id, "⚠️ You can only verify yourself.", show_alert=True)
        return
    is_member, status = check_channel_membership(user_id)
    if is_member:
        save_verified_user(user_id)
        bot.answer_callback_query(call.id, "✅ Verified!")
        try:
            bot.send_message(chat_id, "✅ **Verified!** Loading menu...", parse_mode='Markdown')
        except: pass
        _logic_send_welcome(call.message)
    else:
        bot.answer_callback_query(call.id, "❌ Not in channel.", show_alert=True)

# ============================================================
# MALWARE DETECTION
# ============================================================
def get_file_type(file_content):
    signatures = {
        b'\x7fELF': 'application/x-executable',
        b'MZ': 'application/x-dosexec',
        b'\xfe\xed\xfa': 'application/x-mach-binary',
        b'PK': 'application/zip',
        b'Rar!': 'application/x-rar',
    }
    for sig, mime in signatures.items():
        if file_content.startswith(sig):
            return mime
    return 'application/octet-stream'

def is_suspicious_file(file_content, file_name):
    file_lower = file_name.lower()
    suspicious_extensions = ['.exe', '.dll', '.bat', '.cmd', '.scr', '.com', '.pif',
                             '.msi', '.msp', '.hta', '.cpl', '.msc', '.jar', '.bin',
                             '.deb', '.rpm', '.apk', '.app', '.dmg', '.iso', '.img']
    if any(file_lower.endswith(ext) for ext in suspicious_extensions):
        return True, f"Suspicious extension: {file_name}"
    for sig in MALWARE_SIGNATURES:
        if file_content.startswith(sig):
            return True, f"Malware signature: {sig}"
    sample = file_content[:4096]
    for indicator in ENCRYPTED_FILE_INDICATORS:
        if indicator in sample:
            return True, f"Encrypted indicator: {indicator.decode('utf-8', errors='ignore')}"
    sample_text = sample.decode('utf-8', errors='ignore').lower()
    for kw in SUSPICIOUS_KEYWORDS:
        if kw.decode('utf-8').lower() in sample_text:
            return True, f"Suspicious keyword: {kw.decode('utf-8')}"
    return False, "Safe"

def scan_file_for_malware(file_content, file_name, user_id):
    if user_id == OWNER_ID or user_id in admin_ids:
        user_type = "Owner" if user_id == OWNER_ID else "Admin"
        return True, f"{user_type} bypassed scan"
    is_suspicious, reason = is_suspicious_file(file_content, file_name)
    if is_suspicious:
        return False, f"Security violation: {reason}"
    return True, "Passed"

# ============================================================
# HELPERS
# ============================================================
def get_user_folder(user_id):
    folder = os.path.join(UPLOAD_BOTS_DIR, str(user_id))
    os.makedirs(folder, exist_ok=True)
    return folder

def get_user_file_limit(user_id):
    if user_id == OWNER_ID: return OWNER_LIMIT
    if user_id in admin_ids: return ADMIN_LIMIT
    if user_id in user_subscriptions:
        expiry = user_subscriptions[user_id].get('expiry')
        if expiry and expiry > datetime.now():
            return SUBSCRIBED_USER_LIMIT
    return FREE_USER_LIMIT

def get_user_file_count(user_id):
    return len(user_files.get(user_id, []))

def is_bot_running(script_owner_id, file_name):
    script_key = f"{script_owner_id}_{file_name}"
    info = bot_scripts.get(script_key)
    if info and info.get('process'):
        try:
            proc = psutil.Process(info['process'].pid)
            running = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            if not running:
                if 'log_file' in info and hasattr(info['log_file'], 'close') and not info['log_file'].closed:
                    try: info['log_file'].close()
                    except: pass
                bot_scripts.pop(script_key, None)
            return running
        except psutil.NoSuchProcess:
            if 'log_file' in info and hasattr(info['log_file'], 'close') and not info['log_file'].closed:
                try: info['log_file'].close()
                except: pass
            bot_scripts.pop(script_key, None)
            return False
        except Exception:
            return False
    return False

def kill_process_tree(info):
    pid = None
    script_key = info.get('script_key', 'N/A')
    try:
        if 'log_file' in info and hasattr(info['log_file'], 'close') and not info['log_file'].closed:
            try: info['log_file'].close()
            except: pass
        process = info.get('process')
        if process and hasattr(process, 'pid'):
            pid = process.pid
            if pid:
                try:
                    parent = psutil.Process(pid)
                    children = parent.children(recursive=True)
                    for child in children:
                        try: child.terminate()
                        except:
                            try: child.kill()
                            except: pass
                    gone, alive = psutil.wait_procs(children, timeout=1)
                    for p in alive:
                        try: p.kill()
                        except: pass
                    try:
                        parent.terminate()
                        try: parent.wait(timeout=1)
                        except psutil.TimeoutExpired: parent.kill()
                    except psutil.NoSuchProcess: pass
                except psutil.NoSuchProcess: pass
        threading.Thread(target=save_autorestart_state, daemon=True).start()
    except Exception as e:
        logger.error(f"Kill tree error for {script_key}: {e}", exc_info=True)

# ============================================================
# MODULE MAP
# ============================================================
TELEGRAM_MODULES = {
    'telebot': 'pyTelegramBotAPI', 'telegram': 'python-telegram-bot',
    'python_telegram_bot': 'python-telegram-bot', 'aiogram': 'aiogram',
    'pyrogram': 'pyrogram', 'telethon': 'telethon', 'telethon.sync': 'telethon',
    'telepot': 'telepot', 'pytg': 'pytg', 'tgcrypto': 'tgcrypto',
    'requests': 'requests', 'pillow': 'Pillow', 'cv2': 'opencv-python',
    'yaml': 'PyYAML', 'dotenv': 'python-dotenv', 'dateutil': 'python-dateutil',
    'pandas': 'pandas', 'numpy': 'numpy', 'flask': 'Flask', 'django': 'Django',
    'sqlalchemy': 'SQLAlchemy', 'bs4': 'beautifulsoup4', 'psutil': 'psutil',
}

def attempt_install_pip(module_name, message):
    package_name = TELEGRAM_MODULES.get(module_name.lower(), module_name)
    if package_name is None:
        return False
    try:
        bot.reply_to(message, f"🐍 Installing `{package_name}`...", parse_mode='Markdown')
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', package_name],
            capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore',
            timeout=180
        )
        if result.returncode == 0:
            bot.reply_to(message, f"✅ Installed `{package_name}`", parse_mode='Markdown')
            return True
        logger.error(f"pip install failed for {package_name}: {result.stderr[:200]}")
        return False
    except subprocess.TimeoutExpired:
        logger.error(f"pip install timeout for {package_name}")
        return False
    except Exception as e:
        logger.error(f"pip install error: {e}")
        return False

def attempt_install_npm(module_name, user_folder, message):
    try:
        bot.reply_to(message, f"🟠 Installing Node `{module_name}`...", parse_mode='Markdown')
        result = subprocess.run(
            ['npm', 'install', module_name],
            capture_output=True, text=True, check=False, cwd=user_folder,
            encoding='utf-8', errors='ignore', timeout=180
        )
        if result.returncode == 0:
            bot.reply_to(message, f"✅ Installed `{module_name}`", parse_mode='Markdown')
            return True
        return False
    except FileNotFoundError:
        bot.reply_to(message, "❌ 'npm' not installed.")
        return False
    except Exception:
        return False

# ============================================================
# SCRIPT RUNNERS
# ============================================================
def run_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1):
    max_attempts = 2
    if attempt > max_attempts:
        try:
            bot.reply_to(message_obj_for_reply, f"❌ Failed to run '{file_name}'")
        except: pass
        return

    script_key = f"{script_owner_id}_{file_name}"
    logger.info(f"Running Python: {script_path}")

    try:
        # FIX #1: remove_user_file_db is now defined later — use direct DB call instead
        if not os.path.exists(script_path):
            logger.error(f"Script not found: {script_path}")
            if script_owner_id in user_files:
                user_files[script_owner_id] = [f for f in user_files.get(script_owner_id, []) if f[0] != file_name]
                if not user_files[script_owner_id]:
                    del user_files[script_owner_id]
            try:
                conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
                c = conn.cursor()
                c.execute('DELETE FROM user_files WHERE user_id = ? AND file_name = ?',
                          (script_owner_id, file_name))
                conn.commit()
                conn.close()
            except: pass
            return

        # Pre-check for missing modules (first attempt only)
        if attempt == 1:
            check_proc = None
            try:
                check_proc = subprocess.Popen(
                    [sys.executable, script_path], cwd=user_folder,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding='utf-8', errors='ignore'
                )
                _, stderr = check_proc.communicate(timeout=5)
                if check_proc.returncode != 0 and stderr:
                    match = re.search(r"ModuleNotFoundError: No module named '(.+?)'", stderr)
                    if match:
                        module = match.group(1).strip().strip("'\"")
                        if attempt_install_pip(module, message_obj_for_reply):
                            time.sleep(2)
                            return run_script(script_path, script_owner_id, user_folder,
                                              file_name, message_obj_for_reply, attempt + 1)
                        else:
                            try: bot.reply_to(message_obj_for_reply, f"❌ Install failed for `{module}`.")
                            except: pass
                            return
            except subprocess.TimeoutExpired:
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
                    try: check_proc.communicate(timeout=1)
                    except: pass
            except Exception as e:
                logger.error(f"Pre-check error: {e}")
            finally:
                if check_proc and check_proc.poll() is None:
                    try: check_proc.kill(); check_proc.communicate(timeout=1)
                    except: pass

        # Start long-running process
        log_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = open(log_path, 'w', encoding='utf-8', errors='ignore')

        startupinfo = None
        creationflags = 0
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        process = subprocess.Popen(
            [sys.executable, script_path], cwd=user_folder,
            stdout=log_file, stderr=log_file, stdin=subprocess.PIPE,
            startupinfo=startupinfo, creationflags=creationflags,
            encoding='utf-8', errors='ignore'
        )

        bot_scripts[script_key] = {
            'process': process, 'log_file': log_file, 'file_name': file_name,
            'chat_id': message_obj_for_reply.chat.id,
            'script_owner_id': script_owner_id,
            'start_time': datetime.now(), 'user_folder': user_folder,
            'type': 'py', 'script_key': script_key
        }

        try:
            bot.reply_to(message_obj_for_reply,
                         f"✅ Python script '{file_name}' started! (PID: {process.pid})")
        except: pass

        save_autorestart_state()
        logger.info(f"Started Python PID {process.pid} for {script_key}")

    except FileNotFoundError:
        logger.error(f"Python not found")
        try: bot.reply_to(message_obj_for_reply, "❌ Python interpreter not found.")
        except: pass
    except Exception as e:
        logger.error(f"Run script error: {e}", exc_info=True)
        try: bot.reply_to(message_obj_for_reply, f"❌ Error: {str(e)[:200]}")
        except: pass

def run_js_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1):
    max_attempts = 2
    if attempt > max_attempts:
        try: bot.reply_to(message_obj_for_reply, f"❌ Failed to run '{file_name}'")
        except: pass
        return

    script_key = f"{script_owner_id}_{file_name}"

    try:
        if not os.path.exists(script_path):
            logger.error(f"JS script not found: {script_path}")
            if script_owner_id in user_files:
                user_files[script_owner_id] = [f for f in user_files.get(script_owner_id, []) if f[0] != file_name]
                if not user_files[script_owner_id]:
                    del user_files[script_owner_id]
            return

        if attempt == 1:
            check_proc = None
            try:
                check_proc = subprocess.Popen(
                    ['node', script_path], cwd=user_folder,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding='utf-8', errors='ignore'
                )
                _, stderr = check_proc.communicate(timeout=5)
                if check_proc.returncode != 0 and stderr:
                    match = re.search(r"Cannot find module '(.+?)'", stderr)
                    if match:
                        module = match.group(1).strip().strip("'\"")
                        if not module.startswith('.') and not module.startswith('/'):
                            if attempt_install_npm(module, user_folder, message_obj_for_reply):
                                time.sleep(2)
                                return run_js_script(script_path, script_owner_id, user_folder,
                                                     file_name, message_obj_for_reply, attempt + 1)
                            return
            except subprocess.TimeoutExpired:
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
                    try: check_proc.communicate(timeout=1)
                    except: pass
            except FileNotFoundError:
                try: bot.reply_to(message_obj_for_reply, "❌ Node.js not installed.")
                except: pass
                return
            except Exception as e:
                logger.error(f"JS pre-check error: {e}")
            finally:
                if check_proc and check_proc.poll() is None:
                    try: check_proc.kill(); check_proc.communicate(timeout=1)
                    except: pass

        log_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = open(log_path, 'w', encoding='utf-8', errors='ignore')

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
            'chat_id': message_obj_for_reply.chat.id,
            'script_owner_id': script_owner_id,
            'start_time': datetime.now(), 'user_folder': user_folder,
            'type': 'js', 'script_key': script_key
        }

        try:
            bot.reply_to(message_obj_for_reply,
                         f"✅ JS script '{file_name}' started! (PID: {process.pid})")
        except: pass

        save_autorestart_state()
    except FileNotFoundError:
        try: bot.reply_to(message_obj_for_reply, "❌ 'node' not found.")
        except: pass
    except Exception as e:
        logger.error(f"Run JS error: {e}", exc_info=True)
        try: bot.reply_to(message_obj_for_reply, f"❌ Error: {str(e)[:200]}")
        except: pass

# ============================================================
# DATABASE OPS
# ============================================================
DB_LOCK = threading.Lock()

def save_user_file(user_id, file_name, file_type='py'):
    with DB_LOCK:
        try:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute('INSERT OR REPLACE INTO user_files (user_id, file_name, file_type) VALUES (?, ?, ?)',
                      (user_id, file_name, file_type))
            conn.commit()
            conn.close()
            if user_id not in user_files: user_files[user_id] = []
            user_files[user_id] = [(fn, ft) for fn, ft in user_files[user_id] if fn != file_name]
            user_files[user_id].append((file_name, file_type))
        except Exception as e:
            logger.error(f"Save file error: {e}")

def remove_user_file_db(user_id, file_name):
    with DB_LOCK:
        try:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute('DELETE FROM user_files WHERE user_id = ? AND file_name = ?', (user_id, file_name))
            conn.commit()
            conn.close()
            if user_id in user_files:
                user_files[user_id] = [f for f in user_files[user_id] if f[0] != file_name]
                if not user_files[user_id]: del user_files[user_id]
        except Exception as e:
            logger.error(f"Remove file error: {e}")

def add_active_user(user_id):
    active_users.add(user_id)
    with DB_LOCK:
        try:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute('INSERT OR IGNORE INTO active_users (user_id) VALUES (?)', (user_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Active user error: {e}")

def save_subscription(user_id, expiry):
    with DB_LOCK:
        try:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute('INSERT OR REPLACE INTO subscriptions (user_id, expiry) VALUES (?, ?)',
                      (user_id, expiry.isoformat()))
            conn.commit()
            conn.close()
            user_subscriptions[user_id] = {'expiry': expiry}
        except Exception as e:
            logger.error(f"Save sub error: {e}")

def remove_subscription_db(user_id):
    with DB_LOCK:
        try:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute('DELETE FROM subscriptions WHERE user_id = ?', (user_id,))
            conn.commit()
            conn.close()
            user_subscriptions.pop(user_id, None)
        except Exception as e:
            logger.error(f"Remove sub error: {e}")

def add_admin_db(admin_id):
    with DB_LOCK:
        try:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (admin_id,))
            conn.commit()
            conn.close()
            admin_ids.add(admin_id)
        except Exception as e:
            logger.error(f"Add admin error: {e}")

def remove_admin_db(admin_id):
    if admin_id == OWNER_ID:
        return False
    with DB_LOCK:
        try:
            conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
            c = conn.cursor()
            c.execute('DELETE FROM admins WHERE user_id = ?', (admin_id,))
            conn.commit()
            conn.close()
            admin_ids.discard(admin_id)
            return True
        except Exception as e:
            logger.error(f"Remove admin error: {e}")
            return False

# ============================================================
# MENU BUILDERS
# ============================================================
def create_main_menu_inline(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton('📢 Updates Channel', url=UPDATE_CHANNEL),
        types.InlineKeyboardButton('📤 Upload File', callback_data='upload'),
        types.InlineKeyboardButton('📂 Check Files', callback_data='check_files'),
        types.InlineKeyboardButton('⚡ Bot Speed', callback_data='speed'),
        types.InlineKeyboardButton('📤 Send Command', callback_data='send_command'),
        types.InlineKeyboardButton('📞 Contact Owner',
                                   url=f'https://t.me/{YOUR_USERNAME.replace("@", "")}')
    ]
    if user_id in admin_ids:
        admin_buttons = [
            types.InlineKeyboardButton('💳 Subscriptions', callback_data='subscription'),
            types.InlineKeyboardButton('📊 Statistics', callback_data='stats'),
            types.InlineKeyboardButton('🔒 Lock Bot' if not bot_locked else '🔓 Unlock Bot',
                                       callback_data='lock_bot' if not bot_locked else 'unlock_bot'),
            types.InlineKeyboardButton('📢 Broadcast', callback_data='broadcast'),
            types.InlineKeyboardButton('👑 Admin Panel', callback_data='admin_panel'),
            types.InlineKeyboardButton('🟢 Run All User Scripts', callback_data='run_all_scripts')
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
        markup.add(types.InlineKeyboardButton('📊 Statistics', callback_data='stats'))
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
    if is_running:
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
    markup.row(types.InlineKeyboardButton('🔙 Back to Main', callback_data='back_to_main'))
    return markup

def create_subscription_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        types.InlineKeyboardButton('➕ Add Subscription', callback_data='add_subscription'),
        types.InlineKeyboardButton('➖ Remove Subscription', callback_data='remove_subscription')
    )
    markup.row(types.InlineKeyboardButton('🔍 Check Subscription', callback_data='check_subscription'))
    markup.row(types.InlineKeyboardButton('🔙 Back to Main', callback_data='back_to_main'))
    return markup

def create_send_command_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        types.InlineKeyboardButton('📝 Send to Process', callback_data='send_to_process'),
        types.InlineKeyboardButton('🔍 View All Logs', callback_data='view_all_logs')
    )
    markup.row(types.InlineKeyboardButton('🔙 Back to Main', callback_data='back_to_main'))
    return markup

# ============================================================
# LOGIC FUNCTIONS
# ============================================================
@require_verification
def _logic_send_welcome(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_name = message.from_user.first_name
    user_username = message.from_user.username

    if bot_locked and user_id not in admin_ids:
        bot.send_message(chat_id, "⚠️ Bot locked by admin.")
        return

    if user_id not in active_users:
        add_active_user(user_id)
        try:
            bot.send_message(OWNER_ID, f"🎉 New user: {user_name} (@{user_username}) - {user_id}")
        except: pass

    limit = get_user_file_limit(user_id)
    current = get_user_file_count(user_id)
    limit_str = str(limit) if limit != float('inf') else "Unlimited"
    expiry_info = ""

    if user_id == OWNER_ID:
        status = "👑 Owner"
    elif user_id in admin_ids:
        status = "🛡️ Admin"
    elif user_id in user_subscriptions:
        expiry = user_subscriptions[user_id].get('expiry')
        if expiry and expiry > datetime.now():
            days_left = (expiry - datetime.now()).days
            status = "⭐ Premium"
            expiry_info = f"\n⏳ Premium expires in: {days_left} days"
        else:
            status = "🆓 Free User"
    else:
        status = "🆓 Free User"

    msg = (f"〽️ Welcome, {user_name}!\n\n"
           f"🆔 ID: `{user_id}`\n"
           f"🔰 Status: {status}{expiry_info}\n"
           f"📁 Files: {current} / {limit_str}\n\n"
           f"🤖 Host & run Python (.py) or JS (.js) scripts.\n\n"
           f"👇 Use buttons below.")
    try:
        bot.send_message(chat_id, msg, reply_markup=create_reply_keyboard_main_menu(user_id),
                         parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Welcome error: {e}")

@require_verification
def _logic_updates_channel(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('📢 Updates Channel', url=UPDATE_CHANNEL))
    bot.reply_to(message, "Visit our Updates Channel:", reply_markup=markup)

@require_verification
def _logic_upload_file(message):
    user_id = message.from_user.id
    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Bot locked.")
        return
    limit = get_user_file_limit(user_id)
    current = get_user_file_count(user_id)
    if current >= limit:
        bot.reply_to(message, f"⚠️ File limit reached ({current}/{limit}). Delete first.")
        return
    bot.reply_to(message, f"📤 Send your .py, .js, or .zip file.\n📊 Limit: {current}/{limit if limit != float('inf') else '∞'}")

@require_verification
def _logic_check_files(message):
    user_id = message.from_user.id
    files = user_files.get(user_id, [])
    if not files:
        bot.reply_to(message, "📂 No files uploaded yet.")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for file_name, file_type in sorted(files):
        running = is_bot_running(user_id, file_name)
        icon = "🟢 Running" if running else "🔴 Stopped"
        markup.add(types.InlineKeyboardButton(f"{file_name} ({file_type}) - {icon}",
                                              callback_data=f'file_{user_id}_{file_name}'))
    bot.reply_to(message, "📂 Your files:", reply_markup=markup, parse_mode='Markdown')

@require_verification
def _logic_bot_speed(message):
    user_id = message.from_user.id
    start = time.time()
    wait_msg = bot.reply_to(message, "🏃 Testing...")
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        rt = round((time.time() - start) * 1000, 2)
        status = "🔓 Unlocked" if not bot_locked else "🔒 Locked"
        bot.edit_message_text(f"⚡ Bot Speed:\n\n⏱️ {rt} ms\n🚦 {status}",
                              message.chat.id, wait_msg.message_id)
    except Exception as e:
        logger.error(f"Speed error: {e}")

@require_verification
def _logic_contact_owner(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('📞 Contact',
                                          url=f'https://t.me/{YOUR_USERNAME.replace("@", "")}'))
    bot.reply_to(message, "Contact Owner:", reply_markup=markup)

@require_verification
def _logic_subscriptions_panel(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin only.")
        return
    bot.reply_to(message, "💳 Subscriptions:", reply_markup=create_subscription_menu())

@require_verification
def _logic_statistics(message):
    user_id = message.from_user.id
    total_users = len(active_users)
    total_files = sum(len(files) for files in user_files.values())
    running_count = 0
    for key, info in list(bot_scripts.items()):
        if is_bot_running(info['script_owner_id'], info['file_name']):
            running_count += 1
    stats = (f"📊 Statistics:\n\n"
             f"👥 Users: {total_users}\n"
             f"📂 Files: {total_files}\n"
             f"🟢 Running: {running_count}\n"
             f"🔒 Status: {'Locked' if bot_locked else 'Unlocked'}")
    bot.reply_to(message, stats)

@require_verification
def _logic_broadcast_init(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin only.")
        return
    msg = bot.reply_to(message, "📢 Send broadcast message. /cancel to abort.")
    bot.register_next_step_handler(msg, process_broadcast_message)

@require_verification
def _logic_toggle_lock_bot(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin only.")
        return
    global bot_locked
    bot_locked = not bot_locked
    bot.reply_to(message, f"🔒 Bot {'locked' if bot_locked else 'unlocked'}.")

@require_verification
def _logic_admin_panel(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin only.")
        return
    bot.reply_to(message, "👑 Admin Panel:", reply_markup=create_admin_panel())

@require_verification
def _logic_run_all_scripts(message_or_call):
    if isinstance(message_or_call, telebot.types.Message):
        admin_id = message_or_call.from_user.id
        chat_id = message_or_call.chat.id
        reply = lambda text, **kw: bot.reply_to(message_or_call, text, **kw)
        msg_obj = message_or_call
    else:
        admin_id = message_or_call.from_user.id
        chat_id = message_or_call.message.chat.id
        bot.answer_callback_query(message_or_call.id)
        reply = lambda text, **kw: bot.send_message(chat_id, text, **kw)
        msg_obj = message_or_call.message

    if admin_id not in admin_ids:
        reply("⚠️ Admin only.")
        return

    reply("⏳ Running all scripts...")
    started = 0
    for target_user_id, files in dict(user_files).items():
        user_folder = get_user_folder(target_user_id)
        for file_name, file_type in files:
            if not is_bot_running(target_user_id, file_name):
                path = os.path.join(user_folder, file_name)
                if os.path.exists(path):
                    if file_type == 'py':
                        threading.Thread(target=run_script,
                                         args=(path, target_user_id, user_folder, file_name, msg_obj),
                                         daemon=True).start()
                        started += 1
                    elif file_type == 'js':
                        threading.Thread(target=run_js_script,
                                         args=(path, target_user_id, user_folder, file_name, msg_obj),
                                         daemon=True).start()
                        started += 1
    reply(f"✅ Started {started} script(s).")

# ============================================================
# COMMAND HANDLERS
# ============================================================
@bot.message_handler(commands=['start', 'help'])
def command_send_welcome(message):
    user_id = message.from_user.id
    if user_id in admin_ids:
        _logic_send_welcome(message)
        return
    is_member, status = check_channel_membership(user_id)
    if is_member:
        save_verified_user(user_id)
        _logic_send_welcome(message)
    else:
        send_verification_prompt(message.chat.id, user_id)

BUTTON_TEXT_TO_LOGIC = {
    "📢 Updates Channel": _logic_updates_channel,
    "📤 Upload File": _logic_upload_file,
    "📂 Check Files": _logic_check_files,
    "⚡ Bot Speed": _logic_bot_speed,
    "📤 Send Command": lambda m: bot.reply_to(m, "Send command options:",
                                              reply_markup=create_send_command_menu()),
    "📞 Contact Owner": _logic_contact_owner,
    "📊 Statistics": _logic_statistics,
    "💳 Subscriptions": _logic_subscriptions_panel,
    "📢 Broadcast": _logic_broadcast_init,
    "🔒 Lock Bot": _logic_toggle_lock_bot,
    "🟢 Running All Code": _logic_run_all_scripts,
    "👑 Admin Panel": _logic_admin_panel,
}

@bot.message_handler(func=lambda message: message.text in BUTTON_TEXT_TO_LOGIC)
def handle_button_text(message):
    user_id = message.from_user.id
    if user_id not in admin_ids:
        is_member, status = check_channel_membership(user_id)
        if not is_member:
            send_verification_prompt(message.chat.id, user_id)
            return
    func = BUTTON_TEXT_TO_LOGIC.get(message.text)
    if func: func(message)

# ============================================================
# FILE UPLOAD HANDLER
# ============================================================
@bot.message_handler(content_types=['document'])
def handle_file_upload_doc(message):
    user_id = message.from_user.id
    chat_id = message.chat.id

    if user_id not in admin_ids:
        is_member, status = check_channel_membership(user_id)
        if not is_member:
            send_verification_prompt(chat_id, user_id)
            return

    doc = message.document
    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Bot locked.")
        return

    limit = get_user_file_limit(user_id)
    current = get_user_file_count(user_id)
    if current >= limit:
        bot.reply_to(message, f"⚠️ Limit reached ({current}/{limit}).")
        return

    file_name = doc.file_name
    if not file_name:
        bot.reply_to(message, "⚠️ No file name.")
        return
    ext = os.path.splitext(file_name)[1].lower()
    if ext not in ['.py', '.js', '.zip']:
        bot.reply_to(message, "⚠️ Only .py, .js, .zip allowed.")
        return
    if doc.file_size > 20 * 1024 * 1024:
        bot.reply_to(message, "⚠️ File too large (Max 20MB).")
        return

    try:
        wait = bot.reply_to(message, f"⏳ Downloading `{file_name}`...")
        info = bot.get_file(doc.file_id)
        content = bot.download_file(info.file_path)

        if user_id != OWNER_ID and user_id not in admin_ids:
            safe, reason = scan_file_for_malware(content, file_name, user_id)
            if not safe:
                bot.edit_message_text(f"🚨 Security Alert: {reason}", chat_id, wait.message_id)
                return

        user_folder = get_user_folder(user_id)

        if ext == '.zip':
            handle_zip_file(content, file_name, message)
        else:
            path = os.path.join(user_folder, file_name)
            with open(path, 'wb') as f:
                f.write(content)
            if ext == '.js':
                save_user_file(user_id, file_name, 'js')
                threading.Thread(target=run_js_script,
                                 args=(path, user_id, user_folder, file_name, message),
                                 daemon=True).start()
            elif ext == '.py':
                save_user_file(user_id, file_name, 'py')
                threading.Thread(target=run_script,
                                 args=(path, user_id, user_folder, file_name, message),
                                 daemon=True).start()

        bot.edit_message_text(f"✅ Downloaded `{file_name}`. Processing...",
                              chat_id, wait.message_id)
    except Exception as e:
        logger.error(f"Upload error: {e}", exc_info=True)
        try: bot.reply_to(message, f"❌ Error: {str(e)[:200]}")
        except: pass

def handle_zip_file(content, file_name_zip, message):
    user_id = message.from_user.id
    user_folder = get_user_folder(user_id)
    temp_dir = None

    if user_id != OWNER_ID and user_id not in admin_ids:
        safe, reason = scan_file_for_malware(content, file_name_zip, user_id)
        if not safe:
            bot.reply_to(message, f"🚨 Security Alert: {reason}")
            return

    try:
        temp_dir = tempfile.mkdtemp(prefix=f"user_{user_id}_zip_")
        zip_path = os.path.join(temp_dir, file_name_zip)
        with open(zip_path, 'wb') as f:
            f.write(content)

        with zipfile.ZipFile(zip_path, 'r') as zf:
            if user_id != OWNER_ID and user_id not in admin_ids:
                for m in zf.infolist():
                    if any(m.filename.lower().endswith(ext) for ext in ['.exe', '.dll', '.bat', '.cmd']):
                        bot.reply_to(message, f"🚨 ZIP contains suspicious: {m.filename}")
                        return
            zf.extractall(temp_dir)

        # Find main script
        target_dir = temp_dir
        root_files = os.listdir(target_dir)
        if not any(f.endswith(('.py', '.js')) for f in root_files):
            for root, dirs, files in os.walk(temp_dir):
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                if any(f.endswith(('.py', '.js')) for f in files):
                    target_dir = root
                    break

        if target_dir != temp_dir:
            for item in os.listdir(target_dir):
                s = os.path.join(target_dir, item)
                d = os.path.join(temp_dir, item)
                if os.path.exists(d):
                    if os.path.isdir(d): shutil.rmtree(d)
                    else: os.remove(d)
                shutil.move(s, d)
            extracted = os.listdir(temp_dir)
        else:
            extracted = root_files

        py_files = [f for f in extracted if f.endswith('.py')]
        js_files = [f for f in extracted if f.endswith('.js')]
        req = 'requirements.txt' if 'requirements.txt' in extracted else None

        if req:
            req_path = os.path.join(temp_dir, req)
            bot.reply_to(message, "🔄 Installing deps...")
            try:
                subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', req_path],
                               check=True, capture_output=True, timeout=300)
            except Exception as e:
                logger.error(f"req install error: {e}")

        main_script = None
        file_type = None
        for p in ['main.py', 'bot.py', 'app.py']:
            if p in py_files:
                main_script = p; file_type = 'py'; break
        if not main_script:
            for p in ['index.js', 'main.js', 'bot.js']:
                if p in js_files:
                    main_script = p; file_type = 'js'; break
        if not main_script:
            if py_files:
                main_script = py_files[0]; file_type = 'py'
            elif js_files:
                main_script = js_files[0]; file_type = 'js'

        if not main_script:
            bot.reply_to(message, "❌ No script found in ZIP.")
            return

        # Move extracted files to user folder
        for item in os.listdir(temp_dir):
            if item == file_name_zip: continue
            src = os.path.join(temp_dir, item)
            dst = os.path.join(user_folder, item)
            if os.path.isdir(dst): shutil.rmtree(dst)
            elif os.path.exists(dst): os.remove(dst)
            shutil.move(src, dst)

        save_user_file(user_id, main_script, file_type)
        main_path = os.path.join(user_folder, main_script)
        bot.reply_to(message, f"✅ Extracted. Starting `{main_script}`...")

        if file_type == 'py':
            threading.Thread(target=run_script,
                             args=(main_path, user_id, user_folder, main_script, message),
                             daemon=True).start()
        else:
            threading.Thread(target=run_js_script,
                             args=(main_path, user_id, user_folder, main_script, message),
                             daemon=True).start()
    except zipfile.BadZipFile as e:
        logger.error(f"Bad zip: {e}")
        bot.reply_to(message, f"❌ Invalid ZIP: {e}")
    except Exception as e:
        logger.error(f"ZIP error: {e}", exc_info=True)
        bot.reply_to(message, f"❌ ZIP error: {str(e)[:200]}")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            try: shutil.rmtree(temp_dir)
            except: pass

# ============================================================
# CALLBACK HANDLER
# ============================================================
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    data = call.data

    if data.startswith('verify_'):
        process_verification(call)
        return

    if bot_locked and user_id not in admin_ids and data not in ['back_to_main', 'speed', 'stats']:
        bot.answer_callback_query(call.id, "⚠️ Bot locked.", show_alert=True)
        return

    if user_id not in admin_ids:
        is_member, status = check_channel_membership(user_id)
        if not is_member:
            send_verification_prompt(call.message.chat.id, user_id)
            bot.answer_callback_query(call.id, "❌ Join channel first.", show_alert=True)
            return

    try:
        if data == 'upload':
            bot.answer_callback_query(call.id); _logic_upload_file(call.message)
        elif data == 'check_files':
            bot.answer_callback_query(call.id); _logic_check_files(call.message)
        elif data.startswith('file_'):
            file_control_callback(call)
        elif data.startswith('start_'):
            start_bot_callback(call)
        elif data.startswith('stop_'):
            stop_bot_callback(call)
        elif data.startswith('restart_'):
            restart_bot_callback(call)
        elif data.startswith('delete_'):
            delete_bot_callback(call)
        elif data.startswith('logs_'):
            logs_bot_callback(call)
        elif data == 'speed':
            speed_callback(call)
        elif data == 'back_to_main':
            back_to_main_callback(call)
        elif data == 'send_command':
            bot.answer_callback_query(call.id)
            bot.send_message(call.message.chat.id, "📤 Send Command:",
                             reply_markup=create_send_command_menu())
        elif data == 'send_to_process':
            bot.answer_callback_query(call.id); send_to_process_init(call.message)
        elif data.startswith('sendcmd_select_'):
            sendcmd_select_callback(call)
        elif data == 'view_all_logs':
            bot.answer_callback_query(call.id); view_all_logs(call.message)
        elif data.startswith('viewlog_'):
            viewlog_callback(call)
        elif data == 'subscription':
            admin_required_callback(call, subscription_management_callback)
        elif data == 'stats':
            bot.answer_callback_query(call.id); _logic_statistics(call.message)
        elif data == 'lock_bot':
            admin_required_callback(call, lock_bot_callback)
        elif data == 'unlock_bot':
            admin_required_callback(call, unlock_bot_callback)
        elif data == 'run_all_scripts':
            admin_required_callback(call, run_all_scripts_callback)
        elif data == 'broadcast':
            admin_required_callback(call, broadcast_init_callback)
        elif data == 'admin_panel':
            admin_required_callback(call, admin_panel_callback)
        elif data == 'add_admin':
            owner_required_callback(call, add_admin_init_callback)
        elif data == 'remove_admin':
            owner_required_callback(call, remove_admin_init_callback)
        elif data == 'list_admins':
            admin_required_callback(call, list_admins_callback)
        elif data == 'add_subscription':
            admin_required_callback(call, add_subscription_init_callback)
        elif data == 'remove_subscription':
            admin_required_callback(call, remove_subscription_init_callback)
        elif data == 'check_subscription':
            admin_required_callback(call, check_subscription_init_callback)
        elif data.startswith('confirm_broadcast_'):
            handle_confirm_broadcast(call)
        elif data == 'cancel_broadcast':
            handle_cancel_broadcast(call)
        else:
            bot.answer_callback_query(call.id, "Unknown action.")
    except Exception as e:
        logger.error(f"Callback error '{data}': {e}", exc_info=True)
        try: bot.answer_callback_query(call.id, "Error.", show_alert=True)
        except: pass

def admin_required_callback(call, func):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "⚠️ Admin only.", show_alert=True)
        return
    func(call)

def owner_required_callback(call, func):
    if call.from_user.id != OWNER_ID:
        bot.answer_callback_query(call.id, "⚠️ Owner only.", show_alert=True)
        return
    func(call)

# --- Callback implementations ---
def send_command_callback(call):
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text("📤 Send Command Options:",
                              call.message.chat.id, call.message.message_id,
                              reply_markup=create_send_command_menu())
    except Exception as e:
        logger.error(f"Send cmd menu error: {e}")

def send_to_process_init(message):
    user_id = message.from_user.id
    running = []
    for key, info in bot_scripts.items():
        owner = info['script_owner_id']
        if (user_id == owner or user_id in admin_ids) and is_bot_running(owner, info['file_name']):
            running.append((key, info))
    if not running:
        bot.reply_to(message, "❌ No running scripts.")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for key, info in running:
        markup.add(types.InlineKeyboardButton(
            f"{info['file_name']} (User: {info['script_owner_id']})",
            callback_data=f'sendcmd_select_{key}'))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data='send_command'))
    bot.reply_to(message, "📝 Select a running script:", reply_markup=markup)

def send_to_process_callback(call):
    bot.answer_callback_query(call.id)
    send_to_process_init(call.message)

def sendcmd_select_callback(call):
    try:
        script_key = call.data.replace('sendcmd_select_', '')
        bot.answer_callback_query(call.id, f"Selected: {script_key}")
        msg = bot.send_message(call.message.chat.id, f"📝 Enter command for {script_key}:")
        bot.register_next_step_handler(msg, lambda m: process_send_command(m, script_key))
    except Exception as e:
        logger.error(f"Sendcmd select error: {e}")

def process_send_command(message, script_key):
    if script_key not in bot_scripts:
        bot.reply_to(message, "❌ Script not running.")
        return
    info = bot_scripts[script_key]
    try:
        if info['process'] and info['process'].poll() is None:
            info['process'].stdin.write(message.text + '\n')
            info['process'].stdin.flush()
            bot.reply_to(message, f"✅ Sent to `{info['file_name']}`", parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

def view_all_logs(message):
    user_id = message.from_user.id
    folder = get_user_folder(user_id)
    logs = []
    if os.path.exists(folder):
        for f in os.listdir(folder):
            if f.endswith('.log'):
                logs.append(f)
    if not logs:
        bot.reply_to(message, "📜 No logs.")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for log in sorted(logs):
        markup.add(types.InlineKeyboardButton(log, callback_data=f'viewlog_{user_id}_{log}'))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data='back_to_main'))
    bot.reply_to(message, "📜 Logs:", reply_markup=markup)

def view_all_logs_callback(call):
    bot.answer_callback_query(call.id)
    view_all_logs(call.message)

def viewlog_callback(call):
    try:
        parts = call.data.split('_', 2)
        uid = int(parts[1])
        logf = parts[2]
        if call.from_user.id != uid and call.from_user.id not in admin_ids:
            bot.answer_callback_query(call.id, "⚠️ Denied.", show_alert=True)
            return
        path = os.path.join(get_user_folder(uid), logf)
        if not os.path.exists(path):
            bot.answer_callback_query(call.id, "❌ Not found.")
            return
        bot.answer_callback_query(call.id, "📜 Sending...")
        with open(path, 'rb') as f:
            bot.send_document(call.message.chat.id, f, caption=f"📜 {logf}")
    except Exception as e:
        logger.error(f"Viewlog error: {e}")

def file_control_callback(call):
    try:
        parts = call.data.split('_', 2)
        owner_id = int(parts[1])
        file_name = parts[2]
        req = call.from_user.id
        if not (req == owner_id or req in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ Denied.", show_alert=True); return
        files = user_files.get(owner_id, [])
        if not any(f[0] == file_name for f in files):
            bot.answer_callback_query(call.id, "⚠️ Not found."); return
        bot.answer_callback_query(call.id)
        running = is_bot_running(owner_id, file_name)
        status = '🟢 Running' if running else '🔴 Stopped'
        file_type = next((f[1] for f in files if f[0] == file_name), '?')
        bot.edit_message_text(
            f"⚙️ `{file_name}` ({file_type})\nStatus: {status}",
            call.message.chat.id, call.message.message_id,
            reply_markup=create_control_buttons(owner_id, file_name, running),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"File control error: {e}")

def start_bot_callback(call):
    try:
        parts = call.data.split('_', 2)
        owner_id = int(parts[1])
        file_name = parts[2]
        req = call.from_user.id
        if not (req == owner_id or req in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ Denied."); return
        files = user_files.get(owner_id, [])
        info = next((f for f in files if f[0] == file_name), None)
        if not info:
            bot.answer_callback_query(call.id, "⚠️ Not found."); return
        file_type = info[1]
        folder = get_user_folder(owner_id)
        path = os.path.join(folder, file_name)
        if not os.path.exists(path):
            bot.answer_callback_query(call.id, "⚠️ File missing!")
            remove_user_file_db(owner_id, file_name)
            return
        if is_bot_running(owner_id, file_name):
            bot.answer_callback_query(call.id, "⚠️ Already running.")
            return
        bot.answer_callback_query(call.id, "⏳ Starting...")
        if file_type == 'py':
            threading.Thread(target=run_script,
                             args=(path, owner_id, folder, file_name, call.message),
                             daemon=True).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script,
                             args=(path, owner_id, folder, file_name, call.message),
                             daemon=True).start()
        time.sleep(1.5)
        is_now = is_bot_running(owner_id, file_name)
        status = '🟢 Running' if is_now else '🟡 Starting...'
        bot.edit_message_text(
            f"⚙️ `{file_name}` ({file_type})\nStatus: {status}",
            call.message.chat.id, call.message.message_id,
            reply_markup=create_control_buttons(owner_id, file_name, is_now),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Start bot callback error: {e}")

def stop_bot_callback(call):
    try:
        parts = call.data.split('_', 2)
        owner_id = int(parts[1])
        file_name = parts[2]
        req = call.from_user.id
        if not (req == owner_id or req in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ Denied."); return
        files = user_files.get(owner_id, [])
        info = next((f for f in files if f[0] == file_name), None)
        if not info:
            bot.answer_callback_query(call.id, "⚠️ Not found."); return
        file_type = info[1]
        script_key = f"{owner_id}_{file_name}"
        bot.answer_callback_query(call.id, "⏳ Stopping...")
        if script_key in bot_scripts:
            kill_process_tree(bot_scripts[script_key])
            bot_scripts.pop(script_key, None)
        bot.edit_message_text(
            f"⚙️ `{file_name}` ({file_type})\nStatus: 🔴 Stopped",
            call.message.chat.id, call.message.message_id,
            reply_markup=create_control_buttons(owner_id, file_name, False),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Stop error: {e}")

def restart_bot_callback(call):
    try:
        parts = call.data.split('_', 2)
        owner_id = int(parts[1])
        file_name = parts[2]
        req = call.from_user.id
        if not (req == owner_id or req in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ Denied."); return
        files = user_files.get(owner_id, [])
        info = next((f for f in files if f[0] == file_name), None)
        if not info:
            bot.answer_callback_query(call.id, "⚠️ Not found."); return
        file_type = info[1]
        folder = get_user_folder(owner_id)
        path = os.path.join(folder, file_name)
        script_key = f"{owner_id}_{file_name}"
        bot.answer_callback_query(call.id, "⏳ Restarting...")
        if is_bot_running(owner_id, file_name):
            if script_key in bot_scripts:
                kill_process_tree(bot_scripts[script_key])
                bot_scripts.pop(script_key, None)
            time.sleep(1.5)
        if file_type == 'py':
            threading.Thread(target=run_script,
                             args=(path, owner_id, folder, file_name, call.message),
                             daemon=True).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script,
                             args=(path, owner_id, folder, file_name, call.message),
                             daemon=True).start()
        time.sleep(1.5)
        is_now = is_bot_running(owner_id, file_name)
        status = '🟢 Running' if is_now else '🟡 Starting...'
        bot.edit_message_text(
            f"⚙️ `{file_name}` ({file_type})\nStatus: {status}",
            call.message.chat.id, call.message.message_id,
            reply_markup=create_control_buttons(owner_id, file_name, is_now),
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Restart error: {e}")

def delete_bot_callback(call):
    try:
        parts = call.data.split('_', 2)
        owner_id = int(parts[1])
        file_name = parts[2]
        req = call.from_user.id
        if not (req == owner_id or req in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ Denied."); return
        bot.answer_callback_query(call.id, "🗑️ Deleting...")
        script_key = f"{owner_id}_{file_name}"
        if is_bot_running(owner_id, file_name):
            if script_key in bot_scripts:
                kill_process_tree(bot_scripts[script_key])
                bot_scripts.pop(script_key, None)
            time.sleep(0.5)
        folder = get_user_folder(owner_id)
        for p in [os.path.join(folder, file_name),
                  os.path.join(folder, f"{os.path.splitext(file_name)[0]}.log")]:
            if os.path.exists(p):
                try: os.remove(p)
                except: pass
        remove_user_file_db(owner_id, file_name)
        bot.edit_message_text(f"🗑️ `{file_name}` deleted.",
                              call.message.chat.id, call.message.message_id,
                              parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Delete error: {e}")

def logs_bot_callback(call):
    try:
        parts = call.data.split('_', 2)
        owner_id = int(parts[1])
        file_name = parts[2]
        req = call.from_user.id
        if not (req == owner_id or req in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ Denied."); return
        folder = get_user_folder(owner_id)
        path = os.path.join(folder, f"{os.path.splitext(file_name)[0]}.log")
        if not os.path.exists(path):
            bot.answer_callback_query(call.id, "⚠️ No logs."); return
        bot.answer_callback_query(call.id)
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()[-4000:]
        bot.send_message(call.message.chat.id,
                         f"📜 `{file_name}`:\n```\n{content}\n```",
                         parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Logs error: {e}")

def speed_callback(call):
    start = time.time()
    bot.send_chat_action(call.message.chat.id, 'typing')
    rt = round((time.time() - start) * 1000, 2)
    status = "🔓 Unlocked" if not bot_locked else "🔒 Locked"
    bot.answer_callback_query(call.id)
    bot.edit_message_text(f"⚡ Speed: {rt} ms\n🚦 {status}",
                          call.message.chat.id, call.message.message_id)

def back_to_main_callback(call):
    user_id = call.from_user.id
    try:
        bot.answer_callback_query(call.id)
        bot.edit_message_text(
            f"〽️ Main Menu\n🆔 `{user_id}`",
            call.message.chat.id, call.message.message_id,
            reply_markup=create_main_menu_inline(user_id),
            parse_mode='Markdown'
        )
    except: pass

def subscription_management_callback(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text("💳 Subscriptions:", call.message.chat.id,
                          call.message.message_id,
                          reply_markup=create_subscription_menu())

def lock_bot_callback(call):
    global bot_locked
    bot_locked = True
    bot.answer_callback_query(call.id, "🔒 Locked.")

def unlock_bot_callback(call):
    global bot_locked
    bot_locked = False
    bot.answer_callback_query(call.id, "🔓 Unlocked.")

def run_all_scripts_callback(call):
    _logic_run_all_scripts(call)

def broadcast_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "📢 Send broadcast. /cancel to abort.")
    bot.register_next_step_handler(msg, process_broadcast_message)

def process_broadcast_message(message):
    if message.from_user.id not in admin_ids:
        return
    if message.text and message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled."); return
    content = message.text
    if not content and not (message.photo or message.video):
        bot.reply_to(message, "❌ Empty."); return
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("✅ Send", callback_data=f"confirm_broadcast_{message.message_id}"),
        types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast")
    )
    bot.reply_to(message,
                 f"📢 Send to {len(active_users)} users?\n\n{content[:200] if content else '(media)'}",
                 reply_markup=markup)

def handle_confirm_broadcast(call):
    if call.from_user.id not in admin_ids:
        return
    bot.answer_callback_query(call.id, "🚀 Starting...")
    bot.edit_message_text("📢 Broadcasting...", call.message.chat.id, call.message.message_id)
    threading.Thread(target=execute_broadcast,
                     args=(call.message.reply_to_message, call.message.chat.id),
                     daemon=True).start()

def execute_broadcast(original_msg, admin_chat_id):
    sent = 0; failed = 0
    for uid in list(active_users):
        try:
            if original_msg.text:
                bot.send_message(uid, original_msg.text)
            elif original_msg.photo:
                bot.send_photo(uid, original_msg.photo[-1].file_id, caption=original_msg.caption)
            sent += 1
            time.sleep(0.05)
        except:
            failed += 1
    try:
        bot.send_message(admin_chat_id, f"📢 Done!\n✅ Sent: {sent}\n❌ Failed: {failed}")
    except: pass

def handle_cancel_broadcast(call):
    bot.answer_callback_query(call.id, "Cancelled.")
    bot.delete_message(call.message.chat.id, call.message.message_id)

def admin_panel_callback(call):
    bot.answer_callback_query(call.id)
    bot.edit_message_text("👑 Admin Panel:", call.message.chat.id,
                          call.message.message_id, reply_markup=create_admin_panel())

def add_admin_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "👑 Enter User ID to promote:")
    bot.register_next_step_handler(msg, process_add_admin_id)

def process_add_admin_id(message):
    if message.from_user.id != OWNER_ID: return
    try:
        new_id = int(message.text.strip())
        if new_id == OWNER_ID or new_id in admin_ids:
            bot.reply_to(message, "⚠️ Already admin."); return
        add_admin_db(new_id)
        bot.reply_to(message, f"✅ Admin added: `{new_id}`", parse_mode='Markdown')
    except:
        bot.reply_to(message, "❌ Invalid ID.")

def remove_admin_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "👑 Enter Admin ID to remove:")
    bot.register_next_step_handler(msg, process_remove_admin_id)

def process_remove_admin_id(message):
    if message.from_user.id != OWNER_ID: return
    try:
        rem_id = int(message.text.strip())
        if rem_id == OWNER_ID:
            bot.reply_to(message, "⚠️ Cannot remove Owner."); return
        if rem_id not in admin_ids:
            bot.reply_to(message, "⚠️ Not admin."); return
        remove_admin_db(rem_id)
        bot.reply_to(message, f"✅ Admin removed: `{rem_id}`", parse_mode='Markdown')
    except:
        bot.reply_to(message, "❌ Invalid ID.")

def list_admins_callback(call):
    bot.answer_callback_query(call.id)
    admins_str = "\n".join(f"- `{a}` {'(Owner)' if a == OWNER_ID else ''}"
                          for a in sorted(admin_ids))
    bot.edit_message_text(f"👑 Admins:\n\n{admins_str}",
                          call.message.chat.id, call.message.message_id,
                          reply_markup=create_admin_panel(), parse_mode='Markdown')

def add_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "💳 Enter User ID & days (e.g., `123 30`):")
    bot.register_next_step_handler(msg, process_add_subscription)

def process_add_subscription(message):
    if message.from_user.id not in admin_ids: return
    try:
        parts = message.text.split()
        uid = int(parts[0]); days = int(parts[1])
        current = user_subscriptions.get(uid, {}).get('expiry')
        start = datetime.now()
        if current and current > start: start = current
        new_expiry = start + timedelta(days=days)
        save_subscription(uid, new_expiry)
        bot.reply_to(message,
                     f"✅ Premium for `{uid}` added {days} days. Expires: {new_expiry:%Y-%m-%d}",
                     parse_mode='Markdown')
    except:
        bot.reply_to(message, "❌ Invalid format.")

def remove_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "💳 Enter User ID to remove:")
    bot.register_next_step_handler(msg, process_remove_subscription)

def process_remove_subscription(message):
    if message.from_user.id not in admin_ids: return
    try:
        uid = int(message.text.strip())
        remove_subscription_db(uid)
        bot.reply_to(message, f"✅ Removed: `{uid}`", parse_mode='Markdown')
    except:
        bot.reply_to(message, "❌ Invalid ID.")

def check_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "💳 Enter User ID to check:")
    bot.register_next_step_handler(msg, process_check_subscription)

def process_check_subscription(message):
    if message.from_user.id not in admin_ids: return
    try:
        uid = int(message.text.strip())
        if uid in user_subscriptions:
            exp = user_subscriptions[uid].get('expiry')
            if exp and exp > datetime.now():
                days = (exp - datetime.now()).days
                bot.reply_to(message, f"✅ `{uid}` Premium active. {days} days left.",
                             parse_mode='Markdown')
            else:
                bot.reply_to(message, f"⚠️ `{uid}` Expired.", parse_mode='Markdown')
                remove_subscription_db(uid)
        else:
            bot.reply_to(message, f"ℹ️ `{uid}` No subscription.", parse_mode='Markdown')
    except:
        bot.reply_to(message, "❌ Invalid ID.")

# ============================================================
# CLEANUP
# ============================================================
def cleanup():
    logger.warning("Shutdown. Saving state...")
    try:
        save_autorestart_state()
        logger.info("💾 State saved")
    except Exception as e:
        logger.error(f"Save state error: {e}")
    for key in list(bot_scripts.keys()):
        try:
            kill_process_tree(bot_scripts[key])
        except: pass
    logger.warning("Cleanup finished.")

atexit.register(cleanup)

# ============================================================
# MAIN
# ============================================================
if __name__ == '__main__':
    logger.info("="*60)
    logger.info("🤖 XHOST Bot Starting Up...")
    logger.info(f"🐍 Python: {sys.version.split()[0]}")
    logger.info(f"🔑 Owner: {OWNER_ID}")
    logger.info(f"🛡️ Admins: {admin_ids}")
    logger.info("="*60)

    keep_alive()

    logger.info("🔄 Checking for scripts to auto-restart...")
    threading.Thread(target=auto_restart_scripts, daemon=True, name="auto-restart").start()

    start_state_saver()

    logger.info("🚀 Starting polling...")
    while True:
        try:
            bot.infinity_polling(logger_level=logging.INFO, timeout=60, long_polling_timeout=30)
        except requests.exceptions.ReadTimeout:
            logger.warning("Polling ReadTimeout. Restarting in 5s...")
            time.sleep(5)
        except requests.exceptions.ConnectionError as ce:
            logger.error(f"ConnectionError: {ce}. Retrying in 15s...")
            time.sleep(15)
        except Exception as e:
            logger.critical(f"💥 Polling error: {e}", exc_info=True)
            time.sleep(30)
        finally:
            time.sleep(1)