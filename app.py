import os, functools
from flask import Flask, render_template, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = 'so_tay_gia_su_pro_secret_key_nguyen_trong_huy'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=365)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url or ('sqlite:///' + os.path.join(BASE_DIR, 'tutoring_platform.db'))
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Chống lưu Cache trên trình duyệt điện thoại để bấm Reload là cập nhật ngay lập tức
@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# Bảng tra cứu tự động Mã BIN chuẩn VietQR cho các ngân hàng phổ biến tại Việt Nam
BANK_BIN_MAP = {
    "MB": "970422",
    "VCB": "970436",
    "TCB": "970407",
    "BIDV": "970418",
    "ICB": "970415",
    "ACB": "970416",
    "TPB": "970423",
    "VPB": "970432",
    "VBA": "970405",
    "STB": "970403",
    "HDB": "970437",
    "VIB": "970441",
    "SHB": "970443",
    "MSB": "970426",
    "OCB": "970448"
}

# 1. Bảng Tài khoản Gia sư (Multi-User)
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False, unique=True)
    display_name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    bank_id = db.Column(db.String(20), default="MB")
    bank_bin = db.Column(db.String(20), default="970422")
    account_no = db.Column(db.String(50), default="")
    account_name = db.Column(db.String(100), default="")
    is_admin = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default="pending")  # pending, approved, rejected
    created_at = db.Column(db.DateTime, default=datetime.now)
    students = db.relationship('Student', backref='tutor', cascade="all, delete-orphan", lazy=True)

# 2. Bảng Học sinh (Gắn với user_id của từng Gia sư)
class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    fee_per_session = db.Column(db.Integer, nullable=False)
    color = db.Column(db.String(20), default="#4f46e5")
    lessons = db.relationship('Lesson', backref='student', cascade="all, delete-orphan", lazy=True)

# 3. Bảng Lịch học
class Lesson(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    date = db.Column(db.String(10), nullable=False)       # YYYY-MM-DD
    start_time = db.Column(db.String(5), nullable=False)  # HH:MM
    end_time = db.Column(db.String(5), nullable=False)    # HH:MM
    note = db.Column(db.String(200), default="")
    is_completed = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default="scheduled") # scheduled, completed, cancelled, makeup

def init_database():
    is_postgres = bool(os.environ.get('DATABASE_URL'))
    
    # 1. Tren PostgreSQL: kiem tra va don dep bang neu truoc do co cau truc don le
    if is_postgres:
        try:
            from sqlalchemy import inspect, text as sql_text
            with db.engine.connect() as conn:
                inspector = inspect(conn)
                existing_tables = inspector.get_table_names()
                need_reset = False
                if 'student' in existing_tables:
                    col_names = [c['name'] for c in inspector.get_columns('student')]
                    if 'user_id' not in col_names:
                        need_reset = True
                if 'user' not in existing_tables and '"user"' not in existing_tables:
                    need_reset = True
                    
                if need_reset:
                    print('Dang don dep cac bang cu tren PostgreSQL...')
                    conn.execute(sql_text('DROP TABLE IF EXISTS lesson CASCADE'))
                    conn.execute(sql_text('DROP TABLE IF EXISTS student CASCADE'))
                    conn.execute(sql_text('DROP TABLE IF EXISTS "user" CASCADE'))
                    conn.commit()
        except Exception as e:
            print('Luu y kiem tra bang cu:', e)

    # 2. Tao bang
    db.create_all()

    # 3. Dong bo toan bo gia su, hoc sinh, lich day tu tutoring_platform.db
    sqlite_file = os.path.join(BASE_DIR, 'tutoring_platform.db')
    if os.path.exists(sqlite_file) and User.query.count() == 0:
        try:
            import sqlite3
            conn_seed = sqlite3.connect(sqlite_file)
            c_seed = conn_seed.cursor()

            # Seed toan bo gia su
            c_seed.execute('SELECT id, username, display_name, password_hash, bank_id, bank_bin, account_no, account_name, is_admin, status, created_at FROM user')
            for u in c_seed.fetchall():
                created_val = None
                if u[10]:
                    try:
                        created_val = datetime.strptime(u[10][:19], '%Y-%m-%d %H:%M:%S')
                    except Exception:
                        created_val = datetime.now()
                else:
                    created_val = datetime.now()
                db.session.add(User(
                    id=u[0],
                    username=u[1],
                    display_name=u[2],
                    password_hash=u[3],
                    bank_id=u[4] or 'MB',
                    bank_bin=u[5] or '970422',
                    account_no=u[6] or '',
                    account_name=u[7] or '',
                    is_admin=bool(u[8]),
                    status=u[9] or 'approved',
                    created_at=created_val
                ))
            db.session.commit()

            # Seed toan bo hoc sinh
            c_seed.execute('SELECT id, user_id, name, fee_per_session, color FROM student')
            for s in c_seed.fetchall():
                db.session.add(Student(
                    id=s[0],
                    user_id=s[1],
                    name=s[2],
                    fee_per_session=s[3],
                    color=s[4] or '#4f46e5'
                ))
            db.session.commit()

            # Seed toan bo buoi hoc
            c_seed.execute('SELECT id, student_id, date, start_time, end_time, note, is_completed, status FROM lesson')
            for l in c_seed.fetchall():
                db.session.add(Lesson(
                    id=l[0],
                    student_id=l[1],
                    date=l[2],
                    start_time=l[3],
                    end_time=l[4],
                    note=l[5] or '',
                    is_completed=bool(l[6]),
                    status=l[7] or 'scheduled'
                ))
            db.session.commit()
            conn_seed.close()
            print(f'Da dong bo toan bo: {User.query.count()} gia su, {Student.query.count()} hoc sinh, {Lesson.query.count()} buoi hoc!')

            if is_postgres:
                try:
                    from sqlalchemy import text as sql_text
                    db.session.execute(sql_text('SELECT setval(pg_get_serial_sequence(\'"user"\', \'id\'), coalesce(max(id), 1)) FROM "user"'))
                    db.session.execute(sql_text('SELECT setval(pg_get_serial_sequence(\'student\', \'id\'), coalesce(max(id), 1)) FROM student'))
                    db.session.execute(sql_text('SELECT setval(pg_get_serial_sequence(\'lesson\', \'id\'), coalesce(max(id), 1)) FROM lesson'))
                    db.session.commit()
                    print('Da cap nhat auto-increment sequence PostgreSQL!')
                except Exception as seq_err:
                    print('Luu y sequence:', seq_err)
                    db.session.rollback()

        except Exception as err:
            print('Loi dong bo seed:', err)
            db.session.rollback()

    try:
        huy = User.query.filter_by(username='huy').first()
        if huy:
            huy.is_admin = True
            huy.status = 'approved'
            db.session.commit()
    except Exception:
        db.session.rollback()
    finally:
        db.session.remove()

with app.app_context():
    init_database()

@app.route('/healthz')
def healthz():
    return jsonify({"status": "ok"}), 200

def get_current_user():
    uid = session.get('user_id')
    return db.session.get(User, uid) if uid else None

def admin_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Vui lòng đăng nhập!"}), 401
        if not user.is_admin:
            return jsonify({"error": "Bạn không có quyền quản trị viên!"}), 403
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    return render_template('index.html')

# --- API ĐĂNG KÝ / ĐĂNG NHẬP / CÀI ĐẶT NGÂN HÀNG CHO CÁC GIA SƯ ---
@app.route('/api/auth/me', methods=['GET'])
def auth_me():
    user = get_current_user()
    if not user:
        return jsonify({"logged_in": False})
    
    # Nếu user bị từ chối hoặc đang chờ duyệt thì thu hồi phiên đăng nhập
    if user.status in ('pending', 'rejected'):
        session.pop('user_id', None)
        return jsonify({"logged_in": False, "status": user.status, "error": "Tài khoản chưa được kích hoạt hoặc đã bị khóa!"})

    pending_count = 0
    if user.is_admin:
        pending_count = User.query.filter_by(status='pending').count()

    return jsonify({
        "logged_in": True,
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "is_admin": bool(user.is_admin),
        "status": user.status or "approved",
        "pending_count": pending_count,
        "bank": {
            "BANK_ID": user.bank_id,
            "BIN": user.bank_bin,
            "ACCOUNT_NO": user.account_no,
            "ACCOUNT_NAME": user.account_name
        }
    })

@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.json or {}
    username = data.get('username', '').strip().lower()
    display_name = data.get('display_name', '').strip() or username
    password = data.get('password', '').strip()
    bank_id = data.get('bank_id', 'MB').strip().upper()
    account_no = data.get('account_no', '').strip()
    account_name = data.get('account_name', '').strip().upper()

    if not username or not password:
        return jsonify({"error": "Vui lòng nhập tên đăng nhập và mật khẩu!"}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({"error": "Tên đăng nhập này đã có gia sư khác sử dụng!"}), 400

    bank_bin = BANK_BIN_MAP.get(bank_id, "970422")
    new_user = User(
        username=username,
        display_name=display_name,
        password_hash=generate_password_hash(password),
        bank_id=bank_id,
        bank_bin=bank_bin,
        account_no=account_no,
        account_name=account_name,
        is_admin=False,
        status='pending',
        created_at=datetime.now()
    )
    db.session.add(new_user)
    db.session.commit()
    # Phải chờ Admin duyệt - KHÔNG gán session user_id
    return jsonify({
        "message": "Đăng ký thành công! Tài khoản của bạn đang ở trạng thái 'Chờ phê duyệt'. Vui lòng đợi Quản trị viên (Admin) duyệt mới có thể đăng nhập.",
        "pending": True
    }), 201

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    username = data.get('username', '').strip().lower()
    password = data.get('password', '').strip()

    user = User.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "Sai tên đăng nhập hoặc mật khẩu!"}), 401

    user_status = user.status or 'approved'
    if user_status == 'pending':
        return jsonify({
            "error": "Tài khoản của bạn đang chờ Quản trị viên (Admin) duyệt. Vui lòng liên hệ Admin để được cấp quyền sử dụng!",
            "status": "pending"
        }), 403
    elif user_status == 'rejected':
        return jsonify({
            "error": "Tài khoản của bạn đã bị Quản trị viên từ chối truy cập. Vui lòng liên hệ Admin nếu cần hỗ trợ!",
            "status": "rejected"
        }), 403

    session.permanent = True
    session['user_id'] = user.id
    return jsonify({
        "message": "Đăng nhập thành công!",
        "is_admin": bool(user.is_admin)
    })

@app.route('/api/auth/demo', methods=['POST'])
def demo_login():
    demo_user = User.query.filter_by(username='demo').first()
    if not demo_user:
        demo_user = User(
            username='demo',
            display_name='Gia Sư Trải Nghiệm (Demo)',
            password_hash=generate_password_hash('demo123'),
            bank_id='MB',
            bank_bin='970422',
            account_no='0915154306',
            account_name='GIA SU DEMO',
            is_admin=False,
            status='approved',
            created_at=datetime.now()
        )
        db.session.add(demo_user)
        db.session.commit()
        
        s1 = Student(user_id=demo_user.id, name='Minh Anh (Mẫu)', fee_per_session=200000, color='#4f46e5')
        db.session.add(s1)
        db.session.commit()
        today = datetime.now().strftime("%Y-%m-%d")
        db.session.add(Lesson(
            student_id=s1.id, date=today, start_time='19:30', end_time='21:30',
            note='Ôn tập chuyên đề Hình học', is_completed=True, status='completed'
        ))
        db.session.commit()
    else:
        if demo_user.status != 'approved':
            demo_user.status = 'approved'
            db.session.commit()

    session.permanent = True
    session['user_id'] = demo_user.id
    return jsonify({"message": "Đã vào chế độ trải nghiệm!"})

# --- CÁC API QUẢN TRỊ VIÊN (ADMIN ONLY) ---
@app.route('/api/admin/users', methods=['GET'])
@admin_required
def admin_get_users():
    current_user = get_current_user()
    users = User.query.all()
    # Sắp xếp pending lên đầu tiên, sau đó theo ID giảm dần
    users_sorted = sorted(users, key=lambda u: (0 if u.status == 'pending' else 1, -u.id))
    
    result = []
    for u in users_sorted:
        lesson_cnt = sum(len(s.lessons) for s in u.students)
        result.append({
            "id": u.id,
            "username": u.username,
            "display_name": u.display_name,
            "bank_id": u.bank_id or "MB",
            "account_no": u.account_no or "",
            "account_name": u.account_name or "",
            "is_admin": bool(u.is_admin),
            "status": u.status or "approved",
            "created_at": u.created_at.strftime("%d/%m/%Y %H:%M") if u.created_at else "Ban đầu",
            "student_count": len(u.students),
            "lesson_count": lesson_cnt,
            "is_self": (u.id == current_user.id)
        })

    pending_count = sum(1 for u in users if u.status == 'pending')
    return jsonify({
        "users": result,
        "total": len(result),
        "pending_count": pending_count
    })

@app.route('/api/admin/users/<int:user_id>/status', methods=['POST'])
@admin_required
def admin_update_user_status(user_id):
    current_user = get_current_user()
    target = db.session.get(User, user_id)
    if not target:
        return jsonify({"error": "Không tìm thấy người dùng!"}), 404
    if target.id == current_user.id:
        return jsonify({"error": "Không thể thay đổi trạng thái của chính bạn!"}), 400

    data = request.json or {}
    new_status = data.get('status')
    if new_status not in ('approved', 'rejected', 'pending'):
        return jsonify({"error": "Trạng thái không hợp lệ!"}), 400

    target.status = new_status
    db.session.commit()
    status_label = {
        'approved': 'Đã phê duyệt (Được phép đăng nhập & sử dụng)',
        'rejected': 'Đã từ chối (Chặn đăng nhập)',
        'pending': 'Đưa về trạng thái Chờ duyệt'
    }.get(new_status, new_status)

    return jsonify({
        "message": f"Đã cập nhật tài khoản '{target.username}': {status_label}!",
        "status": target.status
    })

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@admin_required
def admin_delete_user(user_id):
    current_user = get_current_user()
    target = db.session.get(User, user_id)
    if not target:
        return jsonify({"error": "Không tìm thấy người dùng!"}), 404
    if target.id == current_user.id:
        return jsonify({"error": "Không thể tự xóa tài khoản quản trị của chính bạn!"}), 400

    uname = target.username
    db.session.delete(target)
    db.session.commit()
    return jsonify({"message": f"Đã xóa vĩnh viễn tài khoản '{uname}' và toàn bộ học sinh, lịch học liên quan!"})

@app.route('/api/admin/users/<int:user_id>/toggle-admin', methods=['POST'])
@admin_required
def admin_toggle_admin(user_id):
    current_user = get_current_user()
    target = db.session.get(User, user_id)
    if not target:
        return jsonify({"error": "Không tìm thấy người dùng!"}), 404
    if target.id == current_user.id:
        return jsonify({"error": "Không thể tự thay đổi quyền quản trị của chính bạn!"}), 400

    target.is_admin = not target.is_admin
    db.session.commit()
    role_str = "Quản trị viên (Admin)" if target.is_admin else "Gia sư thường"
    return jsonify({
        "message": f"Đã cập nhật quyền của tài khoản '{target.username}' thành: {role_str}!",
        "is_admin": target.is_admin
    })

@app.route('/api/auth/update-profile', methods=['PUT'])
def update_profile():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Vui lòng đăng nhập!"}), 401
    data = request.json or {}
    user.display_name = data.get('display_name', user.display_name).strip() or user.username
    bank_id = data.get('bank_id', user.bank_id).strip().upper()
    user.bank_id = bank_id
    user.bank_bin = BANK_BIN_MAP.get(bank_id, "970422")
    user.account_no = data.get('account_no', user.account_no).strip()
    user.account_name = data.get('account_name', user.account_name).strip().upper()
    
    new_pass = data.get('new_password', '').strip()
    if new_pass:
        user.password_hash = generate_password_hash(new_pass)

    db.session.commit()
    return jsonify({"message": "Đã cập nhật thông tin cá nhân & ngân hàng nhận QR!"})

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.pop('user_id', None)
    return jsonify({"message": "Đã đăng xuất!"})

# --- API THỐNG KÊ DASHBOARD (THEO TỪNG GIA SƯ) ---
@app.route('/api/stats', methods=['GET'])
def get_stats():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Chưa đăng nhập"}), 401

    now = datetime.now()
    curr_month = request.args.get('month', now.strftime('%Y-%m'))
    
    total_students = Student.query.filter_by(user_id=user.id).count()
    lessons_month = Lesson.query.join(Student).filter(
        Student.user_id == user.id,
        Lesson.date.like(f"{curr_month}-%")
    ).all()
    
    total_lessons = len(lessons_month)
    # Tính cả buổi hoàn thành (completed) và dạy bù (makeup) vào doanh thu đạt được
    completed_lessons = [l for l in lessons_month if (l.is_completed or l.status in ('completed', 'makeup'))]
    cancelled_lessons = [l for l in lessons_month if l.status == 'cancelled']
    
    estimated_revenue = sum(l.student.fee_per_session for l in completed_lessons)
    projected_revenue = sum(l.student.fee_per_session for l in lessons_month if l.status != 'cancelled')
    
    return jsonify({
        "month": curr_month,
        "total_students": total_students,
        "total_lessons": total_lessons,
        "completed_count": len(completed_lessons),
        "cancelled_count": len(cancelled_lessons),
        "estimated_revenue": estimated_revenue,
        "projected_revenue": projected_revenue
    })

# --- API THÊM & LẤY DANH SÁCH HỌC SINH (THEO TỪNG GIA SƯ) ---
@app.route('/api/students', methods=['GET', 'POST'])
def handle_students():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Vui lòng đăng nhập!"}), 401

    if request.method == 'POST':
        data = request.json or {}
        name = data.get('name', '').strip()
        if not name:
            return jsonify({"error": "Tên học sinh không được để trống!"}), 400

        try:
            fee_str = str(data.get('fee_per_session', 0)).replace('.', '').replace(',', '').strip()
            fee = int(fee_str) if fee_str else 0
        except ValueError:
            return jsonify({"error": "Đơn giá học phí không hợp lệ!"}), 400

        color = data.get('color', '#4f46e5')
        
        student = Student.query.filter(Student.user_id == user.id, Student.name.ilike(name)).first()
        if student:
            student.fee_per_session = fee
            if color:
                student.color = color
        else:
            student = Student(user_id=user.id, name=name, fee_per_session=fee, color=color)
            db.session.add(student)
        db.session.commit()
        return jsonify({
            "message": "Đã lưu thông tin học sinh!",
            "student": {
                "id": student.id,
                "name": student.name,
                "fee": student.fee_per_session,
                "color": student.color
            }
        })
    
    students = Student.query.filter_by(user_id=user.id).all()
    return jsonify([{
        "id": s.id,
        "name": s.name,
        "fee": s.fee_per_session,
        "color": s.color or "#4f46e5"
    } for s in students])

# --- API XÓA HỌC SINH ---
@app.route('/api/students/<int:student_id>', methods=['DELETE'])
def delete_student(student_id):
    user = get_current_user()
    if not user:
        return jsonify({"error": "Vui lòng đăng nhập!"}), 401
    student = Student.query.filter_by(id=student_id, user_id=user.id).first_or_404()
    student_name = student.name
    db.session.delete(student)
    db.session.commit()
    return jsonify({"message": f"Đã xóa học sinh {student_name} và toàn bộ lịch liên quan!"})

# --- HÀM KIỂM TRA TRÙNG LỊCH (CHỈ KIỂM TRA TRONG LỊCH CỦA GIA SƯ ĐÓ) ---
def check_time_conflict(user_id, date, start_time, end_time, exclude_id=None):
    existing = Lesson.query.join(Student).filter(
        Student.user_id == user_id,
        Lesson.date == date
    ).all()
    for l in existing:
        if exclude_id and l.id == exclude_id:
            continue
        if l.status == 'cancelled':
            continue
        if start_time < l.end_time and end_time > l.start_time:
            return {
                "id": l.id,
                "student_name": l.student.name,
                "date": l.date,
                "time": f"{l.start_time} - {l.end_time}"
            }
    return None

# --- API THÊM & HIỂN THỊ LỊCH HỌC ---
@app.route('/api/lessons', methods=['GET', 'POST'])
def handle_lessons():
    user = get_current_user()
    if not user:
        return jsonify([])

    if request.method == 'POST':
        data = request.json
        student = Student.query.filter_by(id=data['student_id'], user_id=user.id).first_or_404()
        start_time = data['start_time']
        end_time = data['end_time']
        note = data.get('note', '')
        is_recurring = data.get('is_recurring', False)
        ignore_conflict = data.get('ignore_conflict', False)

        conflicts = []

        if not is_recurring:
            date = data['date']
            conflict = check_time_conflict(user.id, date, start_time, end_time)
            if conflict and not ignore_conflict:
                return jsonify({
                    "has_conflict": True,
                    "conflicts": [conflict],
                    "message": f"Trùng lịch với {conflict['student_name']} ({conflict['time']})"
                }), 409
            
            new_lesson = Lesson(
                student_id=student.id, date=date,
                start_time=start_time, end_time=end_time, note=note,
                status="scheduled"
            )
            db.session.add(new_lesson)
            db.session.commit()
            return jsonify({"message": "Đã tạo buổi học thành công!"})
        else:
            start_dt = datetime.strptime(data['date'], "%Y-%m-%d")
            end_dt = datetime.strptime(data['end_date'], "%Y-%m-%d")
            weekdays = [int(d) for d in data.get('weekdays', [])]

            to_create = []
            curr_dt = start_dt
            while curr_dt <= end_dt:
                if curr_dt.weekday() in weekdays:
                    d_str = curr_dt.strftime("%Y-%m-%d")
                    conflict = check_time_conflict(user.id, d_str, start_time, end_time)
                    if conflict:
                        conflicts.append(conflict)
                    to_create.append(d_str)
                curr_dt += timedelta(days=1)

            if conflicts and not ignore_conflict:
                return jsonify({
                    "has_conflict": True,
                    "conflicts": conflicts[:3],
                    "message": f"Có {len(conflicts)} buổi bị trùng khung giờ với học sinh khác!"
                }), 409

            for d_str in to_create:
                db.session.add(Lesson(
                    student_id=student.id, date=d_str,
                    start_time=start_time, end_time=end_time, note=note,
                    status="scheduled"
                ))

            db.session.commit()
            return jsonify({"message": f"Đã tạo {len(to_create)} buổi học thành công!"})

    lessons = Lesson.query.join(Student).filter(Student.user_id == user.id).all()
    events = []
    for l in lessons:
        base_color = l.student.color if l.student.color else "#4f46e5"
        status = l.status or ("completed" if l.is_completed else "scheduled")
        if status == "completed" or l.is_completed:
            color = "#10b981" # Xanh lá
            prefix = "✓ "
        elif status == "cancelled":
            color = "#64748b" # Xám
            prefix = "✕ [Nghỉ] "
        elif status == "makeup":
            color = "#f59e0b" # Cam
            prefix = "↻ [Bù] "
        else:
            color = base_color
            prefix = "● "

        events.append({
            "id": l.id,
            "title": f"{prefix}{l.student.name} ({l.start_time}-{l.end_time})",
            "start": f"{l.date}T{l.start_time}:00",
            "end": f"{l.date}T{l.end_time}:00",
            "backgroundColor": color,
            "borderColor": color,
            "extendedProps": {
                "student_name": l.student.name,
                "student_id": l.student_id,
                "date": l.date,
                "start_time": l.start_time,
                "end_time": l.end_time,
                "note": l.note,
                "is_completed": l.is_completed,
                "status": status,
                "color": base_color
            }
        })
    return jsonify(events)

# --- API SỬA & XÓA BUỔI HỌC ---
@app.route('/api/lessons/<int:lesson_id>', methods=['PUT', 'DELETE'])
def modify_lesson(lesson_id):
    user = get_current_user()
    if not user:
        return jsonify({"error": "Vui lòng đăng nhập!"}), 401
    lesson = Lesson.query.join(Student).filter(Lesson.id == lesson_id, Student.user_id == user.id).first_or_404()

    if request.method == 'DELETE':
        db.session.delete(lesson)
        db.session.commit()
        return jsonify({"message": "Đã xóa buổi học!"})
    
    if request.method == 'PUT':
        data = request.json
        lesson.date = data.get('date', lesson.date)
        lesson.start_time = data.get('start_time', lesson.start_time)
        lesson.end_time = data.get('end_time', lesson.end_time)
        lesson.note = data.get('note', lesson.note)
        
        if 'status' in data:
            lesson.status = data['status']
            lesson.is_completed = (data['status'] == 'completed')
        elif 'is_completed' in data:
            lesson.is_completed = bool(data['is_completed'])
            lesson.status = 'completed' if lesson.is_completed else 'scheduled'
            
        db.session.commit()
        return jsonify({"message": "Đã cập nhật buổi học!"})

# --- API TÍNH TIỀN CUỐI THÁNG (GẮN ĐÚNG MÃ QR CỦA GIA SƯ ĐÓ) ---
@app.route('/api/invoice', methods=['GET'])
def calculate_invoice():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Vui lòng đăng nhập!"}), 401

    name_query = request.args.get('name', '').strip()
    month_query = request.args.get('month', '')

    if not name_query or not month_query:
        return jsonify({"error": "Vui lòng chọn học sinh và chọn tháng!"}), 400

    student = Student.query.filter(
        Student.user_id == user.id,
        Student.name.ilike(f"%{name_query}%")
    ).first()
    if not student:
        return jsonify({"error": "Không tìm thấy học sinh này!"}), 404

    lessons = Lesson.query.filter(
        Lesson.student_id == student.id,
        Lesson.date.like(f"{month_query}-%")
    ).order_by(Lesson.date.asc(), Lesson.start_time.asc()).all()

    weekday_names = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]

    session_list = []
    completed_count = 0
    makeup_count = 0
    cancelled_count = 0
    scheduled_count = 0

    for l in lessons:
        dt = datetime.strptime(l.date, "%Y-%m-%d")
        w_name = weekday_names[dt.weekday()]
        full_date = f"{w_name}, {dt.strftime('%d/%m/%Y')}"

        st = l.status or ('completed' if l.is_completed else 'scheduled')

        is_billed = False
        if st == 'completed':
            completed_count += 1
            is_billed = True
            st_text = 'Đã hoàn thành'
        elif st == 'makeup':
            makeup_count += 1
            is_billed = True
            st_text = 'Dạy bù'
        elif st == 'cancelled':
            cancelled_count += 1
            is_billed = False
            st_text = 'Học sinh nghỉ'
        else:
            scheduled_count += 1
            is_billed = False
            st_text = 'Chưa dạy'

        session_list.append({
            "weekday": w_name,
            "date": dt.strftime("%d/%m/%Y"),
            "full_date": full_date,
            "time": f"{l.start_time} - {l.end_time}",
            "note": l.note or "",
            "status": st,
            "status_text": st_text,
            "is_billed": is_billed
        })

    billable_sessions = completed_count + makeup_count
    total_amount = billable_sessions * student.fee_per_session

    return jsonify({
        "tutor_name": user.display_name,
        "student_name": student.name,
        "month": month_query,
        "fee_per_session": student.fee_per_session,
        "billable_sessions": billable_sessions,
        "completed_count": completed_count,
        "makeup_count": makeup_count,
        "cancelled_count": cancelled_count,
        "scheduled_count": scheduled_count,
        "total_sessions": len(session_list),
        "total_amount": total_amount,
        "sessions": session_list,
        "bank": {
            "BANK_ID": user.bank_id or "MB",
            "BIN": user.bank_bin or "970422",
            "ACCOUNT_NO": user.account_no or "0915154306",
            "ACCOUNT_NAME": user.account_name or "NGUYEN TRONG HUY"
        }
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)