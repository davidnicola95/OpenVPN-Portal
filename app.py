"""OpenVPN self-service portal. Keep secrets and PKI outside source control."""
import csv
import io
import logging
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import subprocess
from contextlib import contextmanager
from dotenv import load_dotenv, get_key, set_key
from flask import Flask, abort, flash, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE = Path(__file__).resolve().parent
ENV_FILE = Path(os.getenv('PORTAL_ENV_FILE', str(BASE / '.env')))
load_dotenv(ENV_FILE)
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY')
if not app.secret_key or len(app.secret_key) < 32:
    raise RuntimeError('Set FLASK_SECRET_KEY to a random value of at least 32 characters.')
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                  SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', 'true').lower() == 'true',
                  MAX_CONTENT_LENGTH=64 * 1024)
DATABASE = os.getenv('DATABASE_PATH', str(BASE / 'users.db'))
EASYRSA_DIR = os.getenv('EASYRSA_DIR', '/etc/openvpn/easy-rsa')
SCRIPTS_DIR = os.getenv('SCRIPTS_DIR', str(BASE / 'scripts'))
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', '')
BRAND_NAME = os.getenv('BRAND_NAME', 'VPN Portal')
VPN_PRIMARY_HOST = os.getenv('VPN_PRIMARY_HOST', 'vpn.example.com')
VPN_BACKUP_HOST = os.getenv('VPN_BACKUP_HOST', '')
VPN_PUBLIC_PORT = int(os.getenv('VPN_PUBLIC_PORT', '1194'))
MGMT_HOST = os.getenv('OPENVPN_MANAGEMENT_HOST', '127.0.0.1')
MGMT_PORT = int(os.getenv('OPENVPN_MANAGEMENT_PORT', '7505'))
NTFY_URL = os.getenv('NTFY_URL', '')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s:%(message)s')

@contextmanager
def database(timeout=5):
    conn = sqlite3.connect(DATABASE, timeout=timeout)
    try:
        with conn:
            yield conn
    finally:
        conn.close()

def init_db():
    with database() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL)')

def csrf_token():
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_urlsafe(32)
    return session['_csrf']

def same_secret(left, right):
    return secrets.compare_digest(left.encode('utf-8'), right.encode('utf-8'))

@app.context_processor
def template_context():
    return dict(brand_name=BRAND_NAME, csrf_token=csrf_token, vpn_primary=VPN_PRIMARY_HOST,
                vpn_backup=VPN_BACKUP_HOST, vpn_port=VPN_PUBLIC_PORT)

@app.before_request
def protect_forms():
    if request.method == 'POST':
        supplied, expected = request.form.get('csrf_token', ''), session.get('_csrf', '')
        if not expected or not same_secret(supplied, expected):
            return render_template('error.html', title='This form has expired',
                message='Reload the page and try again. Your changes were not submitted.'), 400
    if request.endpoint in ('dashboard', 'download') and 'username' in session:
        with database() as conn:
            exists = conn.execute('SELECT 1 FROM users WHERE username=?', (session['username'],)).fetchone()
        if not exists:
            session.clear()
            return redirect(url_for('login'))

@app.after_request
def response_headers(response):
    if request.endpoint != 'static':
        response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
    return response

def admin_password():
    return get_key(str(ENV_FILE), 'ADMIN_PASSWORD') or os.getenv('ADMIN_PASSWORD', '')

@app.route('/')
def index():
    return redirect(url_for('dashboard')) if 'username' in session else render_template('login.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        with database() as conn:
            row = conn.execute('SELECT password FROM users WHERE username=?', (username,)).fetchone()
        if row and check_password_hash(row[0], request.form.get('password', '')):
            session.clear(); session['username'] = username
            return redirect(url_for('dashboard'))
        return render_template('login.html', error='The username or password is incorrect.'), 401
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')
    username, password = request.form.get('username', '').strip(), request.form.get('password', '')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{2,63}', username):
        return render_template('register.html', error='Use 3–64 characters: letters, numbers, dots, hyphens or underscores. Start with a letter or number.'), 400
    if len(password) < 12:
        return render_template('register.html', error='Choose a password with at least 12 characters.'), 400
    if password != request.form.get('password2', ''):
        return render_template('register.html', error='The passwords do not match.'), 400
    try:
        with database(timeout=30) as conn:
            conn.execute('INSERT INTO users (username,password) VALUES (?,?)', (username, generate_password_hash(password)))
            subprocess.run([str(Path(SCRIPTS_DIR) / 'create_client.sh'), username], check=True,
                           timeout=120, capture_output=True)
    except sqlite3.IntegrityError:
        return render_template('register.html', error='That username is already taken.'), 409
    except (subprocess.SubprocessError, OSError):
        logging.exception('Client provisioning failed')
        return render_template('register.html', error='Your VPN profile could not be created. Please contact the administrator before trying again.'), 503
    if NTFY_URL:
        try:
            subprocess.run(['curl', '--fail', '--max-time', '8', '-d', f'New OpenVPN user registered: {username}', NTFY_URL],
                           check=True, timeout=10, capture_output=True)
        except (subprocess.SubprocessError, OSError):
            logging.warning('Registration notification failed')
    return render_template('register_success.html', username=username)

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('index'))
    return render_template('dashboard.html', username=session['username'])

def safe_common_name(value):
    return bool(value) and not any(c in value for c in '/\\\r\n\x00') and value not in ('.', '..')

def build_ovpn_file(username):
    if not safe_common_name(username):
        raise ValueError('Invalid certificate name')
    pki = Path(EASYRSA_DIR) / 'pki'
    ca = (pki / 'ca.crt').read_text()
    cert = (pki / 'issued' / f'{username}.crt').read_text()
    key = (pki / 'private' / f'{username}.key').read_text()
    remotes = f'remote {VPN_PRIMARY_HOST} {VPN_PUBLIC_PORT}\n'
    if VPN_BACKUP_HOST:
        remotes += f'remote {VPN_BACKUP_HOST} {VPN_PUBLIC_PORT}\n'
    return f'''client
dev tun
proto udp
{remotes}server-poll-timeout 10
remote-cert-tls server
resolv-retry infinite
nobind
persist-key
persist-tun
cipher AES-256-CBC
auth SHA256
verb 3

<ca>
{ca}
</ca>

<cert>
{cert}
</cert>

<key>
{key}
</key>
'''

@app.route('/download')
def download():
    if 'username' not in session:
        return redirect(url_for('index'))
    username = session['username']
    try:
        content = build_ovpn_file(username)
    except (OSError, ValueError):
        return render_template('dashboard.html', username=username,
                               error='Your VPN profile is unavailable. Please contact the administrator.'), 503
    return send_file(io.BytesIO(content.encode()), as_attachment=True,
                     download_name=f'{username}.ovpn', mimetype='application/x-openvpn-profile')

@app.route('/logout', methods=['GET', 'POST'])
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        expected = admin_password()
        if ADMIN_USERNAME and expected and same_secret(request.form.get('username', ''), ADMIN_USERNAME) and same_secret(request.form.get('password', ''), expected):
            session.clear(); session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        return render_template('admin_login.html', error='The admin username or password is incorrect.'), 401
    return render_template('admin_login.html')

@app.route('/admin/logout', methods=['GET', 'POST'])
def admin_logout():
    session.clear()
    return redirect(url_for('admin_login'))

def management_command(command):
    with socket.create_connection((MGMT_HOST, MGMT_PORT), timeout=3) as sock:
        sock.recv(1024)
        sock.sendall((command + '\n').encode())
        data = b''
        while len(data) < 1024 * 1024:
            part = sock.recv(4096)
            if not part:
                break
            data += part
            if command == 'status' and b'\nEND' in data:
                break
            if command != 'status' and b'\n' in data:
                break
        sock.sendall(b'quit\n')
    return data.decode(errors='replace')

def parse_vpn_status(data):
    clients, routes, section = [], {}, ''
    for fields in csv.reader(data.splitlines()):
        if not fields:
            continue
        if fields[0] in ('OpenVPN CLIENT LIST', 'ROUTING TABLE', 'GLOBAL STATS', 'END'):
            section = fields[0]; continue
        if section == 'OpenVPN CLIENT LIST' and len(fields) >= 5 and fields[0] not in ('Common Name', 'Updated'):
            clients.append(dict(common_name=fields[0], real_addr=fields[1], bytes_received=fields[2],
                                bytes_sent=fields[3], connected_since=fields[4]))
        elif section == 'ROUTING TABLE' and len(fields) >= 3 and fields[0] != 'Virtual Address':
            routes[(fields[1], fields[2])] = fields[0]
    for client in clients:
        client['virtual_addr'] = routes.get((client['common_name'], client['real_addr']), '—')
    return clients

def get_active_vpn_users():
    return parse_vpn_status(management_command('status'))

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    with database() as conn:
        users = conn.execute('SELECT id, username FROM users ORDER BY username COLLATE NOCASE').fetchall()
    available = True
    try:
        active = get_active_vpn_users()
    except (OSError, ValueError):
        logging.warning('OpenVPN management status unavailable')
        active, available = [], False
    return render_template('admin_dashboard.html', users=users, active_sessions=active, management_available=available)

@app.route('/admin/delete/<int:user_id>', methods=['POST'])
def admin_delete_user(user_id):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    with database() as conn:
        row = conn.execute('SELECT username FROM users WHERE id=?', (user_id,)).fetchone()
        if not row:
            abort(404)
        try:
            if not safe_common_name(row[0]):
                raise ValueError('Invalid certificate name')
            subprocess.run([str(Path(SCRIPTS_DIR) / 'revoke_client.sh'), row[0]], check=True,
                           capture_output=True, timeout=120)
        except (subprocess.SubprocessError, OSError, ValueError):
            flash('Certificate revocation could not be confirmed. The account has been retained for review.', 'error')
            return redirect(url_for('admin_dashboard'))
        conn.execute('DELETE FROM users WHERE id=?', (user_id,))
    flash(f'Access revoked and account removed for {row[0]}.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/kill/<common_name>', methods=['POST'])
def admin_kill_connection(common_name):
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    if not safe_common_name(common_name):
        abort(400)
    try:
        result = management_command(f'kill {common_name}')
        if 'SUCCESS:' not in result:
            raise ValueError('Disconnect not confirmed')
        flash(f'Disconnected {common_name}. Their certificate remains valid.', 'success')
    except (OSError, ValueError):
        flash('The disconnect could not be confirmed. Refresh the sessions and try again.', 'error')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/change_password', methods=['POST'])
def admin_change_password():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    value = request.form.get('new_password', '')
    if not same_secret(request.form.get('current_password', ''), admin_password()):
        flash('Your current admin password is incorrect.', 'error')
    elif len(value) < 12 or '\n' in value or '\r' in value:
        flash('Use at least 12 characters without line breaks.', 'error')
    elif value != request.form.get('confirm_password', ''):
        flash('The new passwords do not match.', 'error')
    else:
        try:
            set_key(str(ENV_FILE), 'ADMIN_PASSWORD', value, quote_mode='always')
            ENV_FILE.chmod(0o600)
            os.environ['ADMIN_PASSWORD'] = value
            flash('Admin password updated.', 'success')
        except OSError:
            logging.exception('Admin password update failed')
            flash('The password could not be saved. Please try again or check file permissions.', 'error')
    return redirect(url_for('admin_dashboard'))

@app.errorhandler(404)
def missing_page(_error):
    return render_template('error.html', title='Page not found', message='This page is unavailable. Return to the portal to continue.'), 404

if __name__ == '__main__':
    init_db()
    app.run(host=os.getenv('LISTEN_HOST', '0.0.0.0'), port=int(os.getenv('PORT', '5000')), debug=False)
