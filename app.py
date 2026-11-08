import os
from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta

app = Flask(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url or ('sqlite:///' + os.path.join(BASE_DIR, 'tutoring.db'))
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Chống lưu Cache trên trình duyệt điện thoại để bấm Reload là cập nhật ngay lập tức
@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# --- CẤU HÌNH NGÂN HÀNG CỦA BẠN (ĐỂ TẠO MÃ QR) ---
BANK_CONFIG = {
    "BANK_ID": "MB",                   # Mã ngân hàng
    "BIN": "970422",                   # Mã BIN VietQR MB Bank
    "ACCOUNT_NO": "0915154306",        # Số tài khoản
    "ACCOUNT_NAME": "NGUYEN TRONG HUY" # Tên chủ tài khoản
}

# 1. Bảng Học sinh
class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    fee_per_session = db.Column(db.Integer, nullable=False)
    color = db.Column(db.String(20), default="#0d6efd")
    lessons = db.relationship('Lesson', backref='student', cascade="all, delete-orphan", lazy=True)

# 2. Bảng Lịch học
class Lesson(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    date = db.Column(db.String(10), nullable=False)       # YYYY-MM-DD
    start_time = db.Column(db.String(5), nullable=False)  # HH:MM
    end_time = db.Column(db.String(5), nullable=False)    # HH:MM
    note = db.Column(db.String(200), default="")
    is_completed = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default="scheduled") # scheduled, completed, cancelled, makeup

with app.app_context():
    db.create_all()
    # Nếu chạy với database ngoài (PostgreSQL) mà database còn trống, tự động nạp từ file SQLite cũ
    sqlite_path = os.path.join(BASE_DIR, 'tutoring.db')
    if os.environ.get('DATABASE_URL') and os.path.exists(sqlite_path):
        try:
            if Student.query.count() == 0:
                import sqlite3
                conn = sqlite3.connect(sqlite_path)
                c = conn.cursor()
                c.execute("SELECT id, name, fee_per_session, color FROM student")
                for s in c.fetchall():
                    db.session.add(Student(id=s[0], name=s[1], fee_per_session=s[2], color=s[3]))
                db.session.commit()

                c.execute("SELECT id, student_id, date, start_time, end_time, note, is_completed, status FROM lesson")
                for l in c.fetchall():
                    db.session.add(Lesson(id=l[0], student_id=l[1], date=l[2], start_time=l[3], end_time=l[4],
                                         note=l[5] or "", is_completed=bool(l[6]), status=l[7] or "scheduled"))
                db.session.commit()
                conn.close()
                print("Đã tự động sao chép dữ liệu từ SQLite sang PostgreSQL thành công!")
        except Exception as err:
            print("Lỗi khi nạp dữ liệu cũ sang PostgreSQL:", err)

@app.route('/')
def index():
    return render_template('index.html')

# --- API THỐNG KÊ DASHBOARD ---
@app.route('/api/stats', methods=['GET'])
def get_stats():
    now = datetime.now()
    curr_month = request.args.get('month', now.strftime('%Y-%m'))
    
    total_students = Student.query.count()
    lessons_month = Lesson.query.filter(Lesson.date.like(f"{curr_month}-%")).all()
    
    total_lessons = len(lessons_month)
    completed_lessons = [l for l in lessons_month if (l.is_completed or l.status == 'completed')]
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

# --- API THÊM & LẤY DANH SÁCH HỌC SINH ---
@app.route('/api/students', methods=['GET', 'POST'])
def handle_students():
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

        color = data.get('color', '#0d6efd')
        
        student = Student.query.filter(Student.name.ilike(name)).first()
        if student:
            student.fee_per_session = fee
            if color:
                student.color = color
        else:
            student = Student(name=name, fee_per_session=fee, color=color)
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
    
    students = Student.query.all()
    return jsonify([{
        "id": s.id,
        "name": s.name,
        "fee": s.fee_per_session,
        "color": s.color or "#0d6efd"
    } for s in students])

# --- API XÓA HỌC SINH ---
@app.route('/api/students/<int:student_id>', methods=['DELETE'])
def delete_student(student_id):
    student = Student.query.get_or_404(student_id)
    student_name = student.name
    db.session.delete(student)
    db.session.commit()
    return jsonify({"message": f"Đã xóa học sinh {student_name} và toàn bộ lịch liên quan!"})

# --- HÀM KIỂM TRA TRÙNG LỊCH ---
def check_time_conflict(date, start_time, end_time, exclude_id=None):
    existing = Lesson.query.filter(Lesson.date == date).all()
    for l in existing:
        if exclude_id and l.id == exclude_id:
            continue
        # Trùng khi: start_time < l.end_time and end_time > l.start_time
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
    if request.method == 'POST':
        data = request.json
        student_id = data['student_id']
        start_time = data['start_time']
        end_time = data['end_time']
        note = data.get('note', '')
        is_recurring = data.get('is_recurring', False)
        ignore_conflict = data.get('ignore_conflict', False)

        conflicts = []

        if not is_recurring:
            date = data['date']
            conflict = check_time_conflict(date, start_time, end_time)
            if conflict and not ignore_conflict:
                return jsonify({
                    "has_conflict": True,
                    "conflicts": [conflict],
                    "message": f"Trùng lịch với {conflict['student_name']} ({conflict['time']})"
                }), 409
            
            new_lesson = Lesson(
                student_id=student_id, date=date,
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
                    conflict = check_time_conflict(d_str, start_time, end_time)
                    if conflict:
                        conflicts.append(conflict)
                    to_create.append(d_str)
                curr_dt += timedelta(days=1)

            if conflicts and not ignore_conflict:
                return jsonify({
                    "has_conflict": True,
                    "conflicts": conflicts[:3], # trả về tối đa 3 lịch trùng mẫu
                    "message": f"Có {len(conflicts)} buổi bị trùng khung giờ với học sinh khác!"
                }), 409

            for d_str in to_create:
                db.session.add(Lesson(
                    student_id=student_id, date=d_str,
                    start_time=start_time, end_time=end_time, note=note,
                    status="scheduled"
                ))

            db.session.commit()
            return jsonify({"message": f"Đã tạo {len(to_create)} buổi học thành công!"})

    lessons = Lesson.query.all()
    events = []
    for l in lessons:
        # Màu sắc theo học sinh hoặc trạng thái
        base_color = l.student.color if l.student.color else "#0d6efd"
        
        status = l.status or ("completed" if l.is_completed else "scheduled")
        if status == "completed" or l.is_completed:
            color = "#198754" # Xanh lá
            prefix = "✓ "
        elif status == "cancelled":
            color = "#6c757d" # Xám
            prefix = "✕ [Nghỉ] "
        elif status == "makeup":
            color = "#fd7e14" # Cam
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
    lesson = Lesson.query.get_or_404(lesson_id)
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

# --- API TÍNH TIỀN CUỐI THÁNG ---
@app.route('/api/invoice', methods=['GET'])
def calculate_invoice():
    name_query = request.args.get('name', '').strip()
    month_query = request.args.get('month', '')

    if not name_query or not month_query:
        return jsonify({"error": "Vui lòng chọn học sinh và chọn tháng!"}), 400

    student = Student.query.filter(Student.name.ilike(f"%{name_query}%")).first()
    if not student:
        return jsonify({"error": "Không tìm thấy học sinh này!"}), 404

    # Lấy toàn bộ các buổi học trong tháng của học sinh để hiển thị chi tiết cho phụ huynh
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

        # Quy tắc tính tiền học phí:
        # - Đã hoàn thành (completed): TÍNH TIỀN (+1)
        # - Dạy bù (makeup): TÍNH TIỀN (+1)
        # - Nghỉ (cancelled): KHÔNG TÍNH TIỀN (0đ)
        # - Chưa dạy (scheduled): Mặc định không tính
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
        "bank": BANK_CONFIG
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
