"""
EduRec v2 - Enhanced E-Learning Recommendation System
======================================================
New Features:
- YouTube Video Player
- PDF Certificate Generation
- Bookmark System
- Dark Mode Support
- Learning Path
- Better Dashboard with Charts
- Profile Picture Upload
- Notes System
- Enhanced Admin
"""

from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify, send_file, make_response)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3
import os
import json
import io
from functools import wraps
from datetime import datetime, timedelta
from model.recommender import recommender

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'edurec-v2-secret-2024-xyz')

DB_PATH = 'database.db'
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ═══════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT UNIQUE NOT NULL,
            email       TEXT UNIQUE NOT NULL,
            password    TEXT NOT NULL,
            role        TEXT DEFAULT 'student',
            interests   TEXT DEFAULT '',
            level       TEXT DEFAULT 'Beginner',
            avatar      TEXT DEFAULT '',
            dark_mode   INTEGER DEFAULT 0,
            streak      INTEGER DEFAULT 0,
            last_active TEXT DEFAULT '',
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS enrollments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            course_id   INTEGER NOT NULL,
            enrolled_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            completed   INTEGER DEFAULT 0,
            progress    INTEGER DEFAULT 0,
            UNIQUE(user_id, course_id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS ratings (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            course_id  INTEGER NOT NULL,
            rating     REAL NOT NULL CHECK(rating >= 1 AND rating <= 5),
            review     TEXT DEFAULT '',
            rated_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, course_id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS bookmarks (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            course_id  INTEGER NOT NULL,
            saved_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, course_id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS notes (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL,
            course_id  INTEGER NOT NULL,
            content    TEXT DEFAULT '',
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, course_id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS certificates (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            course_id    INTEGER NOT NULL,
            issued_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            cert_id      TEXT UNIQUE,
            UNIQUE(user_id, course_id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
    ''')

    try:
        cur.execute('''INSERT OR IGNORE INTO users (username, email, password, role)
                       VALUES (?, ?, ?, ?)''',
                    ('admin', 'admin@elearn.com',
                     generate_password_hash('admin123'), 'admin'))
    except Exception:
        pass

    conn.commit()
    conn.close()


# ═══════════════════════════════════════════
# DECORATORS & HELPERS
# ═══════════════════════════════════════════

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to continue.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'admin':
            flash('Admin access required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_user(user_id):
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return dict(user) if user else None


def get_user_history(user_id):
    conn = get_db()
    rows = conn.execute(
        'SELECT course_id FROM enrollments WHERE user_id = ? ORDER BY enrolled_at DESC',
        (user_id,)
    ).fetchall()
    conn.close()
    return [r['course_id'] for r in rows]


def get_all_ratings():
    conn = get_db()
    rows = conn.execute('SELECT user_id, course_id, rating FROM ratings').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_streak(user_id):
    conn = get_db()
    user = conn.execute('SELECT streak, last_active FROM users WHERE id=?', (user_id,)).fetchone()
    today = datetime.now().strftime('%Y-%m-%d')
    if user:
        last = user['last_active']
        streak = user['streak'] or 0
        if last == today:
            pass
        elif last == (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d'):
            streak += 1
        else:
            streak = 1
        conn.execute('UPDATE users SET streak=?, last_active=? WHERE id=?',
                     (streak, today, user_id))
        conn.commit()
    conn.close()


def generate_cert_id(user_id, course_id):
    import hashlib
    raw = f"EDUREC-{user_id}-{course_id}-{datetime.now().year}"
    return "CERT-" + hashlib.md5(raw.encode()).hexdigest()[:12].upper()


# ═══════════════════════════════════════════
# AUTH ROUTES
# ═══════════════════════════════════════════

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username  = request.form['username'].strip()
        email     = request.form['email'].strip()
        password  = request.form['password']
        interests = request.form.get('interests', '').strip()
        level     = request.form.get('level', 'Beginner')

        if not username or not email or not password:
            flash('All fields required.', 'danger')
            return render_template('register.html', categories=recommender.get_categories())

        conn = get_db()
        try:
            conn.execute(
                'INSERT INTO users (username,email,password,interests,level) VALUES (?,?,?,?,?)',
                (username, email, generate_password_hash(password), interests, level)
            )
            conn.commit()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username or email already exists.', 'danger')
        finally:
            conn.close()

    return render_template('register.html', categories=recommender.get_categories())


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email    = request.form['email'].strip()
        password = request.form['password']
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password'], password):
            session['user_id']  = user['id']
            session['username'] = user['username']
            session['role']     = user['role']
            session['dark_mode']= user['dark_mode']
            update_streak(user['id'])
            flash(f'Welcome back, {user["username"]}! 🎓', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))


# ═══════════════════════════════════════════
# MAIN ROUTES
# ═══════════════════════════════════════════

@app.route('/dashboard')
@login_required
def dashboard():
    user    = get_user(session['user_id'])
    history = get_user_history(session['user_id'])
    ratings = get_all_ratings()

    rec_ids = recommender.hybrid_recommend(
        user_id=session['user_id'],
        user_interests=user.get('interests', ''),
        learning_history=history,
        all_ratings=ratings,
        top_n=8,
        user_level=user.get('level', 'Beginner')
    )
    recommendations = recommender.get_courses_by_ids(rec_ids)
    trending = recommender.get_trending_courses(4)

    enrolled_courses = []
    if history:
        conn = get_db()
        for cid in history[:6]:
            course = recommender.get_course_by_id(cid)
            if course:
                enroll = conn.execute(
                    'SELECT * FROM enrollments WHERE user_id=? AND course_id=?',
                    (session['user_id'], cid)
                ).fetchone()
                if enroll:
                    course['progress'] = enroll['progress']
                    course['completed'] = enroll['completed']
                enrolled_courses.append(course)
        conn.close()

    conn = get_db()
    rating_count = conn.execute(
        'SELECT COUNT(*) as c FROM ratings WHERE user_id=?', (session['user_id'],)
    ).fetchone()['c']
    bookmark_count = conn.execute(
        'SELECT COUNT(*) as c FROM bookmarks WHERE user_id=?', (session['user_id'],)
    ).fetchone()['c']
    cert_count = conn.execute(
        'SELECT COUNT(*) as c FROM certificates WHERE user_id=?', (session['user_id'],)
    ).fetchone()['c']
    completed_count = conn.execute(
        'SELECT COUNT(*) as c FROM enrollments WHERE user_id=? AND completed=1',
        (session['user_id'],)
    ).fetchone()['c']
    conn.close()

    stats = {
        'enrolled': len(history),
        'ratings': rating_count,
        'bookmarks': bookmark_count,
        'certificates': cert_count,
        'completed': completed_count,
        'streak': user.get('streak', 0),
        'recommendations': len(recommendations)
    }

    return render_template('dashboard.html',
                           user=user,
                           recommendations=recommendations,
                           enrolled_courses=enrolled_courses,
                           trending=trending,
                           stats=stats)


@app.route('/courses')
@login_required
def courses():
    query      = request.args.get('q', '')
    category   = request.args.get('category', '')
    difficulty = request.args.get('difficulty', '')

    if query:
        all_courses = recommender.search_courses(query)
    else:
        all_courses = recommender.get_all_courses()

    if category:
        all_courses = [c for c in all_courses if c['category'] == category]
    if difficulty:
        all_courses = [c for c in all_courses if c['difficulty'] == difficulty]

    history = set(get_user_history(session['user_id']))
    conn = get_db()
    bookmarks = set(r['course_id'] for r in conn.execute(
        'SELECT course_id FROM bookmarks WHERE user_id=?', (session['user_id'],)
    ).fetchall())
    conn.close()

    for course in all_courses:
        course['enrolled'] = course['course_id'] in history
        course['bookmarked'] = course['course_id'] in bookmarks

    return render_template('courses.html',
                           courses=all_courses,
                           categories=recommender.get_categories(),
                           difficulties=recommender.get_difficulties(),
                           query=query,
                           selected_category=category,
                           selected_difficulty=difficulty)


@app.route('/course/<int:course_id>')
@login_required
def course_detail(course_id):
    course = recommender.get_course_by_id(course_id)
    if not course:
        flash('Course not found.', 'danger')
        return redirect(url_for('courses'))

    conn = get_db()
    enrolled = conn.execute(
        'SELECT * FROM enrollments WHERE user_id=? AND course_id=?',
        (session['user_id'], course_id)
    ).fetchone()

    user_rating = conn.execute(
        'SELECT * FROM ratings WHERE user_id=? AND course_id=?',
        (session['user_id'], course_id)
    ).fetchone()

    bookmarked = conn.execute(
        'SELECT id FROM bookmarks WHERE user_id=? AND course_id=?',
        (session['user_id'], course_id)
    ).fetchone()

    user_note = conn.execute(
        'SELECT content FROM notes WHERE user_id=? AND course_id=?',
        (session['user_id'], course_id)
    ).fetchone()

    certificate = conn.execute(
        'SELECT * FROM certificates WHERE user_id=? AND course_id=?',
        (session['user_id'], course_id)
    ).fetchone()

    reviews = conn.execute(
        '''SELECT r.rating, r.review, r.rated_at, u.username
           FROM ratings r JOIN users u ON r.user_id=u.id
           WHERE r.course_id=? ORDER BY r.rated_at DESC LIMIT 10''',
        (course_id,)
    ).fetchall()
    conn.close()

    similar_ids = recommender.content_based_recommend(course_id, 4)
    similar = recommender.get_courses_by_ids(similar_ids)

    learning_path = recommender.get_learning_path(course['category'])

    return render_template('course_detail.html',
                           course=course,
                           enrolled=dict(enrolled) if enrolled else None,
                           user_rating=dict(user_rating) if user_rating else None,
                           bookmarked=bool(bookmarked),
                           user_note=user_note['content'] if user_note else '',
                           certificate=dict(certificate) if certificate else None,
                           reviews=[dict(r) for r in reviews],
                           similar=similar,
                           learning_path=learning_path)


@app.route('/enroll/<int:course_id>', methods=['POST'])
@login_required
def enroll(course_id):
    conn = get_db()
    try:
        conn.execute(
            'INSERT OR IGNORE INTO enrollments (user_id, course_id) VALUES (?,?)',
            (session['user_id'], course_id)
        )
        conn.commit()
        flash('Successfully enrolled! Start learning 🚀', 'success')
    except Exception as e:
        flash(f'Enrollment failed: {str(e)}', 'danger')
    finally:
        conn.close()
    return redirect(url_for('course_detail', course_id=course_id))


@app.route('/rate', methods=['POST'])
@login_required
def rate_course():
    course_id = int(request.form['course_id'])
    rating    = float(request.form['rating'])
    review    = request.form.get('review', '').strip()

    if not 1 <= rating <= 5:
        flash('Rating must be 1-5.', 'danger')
        return redirect(url_for('course_detail', course_id=course_id))

    conn = get_db()
    conn.execute(
        '''INSERT INTO ratings (user_id,course_id,rating,review) VALUES (?,?,?,?)
           ON CONFLICT(user_id,course_id) DO UPDATE SET rating=?,review=?''',
        (session['user_id'], course_id, rating, review, rating, review)
    )
    conn.commit()
    conn.close()
    flash('Rating submitted! ⭐', 'success')
    return redirect(url_for('course_detail', course_id=course_id))


@app.route('/progress/<int:course_id>', methods=['POST'])
@login_required
def update_progress(course_id):
    progress = min(100, max(0, int(request.form.get('progress', 0))))
    completed = 1 if progress == 100 else 0
    conn = get_db()
    conn.execute(
        'UPDATE enrollments SET progress=?,completed=? WHERE user_id=? AND course_id=?',
        (progress, completed, session['user_id'], course_id)
    )

    # Auto-issue certificate on completion
    if completed:
        cert_id = generate_cert_id(session['user_id'], course_id)
        conn.execute(
            'INSERT OR IGNORE INTO certificates (user_id,course_id,cert_id) VALUES (?,?,?)',
            (session['user_id'], course_id, cert_id)
        )
        conn.commit()
        conn.close()
        return jsonify({'status': 'ok', 'progress': progress,
                        'completed': True, 'cert_issued': True})

    conn.commit()
    conn.close()
    return jsonify({'status': 'ok', 'progress': progress, 'completed': False})


@app.route('/bookmark/<int:course_id>', methods=['POST'])
@login_required
def toggle_bookmark(course_id):
    conn = get_db()
    existing = conn.execute(
        'SELECT id FROM bookmarks WHERE user_id=? AND course_id=?',
        (session['user_id'], course_id)
    ).fetchone()

    if existing:
        conn.execute('DELETE FROM bookmarks WHERE user_id=? AND course_id=?',
                     (session['user_id'], course_id))
        conn.commit()
        conn.close()
        return jsonify({'status': 'removed'})
    else:
        conn.execute('INSERT INTO bookmarks (user_id,course_id) VALUES (?,?)',
                     (session['user_id'], course_id))
        conn.commit()
        conn.close()
        return jsonify({'status': 'saved'})


@app.route('/note/<int:course_id>', methods=['POST'])
@login_required
def save_note(course_id):
    content = request.form.get('content', '').strip()
    conn = get_db()
    conn.execute(
        '''INSERT INTO notes (user_id,course_id,content) VALUES (?,?,?)
           ON CONFLICT(user_id,course_id) DO UPDATE SET content=?,updated_at=CURRENT_TIMESTAMP''',
        (session['user_id'], course_id, content, content)
    )
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})


@app.route('/bookmarks')
@login_required
def bookmarks():
    conn = get_db()
    rows = conn.execute(
        'SELECT course_id FROM bookmarks WHERE user_id=? ORDER BY saved_at DESC',
        (session['user_id'],)
    ).fetchall()
    conn.close()
    course_ids = [r['course_id'] for r in rows]
    saved_courses = recommender.get_courses_by_ids(course_ids)
    return render_template('bookmarks.html', courses=saved_courses)


@app.route('/certificate/<int:course_id>')
@login_required
def download_certificate(course_id):
    conn = get_db()
    cert = conn.execute(
        'SELECT * FROM certificates WHERE user_id=? AND course_id=?',
        (session['user_id'], course_id)
    ).fetchone()
    conn.close()

    if not cert:
        flash('Certificate not available. Complete the course first!', 'warning')
        return redirect(url_for('course_detail', course_id=course_id))

    user    = get_user(session['user_id'])
    course  = recommender.get_course_by_id(course_id)
    cert    = dict(cert)

    # Generate HTML Certificate
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Certificate - {course['title']}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700&family=Open+Sans:wght@300;400;600&display=swap');
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#f5f5f5; display:flex; justify-content:center; align-items:center; min-height:100vh; font-family:'Open Sans',sans-serif; }}
  .cert {{ background:#fff; width:900px; padding:60px; text-align:center; position:relative;
           border:3px solid #4f46e5; box-shadow:0 20px 60px rgba(0,0,0,0.15); }}
  .cert::before {{ content:''; position:absolute; top:15px; left:15px; right:15px; bottom:15px; border:1px solid #c7d2fe; }}
  .logo {{ font-size:3rem; margin-bottom:0.5rem; }}
  .brand {{ font-size:1.8rem; font-weight:700; color:#4f46e5; font-family:'Playfair Display',serif; }}
  .title {{ font-size:1rem; color:#64748b; text-transform:uppercase; letter-spacing:3px; margin:1.5rem 0 0.5rem; }}
  .cert-title {{ font-size:2.8rem; font-weight:700; color:#1e1b4b; font-family:'Playfair Display',serif; margin-bottom:1rem; }}
  .student {{ font-size:2rem; color:#4f46e5; font-family:'Playfair Display',serif; font-weight:700; border-bottom:2px solid #4f46e5; display:inline-block; padding:0 2rem 0.3rem; margin:1rem 0; }}
  .course-name {{ font-size:1.4rem; color:#1e293b; font-weight:600; margin:1rem 0; }}
  .meta {{ display:flex; justify-content:center; gap:3rem; margin:2rem 0; }}
  .meta-item {{ text-align:center; }}
  .meta-label {{ font-size:0.75rem; color:#64748b; text-transform:uppercase; letter-spacing:1px; }}
  .meta-value {{ font-size:1rem; font-weight:600; color:#1e293b; margin-top:0.2rem; }}
  .cert-id {{ font-size:0.8rem; color:#94a3b8; margin-top:2rem; }}
  .seal {{ font-size:4rem; margin-top:1rem; }}
  @media print {{ body {{ background:#fff; }} .cert {{ box-shadow:none; }} }}
</style>
</head>
<body>
<div class="cert">
  <div class="logo">🎓</div>
  <div class="brand">EduRec Learning Platform</div>
  <div class="title">Certificate of Completion</div>
  <div class="cert-title">This certifies that</div>
  <div class="student">{user['username']}</div>
  <p style="color:#475569;margin:0.5rem 0;">has successfully completed the course</p>
  <div class="course-name">"{course['title']}"</div>
  <p style="color:#64748b;font-size:0.9rem;">Difficulty: {course['difficulty']} &nbsp;|&nbsp; Duration: {course['duration_hours']} Hours</p>
  <div class="meta">
    <div class="meta-item">
      <div class="meta-label">Instructor</div>
      <div class="meta-value">{course['instructor']}</div>
    </div>
    <div class="meta-item">
      <div class="meta-label">Issue Date</div>
      <div class="meta-value">{cert['issued_at'][:10]}</div>
    </div>
    <div class="meta-item">
      <div class="meta-label">Category</div>
      <div class="meta-value">{course['category']}</div>
    </div>
  </div>
  <div class="seal">🏅</div>
  <div class="cert-id">Certificate ID: {cert['cert_id']}</div>
  <p style="margin-top:0.5rem;font-size:0.75rem;color:#94a3b8;">Verify at: edurec.onrender.com/verify/{cert['cert_id']}</p>
  <div style="margin-top:1.5rem;">
    <button onclick="window.print()" style="background:#4f46e5;color:#fff;border:none;padding:0.7rem 2rem;border-radius:8px;font-size:1rem;cursor:pointer;">🖨️ Print / Save PDF</button>
  </div>
</div>
</body>
</html>"""

    response = make_response(html)
    response.headers['Content-Type'] = 'text/html'
    return response


@app.route('/verify/<cert_id>')
def verify_certificate(cert_id):
    conn = get_db()
    cert = conn.execute('SELECT * FROM certificates WHERE cert_id=?', (cert_id,)).fetchone()
    conn.close()
    if cert:
        cert = dict(cert)
        user   = get_user(cert['user_id'])
        course = recommender.get_course_by_id(cert['course_id'])
        return render_template('verify_cert.html', cert=cert, user=user, course=course, valid=True)
    return render_template('verify_cert.html', valid=False)


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = get_user(session['user_id'])
    if request.method == 'POST':
        interests = request.form.get('interests', '').strip()
        level     = request.form.get('level', 'Beginner')
        dark_mode = 1 if request.form.get('dark_mode') else 0

        # Handle avatar upload
        avatar = user.get('avatar', '')
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"avatar_{session['user_id']}.{file.filename.rsplit('.',1)[1]}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                avatar = filename

        conn = get_db()
        conn.execute(
            'UPDATE users SET interests=?,level=?,dark_mode=?,avatar=? WHERE id=?',
            (interests, level, dark_mode, avatar, session['user_id'])
        )
        conn.commit()
        conn.close()
        session['dark_mode'] = dark_mode
        flash('Profile updated! ✅', 'success')
        return redirect(url_for('profile'))

    conn = get_db()
    certs = conn.execute(
        'SELECT * FROM certificates WHERE user_id=?',
        (session['user_id'],)
    ).fetchall()
    conn.close()

    user_certs = []
    for c in certs:
        c = dict(c)
        course = recommender.get_course_by_id(c['course_id'])
        if course:
            c['course_title'] = course['title']
            user_certs.append(c)

    return render_template('profile.html', user=user, certificates=user_certs)


@app.route('/toggle-dark', methods=['POST'])
@login_required
def toggle_dark():
    dark = 1 if session.get('dark_mode') == 0 else 0
    session['dark_mode'] = dark
    conn = get_db()
    conn.execute('UPDATE users SET dark_mode=? WHERE id=?', (dark, session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'dark_mode': dark})


# ═══════════════════════════════════════════
# ADMIN ROUTES
# ═══════════════════════════════════════════

@app.route('/admin')
@login_required
@admin_required
def admin():
    conn = get_db()
    users_count   = conn.execute('SELECT COUNT(*) as c FROM users').fetchone()['c']
    enroll_count  = conn.execute('SELECT COUNT(*) as c FROM enrollments').fetchone()['c']
    ratings_count = conn.execute('SELECT COUNT(*) as c FROM ratings').fetchone()['c']
    cert_count    = conn.execute('SELECT COUNT(*) as c FROM certificates').fetchone()['c']
    recent_users  = conn.execute('SELECT * FROM users ORDER BY created_at DESC LIMIT 10').fetchall()
    top_courses   = conn.execute(
        'SELECT course_id, COUNT(*) as cnt FROM enrollments GROUP BY course_id ORDER BY cnt DESC LIMIT 5'
    ).fetchall()
    conn.close()

    top_courses_detail = []
    for tc in top_courses:
        course = recommender.get_course_by_id(tc['course_id'])
        if course:
            course['enroll_count'] = tc['cnt']
            top_courses_detail.append(course)

    stats = {
        'users': users_count,
        'enrollments': enroll_count,
        'ratings': ratings_count,
        'courses': len(recommender.get_all_courses()),
        'certificates': cert_count
    }
    return render_template('admin.html',
                           stats=stats,
                           recent_users=[dict(u) for u in recent_users],
                           top_courses=top_courses_detail)


@app.route('/admin/add-course', methods=['GET', 'POST'])
@login_required
@admin_required
def add_course():
    if request.method == 'POST':
        title      = request.form['title'].strip()
        desc       = request.form['description'].strip()
        category   = request.form['category'].strip()
        difficulty = request.form['difficulty']
        duration   = int(request.form.get('duration_hours', 10))
        tags       = request.form.get('tags', '').strip()
        instructor = request.form.get('instructor', '').strip()
        youtube    = request.form.get('youtube_url', '').strip()

        # Convert YouTube URL to embed format
        if 'watch?v=' in youtube:
            youtube = youtube.replace('watch?v=', 'embed/')
        elif 'youtu.be/' in youtube:
            vid_id = youtube.split('youtu.be/')[-1]
            youtube = f'https://www.youtube.com/embed/{vid_id}'

        courses_df = recommender.courses_df
        new_id = int(courses_df['course_id'].max()) + 1
        new_row = {
            'course_id': new_id,
            'title': title,
            'description': desc,
            'category': category,
            'difficulty': difficulty,
            'duration_hours': duration,
            'rating': 4.0,
            'tags': tags,
            'instructor': instructor,
            'youtube_url': youtube,
            'thumbnail_color': '4f46e5'
        }
        new_df = courses_df._append(new_row, ignore_index=True)
        new_df.to_csv('data/courses.csv', index=False)
        recommender.reload()
        flash(f'Course "{title}" added! 🎉', 'success')
        return redirect(url_for('admin'))

    return render_template('add_course.html',
                           categories=recommender.get_categories(),
                           difficulties=recommender.get_difficulties())


# ═══════════════════════════════════════════
# API ROUTES
# ═══════════════════════════════════════════

@app.route('/api/recommendations')
@login_required
def api_recommendations():
    user    = get_user(session['user_id'])
    history = get_user_history(session['user_id'])
    ratings = get_all_ratings()
    rec_ids = recommender.hybrid_recommend(
        user_id=session['user_id'],
        user_interests=user.get('interests', ''),
        learning_history=history,
        all_ratings=ratings,
        top_n=10,
        user_level=user.get('level', 'Beginner')
    )
    return jsonify({'status': 'ok', 'recommendations': recommender.get_courses_by_ids(rec_ids)})


@app.route('/api/search')
def api_search():
    query = request.args.get('q', '')
    return jsonify({'status': 'ok', 'results': recommender.search_courses(query, 8)})


@app.route('/api/similar/<int:course_id>')
def api_similar(course_id):
    similar_ids = recommender.content_based_recommend(course_id, 5)
    return jsonify({'status': 'ok', 'similar': recommender.get_courses_by_ids(similar_ids)})


@app.route('/api/stats')
@login_required
def api_stats():
    conn = get_db()
    # Category distribution
    rows = conn.execute(
        'SELECT course_id, COUNT(*) as cnt FROM enrollments WHERE user_id=? GROUP BY course_id',
        (session['user_id'],)
    ).fetchall()
    conn.close()
    categories = {}
    for row in rows:
        course = recommender.get_course_by_id(row['course_id'])
        if course:
            cat = course['category']
            categories[cat] = categories.get(cat, 0) + 1
    return jsonify({'categories': categories})


# ═══════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=5000, debug=True)
