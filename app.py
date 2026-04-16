from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory
import sqlite3
from pathlib import Path
import os
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image
import time
from datetime import datetime, timedelta
import json

app = Flask(__name__)
# simple secret for session cookies; override via env var in production
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret")
DATABASE = Path(__file__).parent / "data.db"
UPLOAD_FOLDER = Path(__file__).parent / 'static' / 'uploads' / 'avatars'
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2 MB
app.config['MAX_CONTENT_LENGTH'] = MAX_AVATAR_SIZE


def normalize_username(raw_username):
    """Normalize username input so case does not matter and format is Title-like."""
    if not raw_username:
        return ''
    cleaned = ' '.join(raw_username.strip().split())
    cleaned = cleaned.lower()
    return cleaned.capitalize()


# initialize database if not exists

def init_db():
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()
    # user table for simple login
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT,
            display_name TEXT,
            bio TEXT,
            avatar_path TEXT,
            role TEXT DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    # migrate users table to include profile fields, role, and password hash if missing
    c.execute("PRAGMA table_info(users)")
    user_cols = [r[1] for r in c.fetchall()]
    if 'password_hash' not in user_cols:
        c.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
    if 'display_name' not in user_cols:
        c.execute("ALTER TABLE users ADD COLUMN display_name TEXT")
    if 'bio' not in user_cols:
        c.execute("ALTER TABLE users ADD COLUMN bio TEXT")
    if 'avatar_path' not in user_cols:
        c.execute("ALTER TABLE users ADD COLUMN avatar_path TEXT")
    if 'role' not in user_cols:
        c.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")

    # sessions now belong to users; check for existing table and migrate if needed
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'")
    if c.fetchone():
        # table exists; see if user_id column present
        c.execute("PRAGMA table_info(sessions)")
        cols = [r[1] for r in c.fetchall()]
        if 'user_id' not in cols:
            # add column with default to ensure existing session rows remain valid
            c.execute("ALTER TABLE sessions ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")
    else:
        c.execute(
            """
            CREATE TABLE sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                drill TEXT NOT NULL,
                duration INTEGER NOT NULL,
                notes TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
    
    # goals table for tracking objectives
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            target_value INTEGER NOT NULL,
            target_type TEXT NOT NULL,
            start_date TEXT NOT NULL,
            due_date TEXT,
            completed INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    
    # achievements/badges table
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            badge_name TEXT NOT NULL,
            description TEXT,
            icon_emoji TEXT DEFAULT '🏆',
            unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )

    # direct messaging for friend chat
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            recipient_id INTEGER NOT NULL,
            body TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            read INTEGER DEFAULT 0,
            FOREIGN KEY(sender_id) REFERENCES users(id),
            FOREIGN KEY(recipient_id) REFERENCES users(id)
        )
        """
    )

    def ensure_user(username, password, display_name, role, bio):
        normalized = normalize_username(username)
        existing = c.execute('SELECT id, role, username FROM users WHERE LOWER(username) = ?', (normalized.lower(),)).fetchone()
        password_hash = generate_password_hash(password)
        if existing:
            if existing[1] != role:
                c.execute('UPDATE users SET role = ? WHERE id = ?', (role, existing[0]))
            if existing[2] != normalized:
                c.execute('UPDATE users SET username = ? WHERE id = ?', (normalized, existing[0]))
        else:
            c.execute(
                'INSERT INTO users (username, password_hash, display_name, bio, role, created_at) VALUES (?, ?, ?, ?, ?, ?)',
                (normalized, password_hash, display_name, bio, role, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            )

    ensure_user('admin', 'hecknoo', 'TrackPro Admin', 'admin', 'Platform administrator')
    ensure_user('coach', 'Coach123!', 'Coach Morgan', 'coach', 'Your expert coach. Message anytime.')
    
    conn.commit()
    conn.close()


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def get_analytics_data(user_id, conn):
    """Compute advanced analytics: weekly/monthly trends, best drills, averages"""
    sessions = conn.execute(
        "SELECT * FROM sessions WHERE user_id = ? ORDER BY date ASC", (user_id,)
    ).fetchall()
    
    if not sessions:
        return {
            'weekly_trends': [],
            'monthly_trends': [],
            'best_drills': [],
            'weekly_avg': 0,
            'monthly_avg': 0
        }
    
    # Convert to list of dicts for easier processing
    sessions_list = [dict(s) for s in sessions]
    today = datetime.now()
    last_week = today - timedelta(days=7)
    last_month = today - timedelta(days=30)
    
    # Weekly data (last 7 days)
    weekly_data = {}
    for day in range(7):
        date_key = (today - timedelta(days=day)).strftime("%a")
        weekly_data[date_key] = 0
    
    for s in sessions_list:
        try:
            s_date = datetime.strptime(s['date'], "%Y-%m-%d")
            if s_date >= last_week:
                day_name = s_date.strftime("%a")
                if day_name in weekly_data:
                    weekly_data[day_name] += s['duration']
        except:
            pass
    
    # Monthly data (by week)
    monthly_data = {}
    for week in range(4):
        week_start = (today - timedelta(days=7 * (3 - week)))
        week_key = f"Week {4 - week}"
        monthly_data[week_key] = 0
    
    for s in sessions_list:
        try:
            s_date = datetime.strptime(s['date'], "%Y-%m-%d")
            if s_date >= last_month:
                weeks_ago = (today - s_date).days // 7
                month_idx = 3 - weeks_ago
                if 0 <= month_idx < 4:
                    week_key = f"Week {month_idx + 1}"
                    if week_key in monthly_data:
                        monthly_data[week_key] += s['duration']
        except:
            pass
    
    # Best drills
    drill_totals = {}
    drill_counts = {}
    for s in sessions_list:
        drill = s['drill']
        drill_totals[drill] = drill_totals.get(drill, 0) + s['duration']
        drill_counts[drill] = drill_counts.get(drill, 0) + 1
    
    best_drills = sorted(
        [(drill, drill_totals[drill], drill_counts[drill]) for drill in drill_totals],
        key=lambda x: x[1],
        reverse=True
    )[:5]
    
    # Averages
    total_duration = sum(s['duration'] for s in sessions_list)
    weekly_avg = sum(weekly_data.values()) / 7 if weekly_data else 0
    monthly_avg = total_duration / max(len(sessions_list), 1)
    
    return {
        'weekly_trends': [{'day': day, 'minutes': minutes} for day, minutes in weekly_data.items()],
        'monthly_trends': [{'week': week, 'minutes': minutes} for week, minutes in monthly_data.items()],
        'best_drills': [{'drill': drill, 'total': total, 'count': count} for drill, total, count in best_drills],
        'weekly_avg': round(weekly_avg, 1),
        'monthly_avg': round(monthly_avg, 1)
    }


@app.route("/", methods=["GET", "POST"])
def index():
    # require login
    if "user_id" not in session:
        return redirect(url_for("login"))
    user_id = session["user_id"]

    if request.method == "POST":
        date = request.form.get("date")
        drill = request.form.get("drill")
        duration = request.form.get("duration")
        notes = request.form.get("notes")
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO sessions (user_id, date, drill, duration, notes) VALUES (?, ?, ?, ?, ?)",
            (user_id, date, drill, duration, notes),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("index"))

    conn = get_db_connection()
    user_row = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    avatar_url = None
    display_name = None
    if user_row:
        avatar_path = user_row['avatar_path']
        display_name = user_row['display_name'] or user_row['username']
        if avatar_path:
            # ensure path is web relative
            avatar_url = f"/static/uploads/avatars/{avatar_path}"
    sessions = conn.execute(
        "SELECT * FROM sessions WHERE user_id = ? ORDER BY date DESC", (user_id,)
    ).fetchall()

    # derive simple statistics
    stats = {
        'total_sessions': len(sessions),
        'total_minutes': sum(s['duration'] for s in sessions) if sessions else 0,
    }

    # prepare data for chart: count per drill
    chart_data = {}
    for s in sessions:
        chart_data[s['drill']] = chart_data.get(s['drill'], 0) + s['duration']

    leaderboard_top = conn.execute(
        """
        SELECT u.id,
               COALESCE(NULLIF(u.display_name, ''), u.username) AS display_name,
               COUNT(s.id) AS total_sessions,
               COALESCE(SUM(s.duration), 0) AS total_minutes
        FROM users u
        LEFT JOIN sessions s ON u.id = s.user_id
        WHERE COALESCE(u.role, 'user') NOT IN ('admin', 'coach')
        GROUP BY u.id
        ORDER BY total_minutes DESC, total_sessions DESC
        LIMIT 5
        """
    ).fetchall()

    conn.close()
    return render_template(
        "index.html",
        sessions=sessions,
        username=session.get("username"),
        display_name=display_name,
        avatar_url=avatar_url,
        stats=stats,
        chart_data=chart_data,
        leaderboard_top=leaderboard_top,
    )

# initialize DB when module is imported (necessary for gunicorn on Render)
with app.app_context():
    init_db()


@app.route('/analytics')
def analytics():
    """Advanced analytics page"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    conn = get_db_connection()
    
    analytics_data = get_analytics_data(user_id, conn)
    user_row = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    
    conn.close()
    return render_template('analytics.html', 
                         username=session.get('username'),
                         analytics=analytics_data,
                         user=user_row)


@app.route('/leaderboard')
def leaderboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT u.id,
               COALESCE(NULLIF(u.display_name, ''), u.username) AS display_name,
               COUNT(s.id) AS total_sessions,
               COALESCE(SUM(s.duration), 0) AS total_minutes
        FROM users u
        LEFT JOIN sessions s ON u.id = s.user_id
        WHERE COALESCE(u.role, 'user') NOT IN ('admin', 'coach')
        GROUP BY u.id
        ORDER BY total_minutes DESC, total_sessions DESC
        """
    ).fetchall()

    leaderboard = [dict(row) for row in rows]
    current_rank = next((idx + 1 for idx, row in enumerate(leaderboard) if row['id'] == user_id), None)
    conn.close()

    return render_template('leaderboard.html',
                         username=session.get('username'),
                         leaderboard=leaderboard,
                         current_rank=current_rank,
                         current_user_id=user_id)


@app.route('/chat')
def chat():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    conn = get_db_connection()
    users = conn.execute(
        """
        SELECT id,
               COALESCE(NULLIF(display_name, ''), username) AS display_name,
               role
        FROM users
        WHERE id != ?
        ORDER BY display_name ASC
        """,
        (user_id,)
    ).fetchall()

    messages = conn.execute(
        """
        SELECT u.id,
               COALESCE(NULLIF(u.display_name, ''), u.username) AS display_name,
               (SELECT body FROM messages m2
                WHERE ((m2.sender_id = ? AND m2.recipient_id = u.id)
                       OR (m2.sender_id = u.id AND m2.recipient_id = ?))
                ORDER BY datetime(m2.created_at) DESC
                LIMIT 1) AS preview,
               (SELECT created_at FROM messages m2
                WHERE ((m2.sender_id = ? AND m2.recipient_id = u.id)
                       OR (m2.sender_id = u.id AND m2.recipient_id = ?))
                ORDER BY datetime(m2.created_at) DESC
                LIMIT 1) AS last_at,
               (SELECT COUNT(*) FROM messages m2
                WHERE m2.sender_id = u.id AND m2.recipient_id = ? AND m2.read = 0) AS unread
        FROM users u
        WHERE u.id != ?
        ORDER BY last_at DESC
        """,
        (user_id, user_id, user_id, user_id, user_id, user_id)
    ).fetchall()

    conn.close()
    return render_template('chat.html', username=session.get('username'), users=messages)


@app.route('/chat/<int:recipient_id>', methods=['GET', 'POST'])
def chat_with(recipient_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    conn = get_db_connection()
    recipient = conn.execute('SELECT id, username, display_name, role FROM users WHERE id = ?', (recipient_id,)).fetchone()
    if not recipient:
        conn.close()
        return redirect(url_for('chat'))

    if request.method == 'POST':
        body = request.form.get('body', '').strip()
        if body:
            conn.execute(
                'INSERT INTO messages (sender_id, recipient_id, body, created_at) VALUES (?, ?, ?, ?)',
                (user_id, recipient_id, body, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            )
            conn.commit()
        return redirect(url_for('chat_with', recipient_id=recipient_id))

    conn.execute(
        'UPDATE messages SET read = 1 WHERE sender_id = ? AND recipient_id = ? AND read = 0',
        (recipient_id, user_id)
    )
    conn.commit()

    conversation = conn.execute(
        """
        SELECT m.*, u.username AS sender_username, COALESCE(NULLIF(u.display_name, ''), u.username) AS sender_name
        FROM messages m
        JOIN users u ON u.id = m.sender_id
        WHERE (m.sender_id = ? AND m.recipient_id = ?) OR (m.sender_id = ? AND m.recipient_id = ?)
        ORDER BY datetime(m.created_at) ASC
        """,
        (user_id, recipient_id, recipient_id, user_id)
    ).fetchall()

    users = conn.execute(
        """
        SELECT id,
               COALESCE(NULLIF(display_name, ''), username) AS display_name,
               role
        FROM users
        WHERE id != ?
        ORDER BY display_name ASC
        """,
        (user_id,)
    ).fetchall()

    conn.close()
    return render_template('chat.html', username=session.get('username'), users=users, conversation=conversation, selected_user=recipient, current_user_id=user_id)


@app.route('/goals', methods=['GET', 'POST'])
def goals():
    """Goals management page"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    conn = get_db_connection()
    
    if request.method == 'POST':
        name = request.form.get('goal_name')
        target_value = request.form.get('target_value')
        target_type = request.form.get('target_type')
        due_date = request.form.get('due_date')
        
        if not name or not target_value or not target_type:
            flash('All fields required', 'danger')
        else:
            try:
                conn.execute(
                    'INSERT INTO goals (user_id, name, target_value, target_type, start_date, due_date) VALUES (?, ?, ?, ?, ?, ?)',
                    (user_id, name, int(target_value), target_type, datetime.now().strftime("%Y-%m-%d"), due_date)
                )
                conn.commit()
                flash('Goal created!', 'success')
            except Exception as e:
                flash(f'Error: {str(e)}', 'danger')
    
    user_goals = conn.execute(
        'SELECT * FROM goals WHERE user_id = ? ORDER BY due_date ASC', (user_id,)
    ).fetchall()
    
    user_row = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    
    return render_template('goals.html', 
                         goals=user_goals,
                         username=session.get('username'),
                         user=user_row)


@app.route('/goal/complete/<int:goal_id>', methods=['POST'])
def complete_goal(goal_id):
    """Mark goal as complete and award badge"""
    if 'user_id' not in session:
        return jsonify({'error': 'not_logged_in'}), 401
    user_id = session['user_id']
    conn = get_db_connection()
    
    goal = conn.execute('SELECT * FROM goals WHERE id = ? AND user_id = ?', (goal_id, user_id)).fetchone()
    if not goal:
        conn.close()
        return jsonify({'error': 'goal_not_found'}), 404
    
    # Mark complete
    conn.execute('UPDATE goals SET completed = 1 WHERE id = ?', (goal_id,))
    
    # Award badge
    badge_name = f"✓ {goal['name']}"
    conn.execute(
        'INSERT INTO achievements (user_id, badge_name, description, icon_emoji) VALUES (?, ?, ?, ?)',
        (user_id, badge_name, f"Completed goal: {goal['name']}", '🏆')
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True})


@app.route('/badges')
def badges():
    """View achievements/badges"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    conn = get_db_connection()
    
    achievements = conn.execute(
        'SELECT * FROM achievements WHERE user_id = ? ORDER BY unlocked_at DESC', (user_id,)
    ).fetchall()
    
    # Get all sessions for this month
    today = datetime.now()
    month_start = today.replace(day=1)
    
    total_sessions = conn.execute(
        'SELECT COUNT(*) as count FROM sessions WHERE user_id = ?', (user_id,)
    ).fetchone()['count']
    
    monthly_sessions = conn.execute(
        'SELECT COUNT(*) as count FROM sessions WHERE user_id = ? AND date >= ?',
        (user_id, month_start.strftime("%Y-%m-%d"))
    ).fetchone()['count']
    
    # Professional badge ranks based on milestones
    ranks_to_check = [
        {
            'name': 'Pro',
            'icon': 'pro',
            'description': 'Master - 5 sessions this month',
            'condition': monthly_sessions >= 5,
            'achievement_name': 'Pro Trainer'
        },
        {
            'name': 'Legendary',
            'icon': 'legendary',
            'description': 'Legendary - 10 total sessions',
            'condition': total_sessions >= 10,
            'achievement_name': 'Legendary Trainer'
        },
        {
            'name': 'Champion',
            'icon': 'champion',
            'description': 'Champion - 15 total sessions',
            'condition': total_sessions >= 15,
            'achievement_name': 'Champion Trainer'
        }
    ]
    
    # Award rank badges
    for rank in ranks_to_check:
        if rank['condition']:
            existing = conn.execute(
                'SELECT * FROM achievements WHERE user_id = ? AND badge_name = ?',
                (user_id, rank['achievement_name'])
            ).fetchone()
            if not existing:
                conn.execute(
                    'INSERT INTO achievements (user_id, badge_name, description, icon_emoji) VALUES (?, ?, ?, ?)',
                    (user_id, rank['achievement_name'], rank['description'], rank['icon'])
                )
    
    # Calculate progress for upcoming badges
    progress = {
        'pro': {
            'current': monthly_sessions,
            'target': 5,
            'progress_percent': min(100, (monthly_sessions / 5) * 100),
            'is_unlocked': monthly_sessions >= 5
        },
        'legendary': {
            'current': total_sessions,
            'target': 10,
            'progress_percent': min(100, (total_sessions / 10) * 100),
            'is_unlocked': total_sessions >= 10
        },
        'champion': {
            'current': total_sessions,
            'target': 15,
            'progress_percent': min(100, (total_sessions / 15) * 100),
            'is_unlocked': total_sessions >= 15
        }
    }
    
    conn.commit()
    conn.close()
    
    return render_template('badges.html',
                         achievements=achievements,
                         total_sessions=total_sessions,
                         monthly_sessions=monthly_sessions,
                         progress=progress,
                         username=session.get('username'))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username_input = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        username = normalize_username(username_input)

        if not username or not password:
            flash('Please provide username and password.', 'danger')
            return render_template('login.html')

        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE LOWER(username) = ?', (username.lower(),)).fetchone()
        conn.close()

        if user:
            if user['password_hash']:
                if check_password_hash(user['password_hash'], password):
                    session['user_id'] = user['id']
                    session['username'] = user['username']
                    return redirect(url_for('index'))
            elif password == '':
                session['user_id'] = user['id']
                session['username'] = user['username']
                flash('Please set a password from your profile.', 'warning')
                return redirect(url_for('index'))

        flash('Invalid username or password', 'danger')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username_input = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        username = normalize_username(username_input)

        if not username_input or not password or not confirm_password:
            flash('Please complete all fields.', 'danger')
            return render_template('register.html')

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('register.html')

        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return render_template('register.html')

        conn = get_db_connection()
        existing = conn.execute('SELECT id FROM users WHERE LOWER(username) = ?', (username.lower(),)).fetchone()
        if existing:
            conn.close()
            flash('Username is already taken.', 'danger')
            return render_template('register.html')

        conn.execute(
            'INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)',
            (username, generate_password_hash(password), datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()
        user = conn.execute('SELECT * FROM users WHERE LOWER(username) = ?', (username.lower(),)).fetchone()
        conn.close()

        session['user_id'] = user['id']
        session['username'] = user['username']
        flash('Account created successfully.', 'success')
        return redirect(url_for('index'))

    return render_template('register.html')


def allowed_file(filename):
    """Validate file extension and size"""
    if not filename or '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False
    # Check file size in request
    if request.content_length and request.content_length > MAX_AVATAR_SIZE:
        return False
    return True


@app.route('/manifest.json')
def manifest():
    """PWA manifest for installation"""
    manifest = {
        "name": "Football Training Tracker",
        "short_name": "TrackPro",
        "description": "Log and track your football training sessions",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#007bff",
        "scope": "/",
        "icons": [
            {
                "src": "/static/icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any"
            },
            {
                "src": "/static/icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable"
            }
        ]
    }
    return jsonify(manifest)


@app.route('/sw.js')
def service_worker():
    """Service worker for offline support"""
    return send_from_directory(Path(__file__).parent / 'static', 'sw.js', mimetype='application/javascript')


@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

    if request.method == 'POST':
        display_name = request.form.get('display_name')
        bio = request.form.get('bio')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if password:
            if password != confirm_password:
                flash('Passwords do not match.', 'danger')
                conn.close()
                return redirect(url_for('profile'))
            if len(password) < 6:
                flash('Password must be at least 6 characters.', 'danger')
                conn.close()
                return redirect(url_for('profile'))
            password_hash = generate_password_hash(password)
        else:
            password_hash = user['password_hash']

        # handle avatar upload
        avatar = request.files.get('avatar')
        avatar_filename = user['avatar_path'] if user else None
        if avatar and avatar.filename:
            if not allowed_file(avatar.filename):
                flash('Invalid image type. Use png/jpg/jpeg/gif.', 'danger')
                conn.close()
                return redirect(url_for('profile'))
            filename = secure_filename(avatar.filename)
            # unique name
            ext = filename.rsplit('.', 1)[1].lower()
            new_name = f'user_{user_id}_{int(time.time())}.{ext}'
            dest = UPLOAD_FOLDER / new_name
            avatar.save(dest)
            # try to resize to 300x300 for consistency
            try:
                img = Image.open(dest)
                img.thumbnail((400, 400))
                img.save(dest)
            except Exception:
                pass
            avatar_filename = new_name

        # update DB
        conn.execute('UPDATE users SET display_name = ?, bio = ?, avatar_path = ?, password_hash = ? WHERE id = ?',
                     (display_name, bio, avatar_filename, password_hash, user_id))
        conn.commit()
        conn.close()
        flash('Profile updated', 'success')
        return redirect(url_for('profile'))

    conn.close()
    return render_template('profile.html', user=user)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/delete/<int:session_id>', methods=['POST'])
def delete_session(session_id):

    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()

    row = conn.execute(
        'SELECT * FROM sessions WHERE id = ? AND user_id = ?',
        (session_id, user_id)
    ).fetchone()

    if not row:
        conn.close()

        # AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'deleted': False}), 404

        flash('Session not found', 'danger')
        return redirect(url_for('index'))

    # store session data for undo
    session_data = dict(row)

    conn.execute(
        'DELETE FROM sessions WHERE id = ? AND user_id = ?',
        (session_id, user_id)
    )

    conn.commit()
    conn.close()

    # if called via JS fetch
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'deleted': True,
            'session': session_data
        })

    # normal form submit
    flash('Session deleted', 'success')
    return redirect(url_for('index'))


@app.route('/restore', methods=['POST'])
def restore_session():
    if 'user_id' not in session:
        return jsonify({'restored': False, 'error': 'not_logged_in'}), 401
    data = request.get_json() or {}
    date = data.get('date')
    drill = data.get('drill')
    duration = data.get('duration')
    notes = data.get('notes')
    user_id = session['user_id']
    if not date or not drill or not duration:
        return jsonify({'restored': False, 'error': 'invalid_data'}), 400
    conn = get_db_connection()
    cur = conn.execute('INSERT INTO sessions (user_id, date, drill, duration, notes) VALUES (?, ?, ?, ?, ?)',
                       (user_id, date, drill, duration, notes))
    conn.commit()
    new_id = cur.lastrowid
    row = conn.execute('SELECT * FROM sessions WHERE id = ?', (new_id,)).fetchone()
    conn.close()
    return jsonify({'restored': True, 'session': dict(row)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

