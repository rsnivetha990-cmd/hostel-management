import os
import io
import base64
from datetime import datetime, date, timedelta
from functools import wraps
from werkzeug.utils import secure_filename

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import qrcode
from flask import (
    Flask, render_template, redirect, url_for, request, flash, jsonify, abort
)
from flask_login import (
    login_user, logout_user, login_required, current_user
)

from extensions import db, login_manager
from models import User, Room, Student, Attendance, Complaint, QRCode


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")

    # Cloud database URL support (Neon.tech / Supabase / Render PostgreSQL)
    db_url = os.environ.get("DATABASE_URL", "sqlite:///hostel.db")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max upload


    db.init_app(app)
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    def role_required(*roles):
        def decorator(f):
            @wraps(f)
            def wrapped(*args, **kwargs):
                if not current_user.is_authenticated:
                    return redirect(url_for("login"))
                if current_user.role not in roles:
                    abort(403)
                return f(*args, **kwargs)
            return wrapped
        return decorator

    # =========================================================
    # AUTH
    # =========================================================
    @app.route("/", methods=["GET"])
    def index():
        if current_user.is_authenticated:
            return redirect_to_dashboard()
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect_to_dashboard()
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = User.query.filter_by(username=username).first()
            if user and user.check_password(password):
                login_user(user)
                return redirect_to_dashboard()
            flash("Invalid username or password.", "danger")
        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))

    def redirect_to_dashboard():
        if current_user.role == "admin":
            return redirect(url_for("admin_dashboard"))
        if current_user.role == "warden":
            return redirect(url_for("warden_dashboard"))
        return redirect(url_for("student_dashboard"))

    # =========================================================
    # STUDENT MODULE
    # =========================================================
    @app.route("/student/dashboard")
    @role_required("student")
    def student_dashboard():
        student = current_user.student_profile
        today_attendance = Attendance.query.filter_by(
            student_id=student.id, date=date.today()
        ).first()
        recent_complaints = (
            Complaint.query.filter_by(student_id=student.id)
            .order_by(Complaint.date.desc())
            .limit(5)
            .all()
        )
        roommates = []
        if student.room:
            roommates = [s for s in student.room.students if s.id != student.id]
        return render_template(
            "student_dashboard.html",
            student=student,
            today_attendance=today_attendance,
            recent_complaints=recent_complaints,
            roommates=roommates,
        )

    @app.route("/student/attendance/scan", methods=["GET", "POST"])
    @role_required("student")
    def student_scan():
        student = current_user.student_profile
        if request.method == "POST":
            token = request.form.get("token", "").strip()
            qr = QRCode.query.filter_by(token=token).first()
            if not qr:
                flash("Invalid QR code.", "danger")
                return redirect(url_for("student_scan"))
            elif not qr.is_valid:
                flash("This QR code has expired. Ask the warden for a new one.", "warning")
                return redirect(url_for("student_scan"))

            existing = Attendance.query.filter_by(
                student_id=student.id, date=date.today()
            ).first()
            if existing:
                # Already marked today -- still show their details as confirmation
                return render_template(
                    "scan_confirmation.html", student=student, attendance=existing,
                    already_marked=True
                )

            status = "Late" if datetime.now().hour >= 21 else "Present"
            att = Attendance(student_id=student.id, qr_id=qr.id, status=status)
            db.session.add(att)
            db.session.commit()
            return render_template(
                "scan_confirmation.html", student=student, attendance=att,
                already_marked=False
            )
        return render_template("student_scan.html")

    @app.route("/student/attendance/history")
    @role_required("student")
    def student_attendance_history():
        student = current_user.student_profile
        records = (
            Attendance.query.filter_by(student_id=student.id)
            .order_by(Attendance.date.desc())
            .all()
        )
        return render_template("attendance_history.html", records=records)

    def upload_complaint_photo(file):
        """Uploads file to Cloudinary if configured; otherwise saves to static/uploads locally."""
        if not file or not file.filename:
            return None

        # 1. Cloudinary upload (if cloud credentials are provided)
        cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME")
        api_key = os.environ.get("CLOUDINARY_API_KEY")
        api_secret = os.environ.get("CLOUDINARY_API_SECRET")

        if cloud_name and api_key and api_secret:
            try:
                import cloudinary
                import cloudinary.uploader

                cloudinary.config(
                    cloud_name=cloud_name,
                    api_key=api_key,
                    api_secret=api_secret,
                    secure=True,
                )
                res = cloudinary.uploader.upload(
                    file,
                    folder="hostel_complaints",
                    resource_type="image",
                )
                return res.get("secure_url")
            except Exception as e:
                app.logger.error(f"Cloudinary upload error: {e}")

        # 2. Local fallback if Cloudinary credentials are not present
        try:
            filename = secure_filename(file.filename)
            if filename:
                unique_name = f"{int(datetime.utcnow().timestamp())}_{filename}"
                upload_dir = os.path.join(app.root_path, "static", "uploads")
                os.makedirs(upload_dir, exist_ok=True)
                file_path = os.path.join(upload_dir, unique_name)
                file.save(file_path)
                return url_for("static", filename=f"uploads/{unique_name}")
        except Exception as e:
            app.logger.error(f"Local file save error: {e}")

        return None

    @app.route("/student/complaints", methods=["GET", "POST"])
    @role_required("student")
    def student_complaints():
        student = current_user.student_profile
        if request.method == "POST":
            category = request.form.get("category")
            description = request.form.get("description", "").strip()
            is_anonymous = request.form.get("is_anonymous") == "on"
            photo = request.files.get("photo")
            image_url = upload_complaint_photo(photo) if photo else None

            if not description:
                flash("Please describe the issue.", "danger")
            else:
                priority, escalated = Complaint.auto_priority(category, description)
                complaint = Complaint(
                    student_id=student.id,
                    category=category,
                    description=description,
                    priority=priority,
                    is_anonymous=is_anonymous,
                    escalated_by_keyword=escalated,
                    image_url=image_url,
                )
                db.session.add(complaint)
                db.session.commit()
                if escalated:
                    flash(
                        "Complaint submitted and flagged as EMERGENCY based on your description. "
                        "The warden has been notified immediately.", "danger"
                    )
                else:
                    flash("Complaint submitted successfully.", "success")
            return redirect(url_for("student_complaints"))
        complaints = (
            Complaint.query.filter_by(student_id=student.id)
            .order_by(Complaint.date.desc())
            .all()
        )
        categories = list(Complaint.CATEGORY_PRIORITY.keys())
        return render_template(
            "student_complaints.html", complaints=complaints, categories=categories
        )

    @app.route("/student/complaints/<int:complaint_id>/rate", methods=["POST"])
    @role_required("student")
    def student_rate_complaint(complaint_id):
        student = current_user.student_profile
        complaint = Complaint.query.get_or_404(complaint_id)
        if complaint.student_id != student.id:
            abort(403)
        if complaint.status != "Resolved":
            flash("You can only rate a complaint once it's resolved.", "warning")
            return redirect(url_for("student_complaints"))
        rating = int(request.form.get("rating", 0))
        if 1 <= rating <= 5:
            complaint.rating = rating
            db.session.commit()
            flash("Thanks for your feedback!", "success")
        return redirect(url_for("student_complaints"))

    # =========================================================
    # WARDEN MODULE
    # =========================================================
    @app.route("/warden/dashboard")
    @role_required("warden", "admin")
    def warden_dashboard():
        total_students = Student.query.count()
        today_present = Attendance.query.filter_by(date=date.today()).count()
        pending_complaints = Complaint.query.filter(
            Complaint.status != "Resolved"
        ).count()
        active_qr = QRCode.query.order_by(QRCode.created_time.desc()).first()
        rooms = Room.query.all()
        full_rooms = [r for r in rooms if r.available_beds == 0]
        return render_template(
            "warden_dashboard.html",
            total_students=total_students,
            today_present=today_present,
            pending_complaints=pending_complaints,
            active_qr=active_qr,
            full_rooms=full_rooms,
        )

    @app.route("/warden/qr/generate", methods=["GET", "POST"])
    @role_required("warden", "admin")
    def warden_generate_qr():
        if request.method == "POST":
            validity = int(request.form.get("validity", 180))
            label = request.form.get("label", "General")
            qr = QRCode.generate(
                validity_seconds=validity, created_by=current_user.id, session_label=label
            )
            return redirect(url_for("warden_qr_display", qr_id=qr.id))
        return render_template("warden_generate_qr.html")

    @app.route("/warden/qr/<int:qr_id>")
    @role_required("warden", "admin")
    def warden_qr_display(qr_id):
        qr = QRCode.query.get_or_404(qr_id)
        img = qrcode.make(qr.token)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return render_template("warden_qr_display.html", qr=qr, qr_b64=qr_b64)

    @app.route("/api/qr/<int:qr_id>/status")
    @role_required("warden", "admin")
    def qr_status(qr_id):
        qr = QRCode.query.get_or_404(qr_id)
        seconds_left = max(0, int((qr.expiry_time - datetime.utcnow()).total_seconds()))
        present_count = Attendance.query.filter_by(qr_id=qr.id).count()
        return jsonify(valid=qr.is_valid, seconds_left=seconds_left, present_count=present_count)

    @app.route("/warden/attendance")
    @role_required("warden", "admin")
    def warden_attendance():
        selected_date = request.args.get("date", date.today().isoformat())
        try:
            d = datetime.strptime(selected_date, "%Y-%m-%d").date()
        except ValueError:
            d = date.today()
        present_records = Attendance.query.filter_by(date=d).all()
        present_ids = {r.student_id for r in present_records}
        all_students = Student.query.all()
        absentees = [s for s in all_students if s.id not in present_ids]
        return render_template(
            "warden_attendance.html",
            selected_date=d,
            present_records=present_records,
            absentees=absentees,
        )

    @app.route("/warden/rooms")
    @role_required("warden", "admin")
    def warden_rooms():
        rooms = Room.query.order_by(Room.block, Room.room_number).all()
        unassigned = Student.query.filter_by(room_id=None).all()
        return render_template("warden_rooms.html", rooms=rooms, unassigned=unassigned)

    @app.route("/warden/rooms/allocate", methods=["POST"])
    @role_required("warden", "admin")
    def warden_allocate_room():
        student_id = request.form.get("student_id")
        room_id = request.form.get("room_id")
        student = Student.query.get_or_404(student_id)
        room = Room.query.get_or_404(room_id)
        if room.available_beds <= 0:
            flash(f"Room {room.room_number} is already full.", "danger")
        else:
            student.room_id = room.id
            db.session.commit()
            flash(f"{student.user.full_name} allocated to room {room.room_number}.", "success")
        return redirect(url_for("warden_rooms"))

    @app.route("/warden/rooms/recommend/<int:student_id>")
    @role_required("warden", "admin")
    def warden_recommend_room(student_id):
        student = Student.query.get_or_404(student_id)
        candidates = [
            r for r in Room.query.filter_by(status="active").all()
            if r.available_beds > 0 and (r.gender == "any" or r.gender == student.gender)
        ]
        candidates.sort(key=lambda r: r.available_beds)
        best = candidates[0] if candidates else None
        return jsonify(
            recommended=best.to_dict() if best else None,
            all_candidates=[r.to_dict() for r in candidates[:5]],
        )

    @app.route("/warden/complaints")
    @role_required("warden", "admin")
    def warden_complaints():
        status_filter = request.args.get("status", "all")
        query = Complaint.query
        if status_filter != "all":
            query = query.filter_by(status=status_filter)
        priority_order = {"Emergency": 0, "High": 1, "Medium": 2, "Low": 3}
        complaints = sorted(query.all(), key=lambda c: (priority_order.get(c.priority, 4), c.date))
        return render_template(
            "warden_complaints.html", complaints=complaints, status_filter=status_filter
        )

    @app.route("/warden/complaints/<int:complaint_id>/update", methods=["POST"])
    @role_required("warden", "admin")
    def warden_update_complaint(complaint_id):
        complaint = Complaint.query.get_or_404(complaint_id)
        new_status = request.form.get("status")
        assigned_to = request.form.get("assigned_to", "").strip()
        complaint.status = new_status
        if assigned_to:
            complaint.assigned_to = assigned_to
        if new_status == "Resolved":
            complaint.resolved_date = datetime.utcnow()
        db.session.commit()
        flash("Complaint updated.", "success")
        return redirect(url_for("warden_complaints"))

    # =========================================================
    # ADMIN MODULE
    # =========================================================
    @app.route("/admin/dashboard")
    @role_required("admin")
    def admin_dashboard():
        total_students = Student.query.count()
        total_rooms = Room.query.count()
        available_beds = sum(r.available_beds for r in Room.query.all())
        today_attendance = Attendance.query.filter_by(date=date.today()).count()
        pending = Complaint.query.filter(Complaint.status != "Resolved").count()
        resolved = Complaint.query.filter_by(status="Resolved").count()
        return render_template(
            "admin_dashboard.html",
            total_students=total_students,
            total_rooms=total_rooms,
            available_beds=available_beds,
            today_attendance=today_attendance,
            pending=pending,
            resolved=resolved,
        )

    @app.route("/admin/students")
    @role_required("admin")
    def admin_students():
        students = Student.query.all()
        return render_template("admin_students.html", students=students)

    @app.route("/admin/students/add", methods=["GET", "POST"])
    @role_required("admin")
    def admin_add_student():
        if request.method == "POST":
            username = request.form.get("username").strip()
            if User.query.filter_by(username=username).first():
                flash("Username already exists.", "danger")
                return redirect(url_for("admin_add_student"))
            user = User(
                username=username,
                role="student",
                full_name=request.form.get("full_name"),
                email=request.form.get("email"),
                phone=request.form.get("phone"),
            )
            user.set_password(request.form.get("password") or "changeme123")
            db.session.add(user)
            db.session.flush()
            student = Student(
                user_id=user.id,
                student_code=request.form.get("student_code"),
                department=request.form.get("department"),
                year=int(request.form.get("year") or 1),
                gender=request.form.get("gender", "any"),
            )
            db.session.add(student)
            db.session.commit()
            flash("Student added successfully.", "success")
            return redirect(url_for("admin_students"))
        return render_template("admin_add_student.html")

    @app.route("/admin/rooms/add", methods=["GET", "POST"])
    @role_required("admin")
    def admin_add_room():
        if request.method == "POST":
            room = Room(
                block=request.form.get("block"),
                floor=int(request.form.get("floor") or 1),
                room_number=request.form.get("room_number"),
                capacity=int(request.form.get("capacity") or 4),
                gender=request.form.get("gender", "any"),
            )
            db.session.add(room)
            db.session.commit()
            flash("Room added.", "success")
            return redirect(url_for("warden_rooms"))
        return render_template("admin_add_room.html")

    @app.route("/admin/reports")
    @role_required("admin")
    def admin_reports():
        labels, present_counts = [], []
        total_students = max(Student.query.count(), 1)
        for i in range(6, -1, -1):
            d = date.today() - timedelta(days=i)
            count = Attendance.query.filter_by(date=d).count()
            labels.append(d.strftime("%d-%b"))
            present_counts.append(count)
        complaint_categories = {}
        for c in Complaint.query.all():
            complaint_categories[c.category] = complaint_categories.get(c.category, 0) + 1

        rated = Complaint.query.filter(Complaint.rating.isnot(None)).all()
        avg_rating = round(sum(c.rating for c in rated) / len(rated), 1) if rated else None
        emergency_escalations = Complaint.query.filter_by(escalated_by_keyword=True).count()

        return render_template(
            "admin_reports.html",
            labels=labels,
            present_counts=present_counts,
            total_students=total_students,
            complaint_categories=complaint_categories,
            avg_rating=avg_rating,
            rated_count=len(rated),
            emergency_escalations=emergency_escalations,
        )

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", code=403, message="Access forbidden for your role."), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404, message="Page not found."), 404

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
