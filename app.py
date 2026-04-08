import sqlite3, os, uuid, hashlib, functools, random, threading
from datetime import datetime, date, timedelta
from flask import (Flask, render_template, redirect, url_for, flash,
                   request, send_from_directory, jsonify, session, abort, g)
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer

# PostgreSQL support
DATABASE_URL = os.environ.get('DATABASE_URL')
USE_PG = bool(DATABASE_URL)
if USE_PG:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
    # Fix Render/Supabase URLs that start with postgres:// instead of postgresql://
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

    if "sslmode=" not in DATABASE_URL:
        DATABASE_URL += ("&" if "?" in DATABASE_URL else "?") + "sslmode=require"

    # Pool is created lazily — NOT opened at import time to avoid Gunicorn
    # worker fork issues and cold-start 502 errors.
    pg_pool = ConnectionPool(
        DATABASE_URL,
        min_size=1,
        max_size=3,
        kwargs={"row_factory": dict_row, "autocommit": False, "connect_timeout": 30},
        open=False,          # Do NOT open at module load time
        reconnect_timeout=30,
        max_waiting=8,
        timeout=30,
    )
    print(" PostgreSQL connection pool created (not yet opened)")
else:
    pg_pool = None

# Thread-safe pool/DB initialisation gate
_pool_lock = threading.Lock()
_pool_opened = False

def _ensure_pool_open():
    """Open the connection pool exactly once, thread-safely."""
    global _pool_opened
    if _pool_opened:
        return
    with _pool_lock:
        if _pool_opened:
            return
        try:
            pg_pool.open(wait=True, timeout=45)
            _pool_opened = True
            print(" PostgreSQL pool opened successfully")
        except Exception as e:
            print(f" Pool open failed: {e} — will retry on next request")

# Supabase Storage Support
# IMPORTANT: Use the service_role key (not anon key) for server-side operations.
# The service_role key bypasses Row Level Security (RLS), which is required
# for backend uploads. The anon key causes 403 "violates row-level security policy".
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')  # service_role key — bypasses RLS
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')                  # anon key — fallback only
_supabase_key_to_use = SUPABASE_SERVICE_KEY or SUPABASE_KEY
if SUPABASE_URL and _supabase_key_to_use:
    try:
        from supabase import create_client
        supabase = create_client(SUPABASE_URL, _supabase_key_to_use)
        key_type = "service_role" if SUPABASE_SERVICE_KEY else "anon (⚠️ RLS may block uploads)"
        print(f" Supabase client initialized with {key_type} key")
    except Exception as e:
        print(f" Supabase init error: {e}")
        supabase = None
else:
    supabase = None

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'campusnotes-super-secret-2025-prod')
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
AVATAR_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads', 'avatars')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024
DB_PATH = os.path.join(os.path.dirname(__file__), 'campusnotes.db')
ALLOWED_EXT = {'pdf','doc','docx','ppt','pptx','png','jpg','jpeg'}
ALLOWED_AVATAR_EXT = {'png','jpg','jpeg','gif','webp'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AVATAR_FOLDER, exist_ok=True)

# --- Email Configuration (Brevo SMTP via Port 2525) ---
app.config.update(
    MAIL_SERVER='smtp-relay.brevo.com',
    MAIL_PORT=2525,  # Bypasses Render's firewall
    MAIL_USE_TLS=True,
    MAIL_USE_SSL=False,
    MAIL_USERNAME=os.environ.get('MAIL_USERNAME'),
    MAIL_PASSWORD=os.environ.get('MAIL_PASSWORD'),
    MAIL_DEFAULT_SENDER=os.environ.get('MAIL_DEFAULT_SENDER', os.environ.get('MAIL_USERNAME'))
)

mail = Mail(app)
ts = URLSafeTimedSerializer(app.secret_key)

# Debug: Check if variables are set on Render
if os.environ.get('RENDER'):
    user = os.environ.get('MAIL_USERNAME')
    pw = os.environ.get('MAIL_PASSWORD')
    print(f"DEBUG: MAIL_USERNAME is {'SET' if user else 'MISSING'}")
    print(f"DEBUG: MAIL_PASSWORD is {'SET' if pw else 'MISSING'}")
    if pw and ' ' in pw:
        print("DEBUG WARNING: MAIL_PASSWORD contains spaces. Please remove spaces in Render Dashboard.")

# --- Session & Security Config ---
import threading
import requests

def send_async_email(app, subject, recipient, body, html):
    with app.app_context():
        try:
            api_key = os.environ.get('MAIL_PASSWORD')
            sender_email = os.environ.get('MAIL_USERNAME')
            
            if not api_key or not sender_email:
                print("Mail error: Missing MAIL_PASSWORD or MAIL_USERNAME")
                return
                
            url = "https://api.brevo.com/v3/smtp/email"
            headers = {
                "accept": "application/json",
                "api-key": api_key,
                "content-type": "application/json"
            }
            payload = {
                "sender": {"email": sender_email},
                "to": [{"email": recipient}],
                "subject": subject,
                "htmlContent": html,
                "textContent": body
            }
            
            response = requests.post(url, json=payload, headers=headers)
            print(f"Brevo API Send Status: {response.status_code}")
            if response.status_code not in [201, 200]:
                print(f"Brevo API error: {response.text}")
            else:
                print("Background mail sent successfully via API!")
        except Exception as e:
            print(f"Background mail exception: {e}")

@app.route('/privacy')
def privacy(): return render_template('legal/privacy.html')

@app.route('/terms')
def terms(): return render_template('legal/terms.html')

@app.route('/help')
def help_page():
    return render_template('legal/help.html')

@app.route('/contact-us', methods=['GET', 'POST'])
def helpdesk_contact():
    if request.method == 'POST':
        # ... logic ...
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        subject = request.form.get('subject', '').strip()
        message = request.form.get('message', '').strip()
        
        if not all([name, email, subject, message]):
            flash('Please fill out all fields.', 'error')
            return render_template('legal/support.html')
            
        admin_email = os.environ.get('ADMIN_EMAIL', 'support4campusnotes@gmail.com')
        support_subject = f"Support Request: {subject}"
        support_body = f"New help request from {name} ({email}):\n\nSubject: {subject}\n\nMessage:\n{message}"
        support_html = f"""
        <div style="font-family: 'Inter', Arial, sans-serif; max-width: 600px; padding: 20px; color: #333; background-color: #f9fafb; border-radius: 12px; margin: 0 auto; border: 1px solid #e5e7eb;">
            <div style="text-align: center; padding: 25px 0;">
                <img src="https://campusnotes-8crf.onrender.com/static/img/logo.png" alt="CampusNotes" style="height: 45px; width: auto; display: block; margin: 0 auto;">
            </div>
            <div style="background-color: #ffffff; padding: 30px; border-radius: 10px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -1px rgba(0,0,0,0.06); border: 1px solid #f3f4f6;">
                <h2 style="color: #4f46e5; margin-top: 0; font-size: 20px; font-weight: 700; border-bottom: 2px solid #f3f4f6; padding-bottom: 12px; margin-bottom: 20px;">New Support Request</h2>
                <div style="margin-bottom: 15px;">
                    <p style="margin: 0; font-size: 14px; color: #6b7280; text-transform: uppercase; font-weight: 600; letter-spacing: 0.05em;">From</p>
                    <p style="margin: 4px 0 0 0; font-size: 16px; font-weight: 500;">{name} (<a href="mailto:{email}" style="color: #4f46e5; text-decoration: none;">{email}</a>)</p>
                </div>
                <div style="margin-bottom: 20px;">
                    <p style="margin: 0; font-size: 14px; color: #6b7280; text-transform: uppercase; font-weight: 600; letter-spacing: 0.05em;">Subject</p>
                    <p style="margin: 4px 0 0 0; font-size: 16px; font-weight: 600; color: #111827;">{subject}</p>
                </div>
                <div style="margin-top: 25px; padding: 20px; background: #f8fafc; border-left: 4px solid #4f46e5; border-radius: 6px;">
                    <p style="white-space: pre-wrap; margin: 0; line-height: 1.6; color: #374151; font-size: 15px;">{message}</p>
                </div>
            </div>
            <div style="text-align: center; font-size: 13px; color: #9ca3af; margin-top: 25px;">
                <p style="margin: 0;">&copy; 2025 CampusNotes · Digital Education for All</p>
                <p style="margin: 8px 0 0 0;"><a href="https://campusnotes-8crf.onrender.com" style="color: #4f46e5; text-decoration: none; font-weight: 500;">Visit CampusNotes →</a></p>
            </div>
        </div>
        """
        # Send email to the site administrator
        threading.Thread(target=send_async_email, args=(app, support_subject, admin_email, support_body, support_html)).start()
        
        flash('Your message has been sent! We will get back to you soon.', 'success')
        return redirect(url_for('helpdesk_contact'))
        
    return render_template('legal/support.html')

def send_verification_email(email):
    """Generate token and send verification email using Brevo API."""
    try:
        token = ts.dumps(email, salt='email-confirm')
        confirm_url = url_for('verify_email', token=token, _external=True)
        
        subject = 'Verify Your CampusNotes Account'
        body = f'Welcome to CampusNotes! Please verify your account by clicking the link: {confirm_url}'
        html = render_template('auth/verify_email_msg.html', confirm_url=confirm_url)
        
        threading.Thread(target=send_async_email, args=(app, subject, email, body, html)).start()
        return True
    except Exception as e:
        print(f"Mail prep error: {e}")
        return False

def send_reset_email(email):
    """Generate token and send password reset email using Brevo API."""
    try:
        token = ts.dumps(email, salt='password-reset')
        reset_url = url_for('reset_password_with_token', token=token, _external=True)
        
        subject = 'Reset Your CampusNotes Password'
        body = f'Click the link to reset your CampusNotes password: {reset_url}'
        html = render_template('auth/reset_password_msg.html', reset_url=reset_url)
        
        threading.Thread(target=send_async_email, args=(app, subject, email, body, html)).start()
        return True
    except Exception as e:
        print(f"Mail prep error: {e}")
        return False

IS_PROD = os.environ.get('RENDER') is not None
app.config.update(
    SESSION_COOKIE_SECURE=IS_PROD,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(days=7)
)

BADGE_TYPES = {
    'first_upload': {'name': 'First Note', 'icon': '📝', 'desc': 'Uploaded your first note'},
    '10_uploads': {'name': '10 Notes', 'icon': '📚', 'desc': 'Uploaded 10 notes'},
    '100_downloads': {'name': '100 Downloads', 'icon': '💯', 'desc': 'Notes downloaded 100 times'},
    '500_downloads': {'name': '500 Downloads', 'icon': '🏅', 'desc': 'Notes downloaded 500 times'},
    'top_rated': {'name': 'Top Rated', 'icon': '⭐', 'desc': 'Average rating above 4.5'},
    'verified': {'name': 'Verified', 'icon': '✅', 'desc': 'Verified contributor'},
}
EXAM_MONTHS = {4, 5, 11, 12}
BRANCHES = ['CSE','IT','ECE','Civil','Mechanical','EEE','Chemical','BCA','BBA','BSC-Biotech','BSC-Nursing','ANM','GNM','DIPLOMA','PGDM','MBA','MCA','Other']
SEMESTERS = list(range(1,9))
NOTE_TYPES = ['PDF','PPT','Handwritten','PYQs','Assignments','Lab Manual']
DIFFICULTY = ['Beginner','Intermediate','Exam-Oriented','Advanced']
AVATAR_COLORS = ['#4f46e5','#0891b2','#059669','#d97706','#dc2626','#7c3aed','#db2777','#0284c7']
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AVATAR_FOLDER, exist_ok=True)
ALLOWED_AVATAR_EXT = {'png','jpg','jpeg','gif','webp'}

# ─── DB Compatibility Layer ─────────────────────────────────────────
class PgDictRow(dict):
    """Dict row that also supports integer indexing like sqlite3.Row."""
    def __init__(self, data):
        super().__init__(data)
        self._values = list(data.values())
    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)

class PgCursorWrapper:
    """Wraps psycopg3 cursor to behave like sqlite3: ? placeholders, dict rows."""
    def __init__(self, cursor):
        self._cur = cursor
    def execute(self, sql, params=None):
        sql = sql.replace('?', '%s')
        # Translate SQLite functions to PostgreSQL
        sql = sql.replace("datetime('now')", "NOW()")
        sql = sql.replace("date(uploaded_at)", "uploaded_at::date")
        sql = sql.replace("date(downloaded_at)", "downloaded_at::date")
        sql = sql.replace("date(created_at)", "created_at::date")
        # Case-insensitive LIKE for PostgreSQL
        sql = sql.replace(' LIKE ', ' ILIKE ')
        # Translate SQLite INSERT OR to PostgreSQL ON CONFLICT
        sql_upper = sql.upper().strip()
        if sql_upper.startswith('INSERT') and 'OR IGNORE' in sql_upper:
            sql = sql.replace('OR IGNORE ', '').replace('or ignore ', '')
            sql = sql.rstrip() + ' ON CONFLICT DO NOTHING'
        elif sql_upper.startswith('INSERT') and 'OR REPLACE' in sql_upper:
            sql = sql.replace('OR REPLACE ', '').replace('or replace ', '')
            if 'ratings' in sql.lower():
                sql = sql.rstrip() + ' ON CONFLICT (user_id, note_id) DO UPDATE SET value = EXCLUDED.value'
            else:
                sql = sql.rstrip() + ' ON CONFLICT DO NOTHING'
        self._cur.execute(sql, params or ())
        return self
    def fetchone(self):
        row = self._cur.fetchone()
        return PgDictRow(row) if row else None
    def fetchall(self):
        rows = self._cur.fetchall()
        return [PgDictRow(r) for r in rows]
    @property
    def lastrowid(self):
        try:
            self._cur.execute("SELECT lastval()")
            return self._cur.fetchone()['lastval']
        except:
            return None
    @property
    def description(self):
        return self._cur.description

class PgConnectionWrapper:
    """Wraps psycopg3 connection to match sqlite3 interface."""
    def __init__(self, conn):
        self._conn = conn
    def execute(self, sql, params=None):
        cur = self._conn.cursor(row_factory=dict_row)
        wrapper = PgCursorWrapper(cur)
        wrapper.execute(sql, params)
        return wrapper
    def executescript(self, sql):
        # Split by semicolons and execute each statement
        cur = self._conn.cursor()
        stmts = [s.strip() for s in sql.split(';') if s.strip()]
        for stmt in stmts:
            try:
                cur.execute(stmt)
            except Exception:
                pass
        self._conn.commit()
    def commit(self):
        self._conn.commit()
    def close(self):
        self._conn.close()

def hp(p): return hashlib.sha256(p.encode()).hexdigest()

# ─── DB ─────────────────────────────────────────────────────────────
def get_db():
    if 'db' not in g:
        if USE_PG:
            _ensure_pool_open()
            try:
                conn = pg_pool.getconn(timeout=30)
                g._is_pool_conn = True
            except Exception as e:
                print(f"Pool getconn error: {e} — falling back to direct connection")
                conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=30)
                g._is_pool_conn = False
            g.db = PgConnectionWrapper(conn)
            g._pg_conn = conn
        else:
            g.db = sqlite3.connect(DB_PATH)
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    pg_conn = g.pop('_pg_conn', None)
    is_pool_conn = g.pop('_is_pool_conn', False)
    if pg_conn and pg_pool and is_pool_conn:
        try:
            pg_pool.putconn(pg_conn)  # Return to pool for reuse
        except Exception:
            try: pg_conn.close()
            except: pass
    elif pg_conn:
        try: pg_conn.close()
        except: pass
    elif db:
        db.close()

def init_db():
    if USE_PG:
        conn = psycopg.connect(DATABASE_URL, autocommit=True, connect_timeout=30)
        db = PgConnectionWrapper(conn)
        db.execute("""
        CREATE TABLE IF NOT EXISTS file_blobs(
            filename TEXT PRIMARY KEY,
            data BYTEA)
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id SERIAL PRIMARY KEY, name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'student', status TEXT DEFAULT 'active',
            college TEXT, branch TEXT, semester INTEGER, bio TEXT,
            avatar_color TEXT DEFAULT '#4f46e5', profile_picture TEXT,
            is_verified INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS notes(
            id SERIAL PRIMARY KEY, title TEXT NOT NULL,
            subject TEXT NOT NULL, branch TEXT NOT NULL, semester INTEGER NOT NULL,
            note_type TEXT NOT NULL, difficulty TEXT NOT NULL,
            description TEXT, tags TEXT, college TEXT, file_path TEXT NOT NULL,
            file_name TEXT, file_size INTEGER, file_ext TEXT,
            uploaded_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            downloads INTEGER DEFAULT 0, views INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending', reject_reason TEXT,
            featured INTEGER DEFAULT 0,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, approved_at TIMESTAMP)
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS saved_notes(
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id,note_id))
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS download_history(
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS notifications(
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            message TEXT NOT NULL, type TEXT DEFAULT 'info',
            is_read INTEGER DEFAULT 0, link TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS ratings(
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            value INTEGER NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id,note_id))
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS comments(
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            content TEXT NOT NULL, is_deleted INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS reports(
            id SERIAL PRIMARY KEY,
            reporter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            reason TEXT NOT NULL, status TEXT DEFAULT 'open',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS follows(
            id SERIAL PRIMARY KEY,
            follower_id INTEGER NOT NULL REFERENCES users(id),
            following_id INTEGER NOT NULL REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(follower_id, following_id))
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS badges(
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            badge_type TEXT NOT NULL,
            earned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, badge_type))
        """)
        db.execute("""
        CREATE TABLE IF NOT EXISTS note_requests(
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id),
            subject TEXT NOT NULL, branch TEXT, semester INTEGER,
            description TEXT, status TEXT DEFAULT 'open',
            fulfilled_by INTEGER REFERENCES notes(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
        """)
        admin_email = os.environ.get('ADMIN_EMAIL', 'support4campusnotes@gmail.com')
        admin_pass = os.environ.get('ADMIN_PASSWORD', 'CampusNotesAdmin@2025!Strong')
        if not db.execute("SELECT 1 FROM users WHERE email=%s", (admin_email,)).fetchone():
            db.execute("INSERT INTO users(name,email,password_hash,role,avatar_color) VALUES(%s,%s,%s,%s,%s)",
                       ('Admin', admin_email, hp(admin_pass), 'admin', '#dc2626'))
            print("\n" + "="*50)
            print(" DEFAULT ADMIN ACCOUNT CREATED")
            print(f" Email: {admin_email}")
            print(f" Password: {admin_pass}")
            print("="*50 + "\n")

        db.close()
    else:
        db = sqlite3.connect(DB_PATH)
        db.executescript("""
        CREATE TABLE IF NOT EXISTS file_blobs(
            filename TEXT PRIMARY KEY,
            data BLOB);
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'student', status TEXT DEFAULT 'active',
            college TEXT, branch TEXT, semester INTEGER, bio TEXT,
            avatar_color TEXT DEFAULT '#4f46e5', profile_picture TEXT,
            is_verified INTEGER DEFAULT 0,
            created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS notes(
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            subject TEXT NOT NULL, branch TEXT NOT NULL, semester INTEGER NOT NULL,
            note_type TEXT NOT NULL, difficulty TEXT NOT NULL,
            description TEXT, tags TEXT, college TEXT, file_path TEXT NOT NULL,
            file_name TEXT, file_size INTEGER, file_ext TEXT,
            uploaded_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            downloads INTEGER DEFAULT 0, views INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending', reject_reason TEXT,
            featured INTEGER DEFAULT 0,
            uploaded_at TEXT DEFAULT(datetime('now')), approved_at TEXT);
        CREATE TABLE IF NOT EXISTS saved_notes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            saved_at TEXT DEFAULT(datetime('now')), UNIQUE(user_id,note_id));
        CREATE TABLE IF NOT EXISTS download_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            downloaded_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS notifications(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            message TEXT NOT NULL, type TEXT DEFAULT 'info',
            is_read INTEGER DEFAULT 0, link TEXT,
            created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS ratings(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            value INTEGER NOT NULL, created_at TEXT DEFAULT(datetime('now')),
            UNIQUE(user_id,note_id));
        CREATE TABLE IF NOT EXISTS comments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            content TEXT NOT NULL, is_deleted INTEGER DEFAULT 0,
            created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS reports(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reporter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            reason TEXT NOT NULL, status TEXT DEFAULT 'open',
            created_at TEXT DEFAULT(datetime('now')));
        CREATE TABLE IF NOT EXISTS follows(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            follower_id INTEGER NOT NULL REFERENCES users(id),
            following_id INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT DEFAULT(datetime('now')),
            UNIQUE(follower_id, following_id));
        CREATE TABLE IF NOT EXISTS badges(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            badge_type TEXT NOT NULL,
            earned_at TEXT DEFAULT(datetime('now')),
            UNIQUE(user_id, badge_type));
        CREATE TABLE IF NOT EXISTS note_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            subject TEXT NOT NULL, branch TEXT, semester INTEGER,
            description TEXT, status TEXT DEFAULT 'open',
            fulfilled_by INTEGER REFERENCES notes(id),
            created_at TEXT DEFAULT(datetime('now')));
        """)
        admin_email = os.environ.get('ADMIN_EMAIL', 'support4campusnotes@gmail.com')
        admin_pass = os.environ.get('ADMIN_PASSWORD', 'CampusNotesAdmin@2025!Strong')
        # Migrations for existing DBs
        for col, sql in [('profile_picture', 'ALTER TABLE users ADD COLUMN profile_picture TEXT'),
                         ('is_verified', 'ALTER TABLE users ADD COLUMN is_verified INTEGER DEFAULT 0'),
                          ('file_blobs', 'CREATE TABLE IF NOT EXISTS file_blobs(filename TEXT PRIMARY KEY, data BLOB)')]:
            try: db.execute(sql)
            except: pass
        db.execute("UPDATE users SET is_verified = 1 WHERE role = 'admin'")
        db.commit()
        if not db.execute("SELECT 1 FROM users WHERE email=?", (admin_email,)).fetchone():
            db.execute("INSERT INTO users(name,email,password_hash,role,avatar_color,is_verified) VALUES(?,?,?,?,?,?)",
                       ('Admin', admin_email, hp(admin_pass), 'admin', '#dc2626', 1))
            print("\n" + "="*50)
            print(" DEFAULT ADMIN ACCOUNT CREATED")
            print(f" Email: {admin_email}")
            print(f" Password: {admin_pass}")
            print("="*50 + "\n")
        db.commit(); db.close()
    print(f" DB ready ({('PostgreSQL' if USE_PG else 'SQLite')})")


# ─── AUTH ────────────────────────────────────────────────────────────
def cur_user():
    """Fetch current user once per request; cached in Flask g."""
    if 'cur_user_cache' not in g:
        uid = session.get('user_id')
        if uid:
            try:
                g.cur_user_cache = get_db().execute(
                    "SELECT * FROM users WHERE id=?", (uid,)
                ).fetchone()
            except Exception:
                g.cur_user_cache = None
        else:
            g.cur_user_cache = None
    return g.cur_user_cache

def login_req(f):
    @functools.wraps(f)
    def dec(*a,**k):
        if not session.get('user_id'):
            flash('Please log in.','warning'); return redirect(url_for('login',next=request.url))
        u = cur_user()
        if u and u['status']=='blocked':
            session.clear(); flash('Account blocked.','error'); return redirect(url_for('login'))
        if u and u['is_verified'] == 0 and u['role'] != 'admin':
            session.clear(); flash('Please verify your email to continue.','warning'); return redirect(url_for('login'))
        return f(*a,**k)
    return dec

def admin_req(f):
    @functools.wraps(f)
    def dec(*a,**k):
        u = cur_user()
        if not u or u['role']!='admin':
            flash('Admin required.','error'); return redirect(url_for('login'))
        return f(*a,**k)
    return dec

def allowed(fn): return '.' in fn and fn.rsplit('.',1)[1].lower() in ALLOWED_EXT

@app.context_processor
def inject():
    try:
        u = cur_user()  # Uses g cache — no extra DB hit
        unread = 0; nav_notifs = []
        if u:
            db = get_db()
            # Single query: get notifications and count unread in one go
            nav_notifs = db.execute(
                "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 8",
                (u['id'],)
            ).fetchall()
            unread = sum(1 for n in nav_notifs if not n['is_read'])
        is_auth = u is not None
        is_admin = bool(u and u['role'] == 'admin')
        user_initials = ''
        if u and u['name']:
            parts = u['name'].split()
            user_initials = ''.join(p[0].upper() for p in parts[:2] if p)

        def get_avatar_url(pp):
            if not pp: return ''
            if pp.startswith('data:'): return pp
            return url_for('serve_avatar', filename=pp)

        return dict(current_user=u, unread_notifs=unread, nav_notifs=nav_notifs,
                    is_auth=is_auth, is_admin=is_admin, user_initials=user_initials,
                    is_exam_season=datetime.now().month in EXAM_MONTHS,
                    get_avatar_url=get_avatar_url,
                    badge_types=BADGE_TYPES,
                    config={'BRANCHES':BRANCHES,'SEMESTERS':SEMESTERS,'NOTE_TYPES':NOTE_TYPES,'DIFFICULTY':DIFFICULTY})
    except Exception as e:
        print(f"inject() error: {e}")
        return dict(current_user=None, unread_notifs=0, nav_notifs=[],
                    is_auth=False, is_admin=False, user_initials='',
                    is_exam_season=False, badge_types=BADGE_TYPES, config={}, get_avatar_url=lambda pp: '')

@app.template_filter('initials')
def tpl_initials(n):
    if not n: return ''
    parts = n.split()
    return ''.join(p[0].upper() for p in parts[:2] if p)

@app.template_filter('file_size_str')
def tpl_fsz(sz):
    if not sz: return 'Unknown'
    if sz<1024: return f'{sz} B'
    if sz<1048576: return f'{sz//1024} KB'
    return f'{sz/1048576:.1f} MB'

@app.template_filter('fmt_date')
def tpl_date(s):
    if not s: return ''
    try:
        if isinstance(s, datetime): return s.strftime('%b %d, %Y')
        return datetime.fromisoformat(str(s)).strftime('%b %d, %Y')
    except: return str(s)[:10]

@app.template_filter('fmt_short')
def tpl_short(s):
    if not s: return ''
    try:
        if isinstance(s, datetime): return s.strftime('%b %d')
        return datetime.fromisoformat(str(s)).strftime('%b %d')
    except: return str(s)[:10]

@app.template_filter('fmt_datetime')
def tpl_dt(s):
    if not s: return ''
    try:
        if isinstance(s, datetime): return s.strftime('%b %d, %Y %H:%M')
        return datetime.fromisoformat(str(s)).strftime('%b %d, %Y %H:%M')
    except: return str(s)[:16]

@app.template_filter('compact_num')
def tpl_compact(n):
    try: n = int(n)
    except: return str(n)
    if n >= 1000000: return f'{n/1000000:.1f}M'
    if n >= 1000: return f'{n/1000:.1f}K'
    return str(n)

def get_uploaders(db, notes_list):
    """Batch-fetch uploaders in a single query instead of N+1 queries."""
    up = {}
    uids = list({n['uploaded_by'] for n in notes_list})
    if not uids: return up
    if USE_PG:
        placeholders = ','.join(['%s'] * len(uids))
    else:
        placeholders = ','.join(['?'] * len(uids))
    rows = db.execute(f"SELECT * FROM users WHERE id IN ({placeholders})", tuple(uids)).fetchall()
    for r in rows:
        up[r['id']] = r
    return up

def check_badges(db, uid):
    """Auto-grant badges based on user activity."""
    existing = {b['badge_type'] for b in db.execute("SELECT badge_type FROM badges WHERE user_id=?",(uid,)).fetchall()}
    note_count = db.execute("SELECT COUNT(*) FROM notes WHERE uploaded_by=? AND status='approved'",(uid,)).fetchone()[0]
    total_dl = db.execute("SELECT COALESCE(SUM(downloads),0) FROM notes WHERE uploaded_by=?",(uid,)).fetchone()[0]
    ratings = db.execute("SELECT AVG(r.value) as avg_r FROM ratings r JOIN notes n ON r.note_id=n.id WHERE n.uploaded_by=?",(uid,)).fetchone()
    avg_rating = ratings['avg_r'] or 0
    new_badges = []
    if note_count >= 1 and 'first_upload' not in existing: new_badges.append('first_upload')
    if note_count >= 10 and '10_uploads' not in existing: new_badges.append('10_uploads')
    if total_dl >= 100 and '100_downloads' not in existing: new_badges.append('100_downloads')
    if total_dl >= 500 and '500_downloads' not in existing: new_badges.append('500_downloads')
    if avg_rating >= 4.5 and note_count >= 3 and 'top_rated' not in existing: new_badges.append('top_rated')
    for b in new_badges:
        try:
            db.execute("INSERT OR IGNORE INTO badges(user_id,badge_type) VALUES(?,?)",(uid,b))
            db.execute("INSERT INTO notifications(user_id,message,type) VALUES(?,?,?)",
                       (uid,f'You earned the {BADGE_TYPES[b]["icon"]} {BADGE_TYPES[b]["name"]} badge!','success'))
        except: pass
    if new_badges: db.commit()

# ─── GOOGLE VERIFICATION ──────────────────────────────────────────────
@app.route('/google861a1c11c5e551c2.html')
def google_verify():
    return send_from_directory(os.path.dirname(__file__), 'google861a1c11c5e551c2.html')

# ─── INDEX ──────────────────────────────────────────────────────────
@app.route('/')
def index():
    db=get_db(); u=cur_user(); uid=u['id'] if u else None
    note_sql = """
        SELECT n.*, u.name as uploader_name, u.profile_picture as uploader_pic, 
               u.avatar_color as uploader_color, u.is_verified as uploader_verified 
        FROM notes n 
        JOIN users u ON n.uploaded_by = u.id 
        WHERE n.status='approved'
    """
    featured = db.execute(f"{note_sql} AND n.featured=1 ORDER BY n.uploaded_at DESC LIMIT 6").fetchall()
    recent = db.execute(f"{note_sql} ORDER BY n.uploaded_at DESC LIMIT 8").fetchall()
    popular = db.execute(f"{note_sql} AND n.downloads > 0 ORDER BY n.downloads DESC LIMIT 10").fetchall()
    # Combined stats query — 1 query instead of 3
    stats_row = db.execute("SELECT COUNT(*) as nc, COALESCE(SUM(downloads),0) as dl FROM notes WHERE status='approved'").fetchone()
    user_count = db.execute("SELECT COUNT(*) FROM users WHERE role='student'").fetchone()[0]
    stats={'notes': stats_row['nc'], 'users': user_count, 'downloads': stats_row['dl']}
    saved_ids={r['note_id'] for r in db.execute("SELECT note_id FROM saved_notes WHERE user_id=?",(uid,)).fetchall()} if uid else set()
    # Personalized recommendations
    recommended=[]
    if u and u['branch'] and u['semester']:
        downloaded_ids = {r['note_id'] for r in db.execute("SELECT note_id FROM download_history WHERE user_id=?",(uid,)).fetchall()}
        rec = db.execute(f"{note_sql} AND (n.branch=? OR n.semester=?) ORDER BY n.downloads DESC LIMIT 8",
                         (u['branch'], u['semester'])).fetchall()
        recommended = [n for n in rec if n['id'] not in downloaded_ids][:6]
    # Exam season notes
    exam_notes=[]
    if datetime.now().month in EXAM_MONTHS:
        exam_notes=db.execute(f"{note_sql} AND (n.note_type='PYQs' OR n.difficulty='Exam-Oriented') ORDER BY n.downloads DESC LIMIT 6").fetchall()
    uploaders=get_uploaders(db, list(featured)+list(recent)+list(popular)+recommended+exam_notes)
    return render_template('notes/index.html',featured=featured,recent=recent,popular=popular,
                           stats=stats,saved_ids=saved_ids,uploaders=uploaders,
                           recommended=recommended,exam_notes=exam_notes)

# ─── BROWSE ─────────────────────────────────────────────────────────
@app.route('/browse')
def browse():
    db=get_db(); u=cur_user(); uid=u['id'] if u else None
    q=request.args.get('q','').strip()
    branch=request.args.get('branch','')
    semester=request.args.get('semester','')
    note_type=request.args.get('note_type','')
    difficulty=request.args.get('difficulty','')
    sort=request.args.get('sort','latest')
    page=max(1,request.args.get('page',1,type=int)); pp=12
    # Build WHERE conditions using table-qualified column names for JOIN compatibility
    j_where = ["n.status='approved'"]
    params = []
    if q:
        q = q.strip()
        parts = [p for p in q.split() if p]
        if parts:
            q_clauses = []
            for p in parts:
                q_clauses.append("(n.title LIKE ? OR n.subject LIKE ? OR n.tags LIKE ? OR n.description LIKE ? OR n.college LIKE ?)")
                like = f'%{p}%'
                params.extend([like]*5)
            j_where.append('(' + ' AND '.join(q_clauses) + ')')
    if branch: j_where.append("n.branch=?"); params.append(branch)
    if semester: j_where.append("n.semester=?"); params.append(int(semester))
    if note_type: j_where.append("n.note_type=?"); params.append(note_type)
    if difficulty: j_where.append("n.difficulty=?"); params.append(difficulty)
    order={'downloads':'n.downloads DESC','saves':'n.views DESC'}.get(sort,'n.uploaded_at DESC')
    base = f"FROM notes n JOIN users u ON n.uploaded_by = u.id WHERE {' AND '.join(j_where)}"
    
    total=db.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
    notes=db.execute(f"SELECT n.*, u.name as uploader_name, u.profile_picture as uploader_pic, u.avatar_color as uploader_color, u.is_verified as uploader_verified {base} ORDER BY {order} LIMIT ? OFFSET ?", params+[pp,(page-1)*pp]).fetchall()
    if not notes and q:
        # fallback: OR-match any word
        words=[w for w in q.split() if w]
        if words:
            f_sub=[]
            f_params=[]
            for w in words:
                f_sub.append("(n.title LIKE ? OR n.subject LIKE ? OR n.tags LIKE ? OR n.description LIKE ? OR n.college LIKE ?)")
                like=f'%{w}%'
                f_params.extend([like]*5)
            sim_base = f"FROM notes n JOIN users u ON n.uploaded_by = u.id WHERE n.status='approved' AND ({' OR '.join(f_sub)})"
            similar=db.execute(f"SELECT n.*, u.name as uploader_name, u.profile_picture as uploader_pic, u.avatar_color as uploader_color, u.is_verified as uploader_verified {sim_base} ORDER BY n.downloads DESC LIMIT 20", f_params).fetchall()
        else:
            similar=[]
    else:
        similar=[]
    saved_ids={r['note_id'] for r in db.execute("SELECT note_id FROM saved_notes WHERE user_id=?",(uid,)).fetchall()} if uid else set()
    uploaders=get_uploaders(db,notes if notes else similar)
    pages=(total+pp-1)//pp
    return render_template('notes/browse.html',notes=notes,total=total,page=page,pages=pages,
                           q=q,branch=branch,semester=semester,note_type=note_type,
                           difficulty=difficulty,sort=sort,saved_ids=saved_ids,uploaders=uploaders,
                           similar=similar)

@app.route('/autocomplete')
def autocomplete():
    q=request.args.get('q','').strip()
    if not q: return jsonify([])
    words=[w for w in q.split() if w]
    if not words: return jsonify([])
    where=["n.status='approved'"]
    params=[]
    search_clauses=[]
    for w in words:
        criterion="(n.title LIKE ? OR n.subject LIKE ? OR n.tags LIKE ? OR n.description LIKE ? OR n.college LIKE ? OR n.branch LIKE ? OR n.note_type LIKE ?)"
        search_clauses.append(criterion)
        like=f'%{w}%'
        params.extend([like]*7)
    where.append(f"({' OR '.join(search_clauses)})")
    
    query = f"""
        SELECT n.id, n.title, n.subject, n.branch, n.semester, n.note_type, u.name as uploader_name 
        FROM notes n 
        LEFT JOIN users u ON n.uploaded_by = u.id 
        WHERE {' AND '.join(where)} 
        ORDER BY n.downloads DESC LIMIT 10
    """
    notes=get_db().execute(query, params).fetchall()
    
    payload=[]
    for n in notes:
        uploader = f" · by {n['uploader_name']}" if n['uploader_name'] else ""
        payload.append({'id':n['id'], 'title': n['title'], 'text':f"{n['title']} · {n['subject']} · {n['branch']} · Sem {n['semester']}{uploader}"})
    return jsonify(payload)

# ─── DETAIL ─────────────────────────────────────────────────────────
@app.route('/notes/<int:nid>')
def note_detail(nid):
    db=get_db(); u=cur_user(); uid=u['id'] if u else None
    note=db.execute("SELECT * FROM notes WHERE id=?",(nid,)).fetchone()
    if not note: abort(404)
    if note['status']!='approved' and (not uid or (uid!=note['uploaded_by'] and (not u or u['role']!='admin'))): abort(404)
    db.execute("UPDATE notes SET views=views+1 WHERE id=?",(nid,)); db.commit()
    uploader=db.execute("SELECT * FROM users WHERE id=?",(note['uploaded_by'],)).fetchone()
    comments=db.execute("SELECT c.*,u.name as uname,u.avatar_color FROM comments c JOIN users u ON c.user_id=u.id WHERE c.note_id=? AND c.is_deleted=0 ORDER BY c.created_at DESC",(nid,)).fetchall()
    related=db.execute("SELECT * FROM notes WHERE status='approved' AND subject=? AND id!=? LIMIT 4",(note['subject'],nid)).fetchall()
    ratings=db.execute("SELECT value FROM ratings WHERE note_id=?",(nid,)).fetchall()
    avg_rating=round(sum(r['value'] for r in ratings)/len(ratings),1) if ratings else 0
    rating_count=len(ratings)
    save_count=db.execute("SELECT COUNT(*) FROM saved_notes WHERE note_id=?",(nid,)).fetchone()[0]
    is_saved=bool(uid and db.execute("SELECT 1 FROM saved_notes WHERE user_id=? AND note_id=?",(uid,nid)).fetchone())
    user_rating=db.execute("SELECT * FROM ratings WHERE user_id=? AND note_id=?",(uid,nid)).fetchone() if uid else None
    rel_up=get_uploaders(db,related)
    return render_template('notes/detail.html',note=note,uploader=uploader,comments=comments,
                           related=related,avg_rating=avg_rating,rating_count=rating_count,
                           save_count=save_count,is_saved=is_saved,user_rating=user_rating,rel_up=rel_up)

# ─── UPLOAD ─────────────────────────────────────────────────────────
@app.route('/upload',methods=['GET','POST'])
@login_req
def upload():
    u=cur_user()
    if request.method=='POST':
        title=request.form.get('title','').strip()
        subject=request.form.get('subject','').strip()
        branch=request.form.get('branch','')
        semester=request.form.get('semester','')
        note_type=request.form.get('note_type','')
        difficulty=request.form.get('difficulty','')
        description=request.form.get('description','').strip()
        tags=request.form.get('tags','').strip()
        college=request.form.get('college',u['college'] or '').strip()
        if not all([title,subject,branch,semester,note_type,difficulty]):
            flash('Fill all required fields.','error'); return render_template('notes/upload.html')
        if 'file' not in request.files or not request.files['file'].filename:
            flash('Select a file.','error'); return render_template('notes/upload.html')
        file=request.files['file']
        if not allowed(file.filename):
            flash('File type not allowed.','error'); return render_template('notes/upload.html')
        ext=file.filename.rsplit('.',1)[1].lower()
        uname=f"{uuid.uuid4().hex}.{ext}"
        
        # Read file data once
        file_data = file.read()
        fsz = len(file_data)
        
        # Upload to Supabase Storage if configured
        if supabase:
            try:
                # Upload to 'notes' bucket
                supabase.storage.from_('notes').upload(
                    path=uname,
                    file=file_data,
                    file_options={"content-type": file.content_type}
                )
            except Exception as e:
                flash(f'Cloud upload failed: {e}','error'); return render_template('notes/upload.html')
        else:
            # Fallback to local and Database persistence
            save_path=os.path.join(UPLOAD_FOLDER,uname)
            with open(save_path, 'wb') as f:
                f.write(file_data)
            db=get_db()
            try: db.execute("INSERT OR IGNORE INTO file_blobs(filename, data) VALUES(?,?)", (uname, file_data))
            except: pass
        
        db=get_db()
        db.execute("INSERT INTO notes(title,subject,branch,semester,note_type,difficulty,description,tags,college,file_path,file_name,file_size,file_ext,uploaded_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (title,subject,branch,int(semester),note_type,difficulty,description,tags,college,uname,file.filename,fsz,ext,u['id']))
        for a in db.execute("SELECT id FROM users WHERE role='admin'").fetchall():
            db.execute("INSERT INTO notifications(user_id,message,type) VALUES(?,?,?)",
                       (a['id'],f'New note "{title}" by {u["name"]} awaiting approval.','info'))
        # Notify followers
        followers = db.execute("SELECT follower_id FROM follows WHERE following_id=?",(u['id'],)).fetchall()
        for fol in followers:
            db.execute("INSERT INTO notifications(user_id,message,type) VALUES(?,?,?)",
                       (fol['follower_id'],f'{u["name"]} uploaded a new note: "{title}"','info'))
        db.commit()
        check_badges(db, u['id'])
        flash('Uploaded! Pending admin review.','success'); return redirect(url_for('my_notes'))
    return render_template('notes/upload.html')

# ─── DOWNLOAD / PREVIEW ─────────────────────────────────────────────
@app.route('/download/<int:nid>')
@login_req
def download_note(nid):
    db=get_db(); u=cur_user()
    note=db.execute("SELECT * FROM notes WHERE id=?",(nid,)).fetchone()
    if not note: abort(404)
    if note['status'] != 'approved':
        if not u or (not u.get('is_admin') and note['uploaded_by'] != u['id']):
            abort(403)
    
    # Track stats only for approved notes viewed by non-authors
    if note['status'] == 'approved' and note['uploaded_by'] != u['id']:
        db.execute("UPDATE notes SET downloads=downloads+1 WHERE id=?",(nid,))
        db.execute("INSERT INTO download_history(user_id,note_id) VALUES(?,?)",(u['id'],nid))
        db.commit()
        check_badges(db, note['uploaded_by'])
    
    # Serve from Supabase if possible
    if supabase:
        try:
            res = supabase.storage.from_('notes').get_public_url(note['file_path'])
            import urllib.parse
            return redirect(res + "?download=" + urllib.parse.quote(note['file_name']))
        except: pass
        
    # Local fallback
    file_path = os.path.join(UPLOAD_FOLDER, note['file_path'])
    if not os.path.exists(file_path):
        blob = db.execute("SELECT data FROM file_blobs WHERE filename=?", (note['file_path'],)).fetchone()
        if blob and blob['data']:
            with open(file_path, 'wb') as f:
                f.write(blob['data'])
        else:
            flash('⚠️ File Not Found — This note was uploaded during a previous hosting session and is no longer on the server. Please contact the uploader.', 'error')
            return redirect(url_for('note_detail', nid=nid))
    return send_from_directory(UPLOAD_FOLDER, note['file_path'], as_attachment=True, download_name=note['file_name'])

@app.route('/preview/<int:nid>')
@login_req
def preview_note(nid):
    db=get_db(); u=cur_user()
    note=db.execute("SELECT * FROM notes WHERE id=?",(nid,)).fetchone()
    if not note: abort(404)
    if note['status'] != 'approved':
        if not u or (not u.get('is_admin') and note['uploaded_by'] != u['id']):
            abort(403)
    
    # Serve from Supabase if possible
    if supabase:
        try:
            res = supabase.storage.from_('notes').get_public_url(note['file_path'])
            return redirect(res)
        except: pass
        
    # Local fallback
    file_path = os.path.join(UPLOAD_FOLDER, note['file_path'])
    if not os.path.exists(file_path):
        blob = db.execute("SELECT data FROM file_blobs WHERE filename=?", (note['file_path'],)).fetchone()
        if blob and blob['data']:
            with open(file_path, 'wb') as f:
                f.write(blob['data'])
        else:
            abort(404)
    return send_from_directory(UPLOAD_FOLDER, note['file_path'])

# ─── SAVE / RATE / COMMENT / REPORT ─────────────────────────────────
@app.route('/save/<int:nid>',methods=['POST'])
@login_req
def toggle_save(nid):
    db=get_db(); u=cur_user()
    ex=db.execute("SELECT 1 FROM saved_notes WHERE user_id=? AND note_id=?",(u['id'],nid)).fetchone()
    if ex: db.execute("DELETE FROM saved_notes WHERE user_id=? AND note_id=?",(u['id'],nid)); saved=False
    else: db.execute("INSERT OR IGNORE INTO saved_notes(user_id,note_id) VALUES(?,?)",(u['id'],nid)); saved=True
    db.commit()
    cnt=db.execute("SELECT COUNT(*) FROM saved_notes WHERE note_id=?",(nid,)).fetchone()[0]
    return jsonify({'saved':saved,'count':cnt})

@app.route('/rate/<int:nid>',methods=['POST'])
@login_req
def rate_note(nid):
    db=get_db(); u=cur_user()
    val=request.json.get('value',0)
    if not 1<=val<=5: return jsonify({'error':'Invalid'}),400
    db.execute("INSERT OR REPLACE INTO ratings(user_id,note_id,value) VALUES(?,?,?)",(u['id'],nid,val))
    db.commit()
    ratings=db.execute("SELECT value FROM ratings WHERE note_id=?",(nid,)).fetchall()
    avg=round(sum(r['value'] for r in ratings)/len(ratings),1) if ratings else 0
    return jsonify({'avg':avg,'count':len(ratings)})

@app.route('/comment/<int:nid>',methods=['POST'])
@login_req
def add_comment(nid):
    db=get_db(); u=cur_user()
    content=request.form.get('content','').strip()
    if not content: flash('Comment empty.','error'); return redirect(url_for('note_detail',nid=nid))
    db.execute("INSERT INTO comments(user_id,note_id,content) VALUES(?,?,?)",(u['id'],nid,content))
    db.commit(); flash('Comment posted.','success')
    return redirect(url_for('note_detail',nid=nid))

@app.route('/report/<int:nid>',methods=['POST'])
@login_req
def report_note(nid):
    db=get_db(); u=cur_user()
    reason=request.form.get('reason','').strip()
    if not reason: flash('Provide reason.','error'); return redirect(url_for('note_detail',nid=nid))
    db.execute("INSERT INTO reports(reporter_id,note_id,reason) VALUES(?,?,?)",(u['id'],nid,reason))
    db.commit(); flash('Report submitted.','info')
    return redirect(url_for('note_detail',nid=nid))

@app.route('/notifications/read',methods=['POST'])
@login_req
def mark_read():
    db=get_db(); u=cur_user()
    db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?",(u['id'],))
    db.commit(); return jsonify({'ok':True})

# ─── AUTH ────────────────────────────────────────────────────────────
@app.route('/register',methods=['GET','POST'])
def register():
    if session.get('user_id'): return redirect(url_for('index'))
    if request.method=='POST':
        name=request.form.get('name','').strip()
        email=request.form.get('email','').strip().lower()
        password=request.form.get('password','')
        confirm=request.form.get('confirm_password','')
        college=request.form.get('college','').strip()
        branch=request.form.get('branch','')
        semester=request.form.get('semester','')
        if not all([name,email,password,confirm]):
            flash('Fill all required fields.','error'); return render_template('auth/register.html')
        if password!=confirm: flash('Passwords do not match.','error'); return render_template('auth/register.html')
        if len(password)<6: flash('Password too short.','error'); return render_template('auth/register.html')
        db=get_db()
        if db.execute("SELECT 1 FROM users WHERE email=?",(email,)).fetchone():
            flash('Email already registered.','error'); return render_template('auth/register.html')
        color=random.choice(AVATAR_COLORS)
        cur=db.execute("INSERT INTO users(name,email,password_hash,college,branch,semester,avatar_color) VALUES(?,?,?,?,?,?,?)",
                       (name,email,hp(password),college,branch,int(semester) if semester else None,color))
        uid=cur.lastrowid
        db.execute("INSERT INTO notifications(user_id,message,type) VALUES(?,?,?)",
                   (uid,f'Welcome to CampusNotes, {name}! 🎉','success'))
        db.commit()
        
        # Send verification email
        send_verification_email(email)
        
        # session['user_id']=uid  # Don't log in automatically
        flash(f'Welcome, {name}! A verification email has been sent. Please check your inbox.','info'); return redirect(url_for('login'))
    return render_template('auth/register.html')

@app.route('/verify-email/<token>')
def verify_email(token):
    try:
        email = ts.loads(token, salt='email-confirm', max_age=86400)
    except:
        flash('The verification link is invalid or has expired.', 'error')
        return redirect(url_for('login'))

    db = get_db()
    db.execute("UPDATE users SET is_verified=1 WHERE email=?", (email,))
    db.commit()
    
    flash('Your email has been verified! You can now log in.', 'success')
    return redirect(url_for('login'))

@app.route('/resend-verification', methods=['GET', 'POST'])
def resend_verification():
    if session.get('user_id'): return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        db = get_db()
        u = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        
        if u and u['is_verified'] == 0:
            send_verification_email(email)
            flash('Verification email resent. Please check your inbox.', 'info')
            return redirect(url_for('login'))
        elif u and u['is_verified'] == 1:
            flash('This account is already verified. Please log in.', 'info')
            return redirect(url_for('login'))
        else:
            flash('Email not found. Please register first.', 'error')
            return redirect(url_for('register'))
            
    return render_template('auth/resend_verification.html')

@app.route('/login',methods=['GET','POST'])
def login():
    if session.get('user_id'): return redirect(url_for('index'))
    if request.method=='POST':
        email=request.form.get('email','').strip().lower()
        password=request.form.get('password','')
        db=get_db()
        u=db.execute("SELECT * FROM users WHERE email=?",(email,)).fetchone()
        if not u or u['password_hash']!=hp(password):
            flash('Invalid email or password.','error'); return render_template('auth/login.html')
        if u['status']=='blocked':
            flash('Account blocked.','error'); return render_template('auth/login.html')
        
        if u['is_verified'] == 0 and u['role'] != 'admin':
            flash('Please verify your email before logging in.', 'warning')
            return render_template('auth/login.html')
            
        session['user_id']=u['id']
        if request.form.get('remember')=='on': session.permanent=True
        nxt=request.args.get('next')
        return redirect(nxt or (url_for('admin_dashboard') if u['role']=='admin' else url_for('index')))
    return render_template('auth/login.html')

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        db = get_db()
        u = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        
        if not u:
            # Do not reveal if email exists for security reasons
            flash('If an account matches that email, a password reset link has been sent.', 'info')
            return redirect(url_for('login'))
            
        if u['role'] == 'admin':
            flash('Admin accounts cannot be reset via this form for security reasons.', 'error')
            return redirect(url_for('forgot_password'))
            
        send_reset_email(email)
        flash('If an account matches that email, a password reset link has been sent.', 'info')
        return redirect(url_for('login'))
        
    return render_template('auth/forgot_password.html')

@app.route('/reset-password/<token>', methods=['GET'])
def reset_password_with_token(token):
    try:
        email = ts.loads(token, salt='password-reset', max_age=3600) # Token valid for 1 hour
    except:
        flash('The password reset link is invalid or has expired.', 'error')
        return redirect(url_for('forgot_password'))
        
    session['reset_email'] = email
    return render_template('auth/reset_password.html')

@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if 'reset_email' not in session:
        flash('Session expired or invalid request. Please request a new password reset.', 'error')
        return redirect(url_for('forgot_password'))
    
    if request.method == 'GET':
        return render_template('auth/reset_password.html')
        
    if request.method == 'POST':
        email = session['reset_email']
        db = get_db()
        u = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not u or u['role'] == 'admin':
            session.pop('reset_email', None)
            flash('Invalid request.', 'error')
            return redirect(url_for('login'))
        
        new_password = request.form.get('password')
        confirm_password = request.form.get('confirm')
        
        if len(new_password) < 6:
            flash('Password must be at least 6 characters.', 'error')
            return redirect(url_for('reset_password_with_token', token=request.form.get('token', ''))) # Token not easily available here, will fallback to session email which is still secure. Actually just returning to the view.
        if new_password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('auth/reset_password.html')
            
        db = get_db()
        db.execute("UPDATE users SET password_hash=? WHERE email=?", (hp(new_password), email))
        db.commit()
        
        # Clear the reset_email from session
        session.pop('reset_email', None)
        flash('Password reset successfully! You can now log in.', 'success')
        return redirect(url_for('login'))
        
    return render_template('auth/reset_password.html')

@app.route('/logout')
def logout():
    session.clear(); flash('Logged out.','info'); return redirect(url_for('login'))

# ─── STUDENT ─────────────────────────────────────────────────────────
@app.route('/dashboard')
@login_req
def dashboard():
    db=get_db(); u=cur_user()
    my_notes=db.execute("SELECT * FROM notes WHERE uploaded_by=? ORDER BY uploaded_at DESC",(u['id'],)).fetchall()
    saved=db.execute("SELECT sn.user_id, sn.saved_at, n.id as id, n.id as note_id, n.title, n.subject, n.note_type, n.branch, n.semester, n.difficulty, n.file_ext, n.downloads, n.views, n.uploaded_at, n.uploaded_by, n.featured FROM saved_notes sn JOIN notes n ON sn.note_id=n.id WHERE sn.user_id=? AND n.status='approved' ORDER BY sn.saved_at DESC",(u['id'],)).fetchall()
    downloads=db.execute("SELECT dh.*,n.title,n.subject FROM download_history dh JOIN notes n ON dh.note_id=n.id WHERE dh.user_id=? ORDER BY dh.downloaded_at DESC LIMIT 10",(u['id'],)).fetchall()
    notifs=db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 6",(u['id'],)).fetchall()
    saved_ids={s['note_id'] for s in saved}
    uploaders={u['id']:u}
    for s in saved:
        if s['uploaded_by'] not in uploaders:
            uploaders[s['uploaded_by']]=db.execute("SELECT * FROM users WHERE id=?",(s['uploaded_by'],)).fetchone()
    return render_template('student/dashboard.html',my_notes=my_notes,saved=saved,
                           downloads=downloads,notifs=notifs,saved_ids=saved_ids,uploaders=uploaders,
                           total_downloads=sum(n['downloads'] for n in my_notes),
                           total_views=sum(n['views'] for n in my_notes))

@app.route('/my-notes')
@login_req
def my_notes():
    db=get_db(); u=cur_user()
    notes=db.execute("SELECT * FROM notes WHERE uploaded_by=? ORDER BY uploaded_at DESC",(u['id'],)).fetchall()
    return render_template('student/my_notes.html',notes=notes)

@app.route('/saved')
@login_req
def saved_notes_page():
    db=get_db(); u=cur_user()
    saved=db.execute("SELECT sn.user_id, sn.saved_at, n.id as id, n.id as note_id, n.title, n.subject, n.note_type, n.branch, n.semester, n.difficulty, n.file_ext, n.downloads, n.views, n.uploaded_at, n.uploaded_by, n.featured FROM saved_notes sn JOIN notes n ON sn.note_id=n.id WHERE sn.user_id=? AND n.status='approved' ORDER BY sn.saved_at DESC",(u['id'],)).fetchall()
    saved_ids={s['note_id'] for s in saved}
    uploaders=get_uploaders(db,saved)
    return render_template('student/saved.html',saved=saved,saved_ids=saved_ids,uploaders=uploaders)

@app.route('/delete-my-note/<int:nid>',methods=['POST'])
@login_req
def delete_my_note(nid):
    db=get_db(); u=cur_user()
    note=db.execute("SELECT * FROM notes WHERE id=?",(nid,)).fetchone()
    if not note or note['uploaded_by']!=u['id']: abort(403)
    
    # Remove from Supabase if possible
    if supabase:
        try: supabase.storage.from_('notes').remove([note['file_path']])
        except: pass
    
    # Remove local fallback
    try: os.remove(os.path.join(UPLOAD_FOLDER,note['file_path']))
    except: pass
    db.execute("DELETE FROM file_blobs WHERE filename=?", (note['file_path'],))
    
    db.execute("DELETE FROM notes WHERE id=?",(nid,)); db.commit()
    flash('Note deleted.','success'); return redirect(url_for('my_notes'))

@app.route('/profile',methods=['GET','POST'])
@login_req
def profile():
    u=cur_user()
    if u['role']=='admin':
        flash('Admin accounts do not have a profile page.','info')
        return redirect(url_for('admin_dashboard'))
    db=get_db()
    if request.method=='POST':
        name=request.form.get('name',u['name']).strip()
        college=request.form.get('college','').strip()
        branch=request.form.get('branch','')
        semester=request.form.get('semester','')
        bio=request.form.get('bio','').strip()
        new_pass=request.form.get('new_password','')
        if new_pass:
            if u['password_hash']!=hp(request.form.get('current_password','')):
                flash('Current password wrong.','error'); return render_template('student/profile.html')
            if len(new_pass)<6: flash('Too short.','error'); return render_template('student/profile.html')
            db.execute("UPDATE users SET password_hash=? WHERE id=?",(hp(new_pass),u['id']))
        # Handle profile picture upload
        if 'profile_picture' in request.files:
            pic = request.files['profile_picture']
            if pic and pic.filename:
                import base64
                ext = pic.filename.rsplit('.', 1)[1].lower() if '.' in pic.filename else ''
                if ext in ALLOWED_AVATAR_EXT:
                    pic_data = pic.read()
                    if len(pic_data) > 2 * 1024 * 1024:
                        flash('Profile picture must be under 2MB.','error')
                        return redirect(url_for('profile'))
                    encoded = base64.b64encode(pic_data).decode('utf-8')
                    data_uri = f"data:image/{ext};base64,{encoded}"
                    db.execute("UPDATE users SET profile_picture=? WHERE id=?", (data_uri, u['id']))
        db.execute("UPDATE users SET name=?,college=?,branch=?,semester=?,bio=? WHERE id=?",
                   (name,college,branch,int(semester) if semester else None,bio,u['id']))
        db.commit(); flash('Profile updated!','success'); return redirect(url_for('profile'))
    badges=[b['badge_type'] for b in db.execute("SELECT badge_type FROM badges WHERE user_id=?",(u['id'],)).fetchall()]
    return render_template('student/profile.html', badges=badges)

@app.route('/avatar/<filename>')
def serve_avatar(filename):
    from flask import make_response
    import os
    file_path = os.path.join(AVATAR_FOLDER, filename)
    if not os.path.exists(file_path):
        svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" fill="none">
            <rect width="100" height="100" fill="#e5e7eb"/>
            <path d="M50 50C61.0457 50 70 41.0457 70 30C70 18.9543 61.0457 10 50 10C38.9543 10 30 18.9543 30 30C30 41.0457 38.9543 50 50 50ZM50 55C33.3333 55 0 63.3333 0 80V90H100V80C100 63.3333 66.6667 55 50 55Z" fill="#9ca3af"/>
        </svg>'''
        resp = make_response(svg)
        resp.headers['Content-Type'] = 'image/svg+xml'
        resp.headers['Cache-Control'] = 'public, max-age=86400'
        return resp
    resp = make_response(send_from_directory(AVATAR_FOLDER, filename))
    resp.headers['Cache-Control'] = 'public, max-age=86400'
    return resp

# ─── SOCIAL & PROFILES ──────────────────────────────────────────────
@app.route('/user/<int:uid>')
def public_profile(uid):
    db=get_db(); u=db.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    if not u or u['role']!='student': abort(404)
    notes=db.execute("SELECT * FROM notes WHERE uploaded_by=? AND status='approved' ORDER BY uploaded_at DESC",(uid,)).fetchall()
    badges=db.execute("SELECT badge_type FROM badges WHERE user_id=?",(uid,)).fetchall()
    cu=cur_user()
    is_following=bool(cu and db.execute("SELECT 1 FROM follows WHERE follower_id=? AND following_id=?",(cu['id'],uid)).fetchone())
    followers=db.execute("SELECT COUNT(*) FROM follows WHERE following_id=?",(uid,)).fetchone()[0]
    following=db.execute("SELECT COUNT(*) FROM follows WHERE follower_id=?",(uid,)).fetchone()[0]
    return render_template('student/public_profile.html',user=u,notes=notes,badges=[b['badge_type'] for b in badges],
                           is_following=is_following,followers=followers,following=following)

@app.route('/follow/<int:uid>',methods=['POST'])
@login_req
def follow_user(uid):
    db=get_db(); cu=cur_user()
    if cu['id']==uid: return jsonify({'error':'Cannot follow self'}),400
    if not db.execute("SELECT 1 FROM users WHERE id=?",(uid,)).fetchone(): abort(404)
    try:
        db.execute("INSERT INTO follows(follower_id,following_id) VALUES(?,?)",(cu['id'],uid))
        db.execute("INSERT INTO notifications(user_id,message,type) VALUES(?,?,?)",
                   (uid,f"{cu['name']} started following you!","info"))
        db.commit()
    except: pass
    return jsonify({'ok':True})

@app.route('/unfollow/<int:uid>',methods=['POST'])
@login_req
def unfollow_user(uid):
    db=get_db(); cu=cur_user()
    db.execute("DELETE FROM follows WHERE follower_id=? AND following_id=?",(cu['id'],uid))
    db.commit(); return jsonify({'ok':True})

# ─── LEADERBOARD & REQUESTS ─────────────────────────────────────────
@app.route('/leaderboard')
def leaderboard():
    db=get_db()
    # Score: Downloads + Saves (views as approximation of saves in simple queries)
    top_users=db.execute("""
        SELECT u.*, 
               COUNT(n.id) as uploads,
               COALESCE(SUM(n.downloads),0) as total_dl
        FROM users u 
        JOIN notes n ON u.id = n.uploaded_by AND n.status='approved'
        WHERE u.role='student'
        GROUP BY u.id
        ORDER BY total_dl DESC, uploads DESC LIMIT 50
    """).fetchall()
    user_badges={u['id']:[b['badge_type'] for b in db.execute("SELECT badge_type FROM badges WHERE user_id=?",(u['id'],)).fetchall()] for u in top_users}
    return render_template('student/leaderboard.html',users=top_users,user_badges=user_badges)

@app.route('/requests',methods=['GET','POST'])
def note_requests():
    db=get_db(); cu=cur_user()
    if request.method=='POST':
        if not cu: abort(403)
        subj=request.form.get('subject','').strip()
        br=request.form.get('branch','')
        sem=request.form.get('semester','')
        desc=request.form.get('description','').strip()
        if not subj: flash('Subject is required','error'); return redirect(url_for('note_requests'))
        db.execute("INSERT INTO note_requests(user_id,subject,branch,semester,description) VALUES(?,?,?,?,?)",
                   (cu['id'],subj,br,int(sem) if sem else None,desc)); db.commit()
        flash('Request posted!','success'); return redirect(url_for('note_requests'))
    
    reqs=db.execute("SELECT r.*,u.name,u.avatar_color,u.profile_picture FROM note_requests r JOIN users u ON r.user_id=u.id ORDER BY r.status DESC, r.created_at DESC").fetchall()
    return render_template('student/requests.html',requests=reqs)

@app.route('/requests/<int:rid>/fulfill',methods=['POST'])
@login_req
def fulfill_request(rid):
    db=get_db(); cu=cur_user()
    nid=request.form.get('note_id')
    req=db.execute("SELECT * FROM note_requests WHERE id=?",(rid,)).fetchone()
    if not req or req['status']!='open': abort(404)
    db.execute("UPDATE note_requests SET status='fulfilled', fulfilled_by=? WHERE id=?",(nid,rid))
    db.execute("INSERT INTO notifications(user_id,message,type,link) VALUES(?,?,?,?)",
               (req['user_id'],f"{cu['name']} fulfilled your request for '{req['subject']}'!","success",url_for('note_detail',nid=nid)))
    db.commit(); flash('Request fulfilled!','success')
    return redirect(url_for('note_requests'))

@app.route('/requests/<int:rid>/delete',methods=['POST'])
@login_req
def delete_request(rid):
    db=get_db(); cu=cur_user()
    req=db.execute("SELECT * FROM note_requests WHERE id=?",(rid,)).fetchone()
    if not req: abort(404)
    if req['user_id'] != cu['id'] and cu['role'] != 'admin': abort(403)
    db.execute("DELETE FROM note_requests WHERE id=?",(rid,))
    db.commit()
    flash('Request deleted!','success')
    return redirect(url_for('note_requests'))

# ─── TOOLS ──────────────────────────────────────────────────────────
@app.route('/compare')
def compare_notes():
    n1_id=request.args.get('n1')
    n2_id=request.args.get('n2')
    db=get_db()
    n1=db.execute("SELECT * FROM notes WHERE id=?",(n1_id,)).fetchone() if n1_id else None
    n2=db.execute("SELECT * FROM notes WHERE id=?",(n2_id,)).fetchone() if n2_id else None
    up=get_uploaders(db,[n for n in (n1,n2) if n]) if n1 or n2 else {}
    return render_template('notes/compare.html',n1=n1,n2=n2,uploaders=up)

@app.route('/features')
def features():
    return render_template('student/features.html')

# ─── ADMIN ───────────────────────────────────────────────────────────
@app.route('/admin')
@admin_req
def admin_dashboard():
    db=get_db()
    today=date.today()
    daily=[{'day':(today-timedelta(days=i)).strftime('%a'),
            'count':db.execute("SELECT COUNT(*) FROM notes WHERE date(uploaded_at)=?",(str(today-timedelta(days=i)),)).fetchone()[0]}
           for i in range(6,-1,-1)]
    return render_template('admin/dashboard.html',
        total_users=db.execute("SELECT COUNT(*) FROM users WHERE role='student'").fetchone()[0],
        total_notes=db.execute("SELECT COUNT(*) FROM notes WHERE status='approved'").fetchone()[0],
        pending=db.execute("SELECT COUNT(*) FROM notes WHERE status='pending'").fetchone()[0],
        total_downloads=db.execute("SELECT COALESCE(SUM(downloads),0) FROM notes").fetchone()[0],
        reports=db.execute("SELECT COUNT(*) FROM reports WHERE status='open'").fetchone()[0],
        recent_notes=db.execute("SELECT n.*,u.name as uploader_name,u.avatar_color FROM notes n JOIN users u ON n.uploaded_by=u.id ORDER BY n.uploaded_at DESC LIMIT 10").fetchall(),
        recent_users=db.execute("SELECT * FROM users WHERE role='student' ORDER BY created_at DESC LIMIT 5").fetchall(),
        top_notes=db.execute("SELECT * FROM notes WHERE status='approved' ORDER BY downloads DESC LIMIT 5").fetchall(),
        daily_data=daily)

@app.route('/admin/notes')
@admin_req
def admin_notes():
    db=get_db()
    sf=request.args.get('status','pending')
    notes=db.execute("SELECT n.*,u.name as uploader_name,u.avatar_color FROM notes n JOIN users u ON n.uploaded_by=u.id WHERE n.status=? ORDER BY n.uploaded_at DESC",(sf,)).fetchall()
    return render_template('admin/notes.html',notes=notes,status_filter=sf)

@app.route('/admin/review/<int:nid>',methods=['GET','POST'])
@admin_req
def admin_review_note(nid):
    db=get_db()
    note=db.execute("SELECT * FROM notes WHERE id=?",(nid,)).fetchone()
    if not note: abort(404)
    uploader=db.execute("SELECT * FROM users WHERE id=?",(note['uploaded_by'],)).fetchone()
    if request.method=='POST':
        action=request.form.get('action')
        if action=='approve':
            if USE_PG:
                db.execute("UPDATE notes SET status='approved',approved_at=NOW() WHERE id=?",(nid,))
            else:
                db.execute("UPDATE notes SET status='approved',approved_at=datetime('now') WHERE id=?",(nid,))
            db.execute("INSERT INTO notifications(user_id,message,type) VALUES(?,?,?)",
                       (note['uploaded_by'],f'Your note "{note["title"]}" was approved! 🎉','success'))
            db.commit()
            check_badges(db, note['uploaded_by'])
            flash('Note approved!','success')
        elif action=='reject':
            reason=request.form.get('reason','Did not meet quality standards.')
            db.execute("UPDATE notes SET status='rejected',reject_reason=? WHERE id=?",(reason,nid))
            db.execute("INSERT INTO notifications(user_id,message,type) VALUES(?,?,?)",
                       (note['uploaded_by'],f'Your note "{note["title"]}" was rejected. Reason: {reason}','error'))
            flash('Note rejected.','warning')
        elif action=='feature':
            nv=0 if note['featured'] else 1
            db.execute("UPDATE notes SET featured=? WHERE id=?",(nv,nid))
            flash(f'Note {"featured" if nv else "unfeatured"}.','info')
        db.commit(); return redirect(url_for('admin_notes'))
    return render_template('admin/review.html',note=note,uploader=uploader)

@app.route('/admin/users')
@admin_req
def admin_users():
    db=get_db(); q=request.args.get('q','')
    if q:
        users=db.execute("SELECT * FROM users WHERE role='student' AND (name LIKE ? OR email LIKE ?) ORDER BY created_at DESC",(f'%{q}%',f'%{q}%')).fetchall()
    else:
        users=db.execute("SELECT * FROM users WHERE role='student' ORDER BY created_at DESC").fetchall()
    note_counts={u['id']:db.execute("SELECT COUNT(*) FROM notes WHERE uploaded_by=?",(u['id'],)).fetchone()[0] for u in users}
    return render_template('admin/users.html',users=users,search=q,note_counts=note_counts)

@app.route('/admin/toggle-user/<int:uid>',methods=['POST'])
@admin_req
def admin_toggle_user(uid):
    db=get_db(); u=db.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    if not u: abort(404)
    ns='blocked' if u['status']=='active' else 'active'
    db.execute("UPDATE users SET status=? WHERE id=?",(ns,uid)); db.commit()
    flash(f'User {u["name"]} {ns}.','info'); return redirect(url_for('admin_users'))

@app.route('/admin/toggle-verified/<int:uid>',methods=['POST'])
@admin_req
def admin_toggle_verified(uid):
    db=get_db(); u=db.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    if not u: abort(404)
    nv = 0 if u['is_verified'] else 1
    db.execute("UPDATE users SET is_verified=? WHERE id=?",(nv,uid))
    if nv:
        db.execute("INSERT OR IGNORE INTO badges(user_id,badge_type) VALUES(?,'verified')",(uid,))
        db.execute("INSERT INTO notifications(user_id,message,type) VALUES(?,?,?)",
                   (uid,"You have been verified by an admin! ✓","success"))
    else:
        db.execute("DELETE FROM badges WHERE user_id=? AND badge_type='verified'",(uid,))
    db.commit()
    flash(f'{u["name"]} verification status updated.','info')
    return redirect(url_for('admin_users'))

@app.route('/admin/delete-note/<int:nid>',methods=['POST'])
@admin_req
def admin_delete_note(nid):
    db=get_db(); note=db.execute("SELECT * FROM notes WHERE id=?",(nid,)).fetchone()
    if not note: abort(404)
    
    # Remove from Supabase if possible
    if supabase:
        try: supabase.storage.from_('notes').remove([note['file_path']])
        except: pass
        
    # Remove local fallback
    try: os.remove(os.path.join(UPLOAD_FOLDER,note['file_path']))
    except: pass
    db.execute("DELETE FROM file_blobs WHERE filename=?", (note['file_path'],))
    
    db.execute("DELETE FROM notes WHERE id=?",(nid,)); db.commit()
    flash('Note deleted.','success'); return redirect(url_for('admin_notes'))

@app.route('/admin/reports')
@admin_req
def admin_reports():
    db=get_db()
    reports=db.execute("SELECT r.*,u.name as reporter_name,u.email as reporter_email,n.title as note_title FROM reports r LEFT JOIN users u ON r.reporter_id=u.id LEFT JOIN notes n ON r.note_id=n.id ORDER BY r.created_at DESC").fetchall()
    return render_template('admin/reports.html',reports=reports)

@app.route('/admin/resolve-report/<int:rid>',methods=['POST'])
@admin_req
def admin_resolve_report(rid):
    db=get_db()
    db.execute("UPDATE reports SET status='resolved' WHERE id=?",(rid,)); db.commit()
    flash('Report resolved.','success'); return redirect(url_for('admin_reports'))

@app.errorhandler(404)
def e404(e): return render_template('errors/404.html'),404

@app.errorhandler(403)
def e403(e): return render_template('errors/403.html'),403

@app.errorhandler(500)
def e500(e):
    import traceback
    print("--- 500 INTERNAL SERVER ERROR ---")
    traceback.print_exc()
    return render_template('errors/500.html'), 500

@app.errorhandler(503)
def e503(e):
    return jsonify({'status': 'starting', 'message': 'Server is initializing, please retry in a moment.'}), 503

# ─── HEALTH CHECK ───────────────────────────────────────────────────
@app.route('/health')
def health_check():
    """Health endpoint — returns ok immediately; pings DB once initialized."""
    if _db_initialized:
        try:
            get_db().execute("SELECT 1").fetchone()
            return jsonify({'status': 'ok', 'db': 'connected'}), 200
        except Exception as e:
            return jsonify({'status': 'degraded', 'db': str(e)}), 200
    return jsonify({'status': 'starting'}), 200

# ─── DB INIT ON FIRST REQUEST (for Gunicorn workers) ────────────────
_db_initialized = False
_db_init_lock = threading.Lock()

@app.before_request
def ensure_db_initialized():
    global _db_initialized
    if _db_initialized:
        return
    # Always respond immediately to health/HEAD probes
    if request.method == 'HEAD' or request.path in ('/health', '/favicon.ico'):
        return
    with _db_init_lock:
        if _db_initialized:  # double-check after acquiring lock
            return
        try:
            init_db()
            _db_initialized = True
            print(" DB initialized successfully on first request")
        except Exception as e:
            print(f"DB init error (will retry): {e}")
            # Return a 503 so the load balancer retries instead of getting a 500
            from flask import abort as _abort
            _abort(503)

# NOTE: Do NOT call pg_pool.open() here at module level.
# It is opened lazily inside _ensure_pool_open() on the first real request.
# This prevents Gunicorn worker fork/startup race conditions.

@app.route('/about')
def about_page():
    return render_template('legal/about.html')

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=os.environ.get('PORT', 5002))
