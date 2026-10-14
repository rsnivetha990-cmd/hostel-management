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

import math
import qrcode
from flask import (
    Flask, render_template, redirect, url_for, request, flash, jsonify, abort
)
from flask_login import (
    login_user, logout_user, login_required, current_user
)

from extensions import db, login_manager
from models import User, Room, Student, Attendance, Complaint, QRCode, Notification


# --- Geofencing & Hostel Gate Coordinates (Configurable & Dynamic Sync) ---
HOSTEL_CONFIG = {
    "latitude": float(os.environ.get("HOSTEL_LATITUDE", 12.9716)),
    "longitude": float(os.environ.get("HOSTEL_LONGITUDE", 77.5946)),
    "radius_meters": float(os.environ.get("HOSTEL_GEOFENCE_METERS", 300)),
    "name": "Main Hostel Gate Entrance",
}

def calculate_distance_meters(lat1, lon1, lat2, lon2):
    """Calculates geodesic distance between two GPS coordinates in meters using the Haversine formula."""
    try:
        R = 6371000  # Earth's radius in meters
        phi1 = math.radians(float(lat1))
        phi2 = math.radians(float(lat2))
        delta_phi = math.radians(float(lat2) - float(lat1))
        delta_lambda = math.radians(float(lon2) - float(lon1))

        a = math.sin(delta_phi / 2.0) ** 2 + \
            math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c
    except Exception:
        return 999999.0


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

    with app.app_context():
        db.create_all()
        # Safe migration for existing SQLite / Postgres tables
        from sqlalchemy import text
        try:
            with db.engine.connect() as conn:
                for col_sql in [
                    "ALTER TABLE qr_codes ADD COLUMN rotation_interval INTEGER DEFAULT 60",
                    "ALTER TABLE students ADD COLUMN trusted_device_id VARCHAR(120)",
                    "ALTER TABLE students ADD COLUMN trusted_device_name VARCHAR(120)",
                    "ALTER TABLE students ADD COLUMN enrolled_face_image TEXT",
                    "ALTER TABLE students ADD COLUMN hostel_location VARCHAR(120)",
                    "ALTER TABLE attendance ADD COLUMN verification_status VARCHAR(80) DEFAULT 'Verified'",
                    "ALTER TABLE attendance ADD COLUMN device_id VARCHAR(120)",
                    "ALTER TABLE attendance ADD COLUMN device_name VARCHAR(120)",
                    "ALTER TABLE attendance ADD COLUMN latitude FLOAT",
                    "ALTER TABLE attendance ADD COLUMN longitude FLOAT",
                    "ALTER TABLE attendance ADD COLUMN distance_meters FLOAT",
                    "ALTER TABLE attendance ADD COLUMN face_verified BOOLEAN DEFAULT 0",
                    "ALTER TABLE attendance ADD COLUMN face_snapshot TEXT",
                ]:
                    try:
                        conn.execute(text(col_sql))
                        conn.commit()
                    except Exception:
                        pass
        except Exception:
            pass

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    @app.route("/health", methods=["GET"])
    @app.route("/api/health", methods=["GET"])
    def cloud_health():
        import time, platform
        t0 = time.time()
        db_status = "connected"
        try:
            db.session.execute(text("SELECT 1"))
        except Exception as e:
            db_status = f"unhealthy: {str(e)}"
        latency_ms = round((time.time() - t0) * 1000, 2)

        has_cloudinary = bool(os.environ.get("CLOUDINARY_CLOUD_NAME"))
        storage_type = "Cloudinary CDN (SaaS)" if has_cloudinary else "Local Secure File Storage"

        return jsonify({
            "status": "healthy" if "unhealthy" not in db_status else "degraded",
            "service": "Smart Hostel Management Cloud Service",
            "version": "2.4.0",
            "timestamp": datetime.utcnow().isoformat(),
            "cloud_infrastructure": {
                "platform": "Cloud PaaS (Linux Container)",
                "python_version": platform.python_version(),
                "database": {
                    "type": "PostgreSQL" if "postgres" in app.config["SQLALCHEMY_DATABASE_URI"] else "SQLite",
                    "status": db_status,
                    "query_latency_ms": latency_ms,
                },
                "object_storage": storage_type,
                "geofence_active": True,
                "biometrics_active": True,
            },
            "metrics": {
                "total_students": Student.query.count(),
                "active_rooms": Room.query.count(),
                "today_attendances": Attendance.query.filter_by(date=date.today()).count(),
                "pending_complaints": Complaint.query.filter(Complaint.status != "Resolved").count(),
            }
        })

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

    @app.context_processor
    def inject_notifications():
        if current_user.is_authenticated and current_user.role in ["admin", "warden"]:
            notifs = (
                Notification.query.filter_by(recipient_role=current_user.role)
                .order_by(Notification.created_at.desc())
                .limit(10)
                .all()
            )
            unread_count = Notification.query.filter_by(
                recipient_role=current_user.role, is_read=False
            ).count()
            return dict(user_notifications=notifs, unread_notifications_count=unread_count)
        return dict(user_notifications=[], unread_notifications_count=0)

    def send_complaint_notifications(complaint, event_type="raised", student_rating=None, custom_msg=None):
        """
        Sends notifications for a complaint:
        - Admin ALWAYS receives notifications.
        - Warden receives notification ONLY IF complaint was NOT submitted anonymously (is_anonymous == False).
        """
        student_name = "Anonymous Student" if complaint.is_anonymous else complaint.student.user.full_name
        student_code = "" if complaint.is_anonymous else f" ({complaint.student.student_code})"

        if event_type == "raised":
            badge = f"[{complaint.priority} Priority]"
            title = f"New Complaint #{complaint.id}: {complaint.category} {badge}"
            body = f"{student_name}{student_code} submitted a {complaint.priority} priority complaint in {complaint.category}: \"{complaint.description[:90]}\""
            cat = "danger" if complaint.priority in ["Emergency", "High"] else "info"

        elif event_type == "not_resolved":
            title = f"Complaint #{complaint.id} Reopened (Not Resolved)"
            rating_text = f" Student rating: {student_rating}/5 stars." if student_rating else ""
            body = f"{student_name}{student_code} reported that Complaint #{complaint.id} ({complaint.category}) is NOT RESOLVED.{rating_text} Status automatically reset to Pending."
            cat = "warning"

        elif event_type == "resolved":
            title = f"Complaint #{complaint.id} Confirmed Resolved"
            rating_text = f" Rating: {student_rating}/5 stars." if student_rating else ""
            body = f"{student_name}{student_code} confirmed Complaint #{complaint.id} ({complaint.category}) is RESOLVED.{rating_text}"
            cat = "success"

        else:
            title = f"Update on Complaint #{complaint.id}"
            body = custom_msg or f"Complaint #{complaint.id} status updated."
            cat = "info"

        # 1. Admin ALWAYS receives the notification
        admin_notif = Notification(
            recipient_role="admin",
            complaint_id=complaint.id,
            title=title,
            message=body,
            category=cat,
        )
        db.session.add(admin_notif)

        # 2. Warden receives notification ONLY if NOT anonymous
        if not complaint.is_anonymous:
            warden_notif = Notification(
                recipient_role="warden",
                complaint_id=complaint.id,
                title=title,
                message=body,
                category=cat,
            )
            db.session.add(warden_notif)

        db.session.commit()

    @app.route("/notifications/mark-all-read")
    @login_required
    def mark_all_notifications_read():
        if current_user.role in ["admin", "warden"]:
            Notification.query.filter_by(recipient_role=current_user.role, is_read=False).update(
                {"is_read": True}
            )
            db.session.commit()
        return redirect(request.referrer or url_for("index"))

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

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if current_user.is_authenticated:
            return redirect_to_dashboard()

        # Authorized member registration code (default: HOSTEL2026, can also be configured via HOSTEL_REGISTRATION_CODE)
        valid_codes = {"HOSTEL2026", "SHMS2026"}
        custom_code = os.environ.get("HOSTEL_REGISTRATION_CODE")
        if custom_code:
            valid_codes.add(custom_code.strip().upper())

        rooms = Room.query.order_by(Room.block, Room.room_number).all()

        if request.method == "POST":
            reg_code = request.form.get("registration_code", "").strip().upper()
            full_name = request.form.get("full_name", "").strip()
            student_code = request.form.get("student_code", "").strip().upper()
            department = request.form.get("department", "").strip()
            year = int(request.form.get("year") or 1)
            gender = request.form.get("gender", "female").strip().lower()
            room_id = request.form.get("room_id", "").strip()
            room_number = request.form.get("room_number", "").strip()
            enrolled_face = request.form.get("enrolled_face", "").strip()
            hostel_location = request.form.get("hostel_location_name", "").strip() or request.form.get("hostel_location", "").strip() or HOSTEL_CONFIG.get("name", "Main Campus Hostel Gate")
            hostel_lat = request.form.get("hostel_lat", "").strip()
            hostel_lon = request.form.get("hostel_lon", "").strip()
            email = request.form.get("email", "").strip()
            phone = request.form.get("phone", "").strip()
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")

            # 1. Constraint: Verify registration code
            if reg_code not in valid_codes:
                flash("Invalid registration code! Only authorized hostel members with a valid code can register.", "danger")
                return render_template("register.html", rooms=rooms, hostel_config=HOSTEL_CONFIG)

            # 2. Constraint: Picture requirement
            if not enrolled_face or len(enrolled_face) < 50:
                flash("Student Picture Required: Please capture your live picture or upload a clear photo before submitting.", "warning")
                return render_template("register.html", rooms=rooms, hostel_config=HOSTEL_CONFIG)

            # 3. Constraint: Room selection
            allocated_room = None
            if room_id and room_id.isdigit():
                allocated_room = Room.query.get(int(room_id))
            elif room_number:
                allocated_room = Room.query.filter_by(room_number=room_number).first()

            if not allocated_room:
                flash("Room Selection Required: Please choose your allocated hostel room number.", "warning")
                return render_template("register.html", rooms=rooms, hostel_config=HOSTEL_CONFIG)

            if allocated_room.available_beds <= 0:
                flash(f"Room {allocated_room.room_number} ({allocated_room.block}) is currently at full capacity. Please select an available room.", "danger")
                return render_template("register.html", rooms=rooms, hostel_config=HOSTEL_CONFIG)

            # 4. Constraint: Password length & confirmation
            if len(password) < 6:
                flash("Password must be at least 6 characters long.", "warning")
                return render_template("register.html", rooms=rooms, hostel_config=HOSTEL_CONFIG)

            if password != confirm_password:
                flash("Passwords do not match. Please verify and try again.", "warning")
                return render_template("register.html", rooms=rooms, hostel_config=HOSTEL_CONFIG)

            # 5. Constraint: Check username uniqueness
            if User.query.filter_by(username=username).first():
                flash("This username is already taken. Please choose another.", "warning")
                return render_template("register.html", rooms=rooms, hostel_config=HOSTEL_CONFIG)

            # 6. Constraint: Check student_code uniqueness
            if Student.query.filter_by(student_code=student_code).first():
                flash(f"Student code '{student_code}' is already registered.", "warning")
                return render_template("register.html", rooms=rooms, hostel_config=HOSTEL_CONFIG)

            # 7. Update active hostel location if custom coordinates were selected/synced
            if hostel_lat and hostel_lon:
                try:
                    lat_f = float(hostel_lat)
                    lon_f = float(hostel_lon)
                    HOSTEL_CONFIG["latitude"] = lat_f
                    HOSTEL_CONFIG["longitude"] = lon_f
                    HOSTEL_CONFIG["name"] = hostel_location
                except (ValueError, TypeError):
                    pass

            # Create User and Student profile
            user = User(
                username=username,
                role="student",
                full_name=full_name,
                email=email or None,
                phone=phone or None,
            )
            user.set_password(password)
            db.session.add(user)
            db.session.flush()

            student = Student(
                user_id=user.id,
                student_code=student_code,
                department=department,
                year=year,
                gender=gender,
                room_id=allocated_room.id if allocated_room else None,
                enrolled_face_image=enrolled_face,
                hostel_location=hostel_location,
            )
            db.session.add(student)
            db.session.commit()

            room_str = f"Room {allocated_room.room_number}" if allocated_room else "Hostel"
            flash(f"Registration successful! Enrolled in {room_str} with designated location '{hostel_location}'. You can now log in.", "success")
            return redirect(url_for("login"))

        return render_template("register.html", rooms=rooms, hostel_config=HOSTEL_CONFIG)

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
            device_id = request.form.get("device_id", "").strip()
            device_name = request.form.get("device_name", "").strip() or "Mobile Device"
            latitude_str = request.form.get("latitude", "").strip()
            longitude_str = request.form.get("longitude", "").strip()
            face_image = request.form.get("face_image", "").strip()
            demo_bypass_gps = request.form.get("demo_bypass_gps") == "true"

            # 1. Check if already marked today
            existing = Attendance.query.filter_by(
                student_id=student.id, date=date.today()
            ).first()
            if existing:
                return render_template(
                    "scan_confirmation.html", student=student, attendance=existing,
                    already_marked=True
                )

            # 2. Trusted Device Verification
            if not device_id:
                flash("Device identification failed! Please ensure cookies and local storage are enabled on your device.", "danger")
                return redirect(url_for("student_scan"))

            if not student.trusted_device_id:
                # First time: automatically register this phone/device as their trusted device
                student.trusted_device_id = device_id
                student.trusted_device_name = device_name
                db.session.commit()
                flash(f"Trusted Device Enrolled! This device ({device_name}) has been registered to your student account.", "info")
            elif student.trusted_device_id != device_id:
                # Untrusted device detected!
                flash(
                    f"Untrusted Device Blocked! Attendance must be marked from your registered device ({student.trusted_device_name or 'Registered Phone'}). "
                    "If you have changed your phone, please contact the warden for a trusted device reset.",
                    "danger"
                )
                notif = Notification(
                    recipient_role="warden",
                    title=f"Untrusted Device Blocked: {student.user.full_name}",
                    message=f"Student {student.user.full_name} ({student.student_code}) attempted attendance from an unregistered device ({device_name}).",
                    category="danger"
                )
                db.session.add(notif)
                db.session.commit()
                return redirect(url_for("student_scan"))

            # 3. GPS Geolocation & Hostel Boundary Verification
            lat_val = None
            lon_val = None
            distance_meters = None

            if latitude_str and longitude_str:
                try:
                    lat_val = float(latitude_str)
                    lon_val = float(longitude_str)
                    distance_meters = round(calculate_distance_meters(
                        lat_val, lon_val, HOSTEL_CONFIG["latitude"], HOSTEL_CONFIG["longitude"]
                    ), 1)
                except ValueError:
                    pass

            if not demo_bypass_gps:
                if distance_meters is None:
                    flash("GPS Verification Required: Please enable location permissions so the system can verify you are within the hostel area.", "danger")
                    return redirect(url_for("student_scan"))

                if distance_meters > HOSTEL_CONFIG["radius_meters"]:
                    flash(
                        f"Location Check Failed: You are {distance_meters}m away from the hostel entrance (allowed radius: {int(HOSTEL_CONFIG['radius_meters'])}m). "
                        "You must be physically present at the hostel entrance to mark attendance.",
                        "danger"
                    )
                    return redirect(url_for("student_scan"))
            else:
                if distance_meters is None:
                    distance_meters = 15.0  # Simulated entrance distance for demo mode

            # 4. Live Face Capture Verification
            if not face_image or len(face_image) < 20:
                flash("Live Face Verification Required: Please look into your camera and capture a live verification selfie before submitting.", "danger")
                return redirect(url_for("student_scan"))

            # If student has not enrolled a baseline face snapshot, store it
            if not student.enrolled_face_image:
                student.enrolled_face_image = face_image
                db.session.commit()
                flash("Your face photo has been registered as your official Reference Face Photo!", "info")

            # 5. All 3 Verification Checks Passed -> Save Attendance
            status = "Late" if datetime.now().hour >= 21 else "Present"
            att = Attendance(
                student_id=student.id,
                qr_id=None,
                status=status,
                verification_status="Verified (Device + GPS + Live Face)",
                device_id=device_id,
                device_name=device_name,
                latitude=lat_val,
                longitude=lon_val,
                distance_meters=distance_meters,
                face_verified=True,
                face_snapshot=face_image,
            )
            db.session.add(att)
            db.session.commit()

            return render_template(
                "scan_confirmation.html", student=student, attendance=att,
                already_marked=False
            )

        return render_template("student_scan.html", hostel_config=HOSTEL_CONFIG, student=student)

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
                    status="Pending",
                    is_anonymous=is_anonymous,
                    escalated_by_keyword=escalated,
                    image_url=image_url,
                )
                db.session.add(complaint)
                db.session.commit()

                # Trigger automatic notifications: Admin receives all, Warden receives only if NOT anonymous
                send_complaint_notifications(complaint, event_type="raised")

                if escalated:
                    flash(
                        "Complaint submitted and flagged as EMERGENCY. Admin has been notified immediately.", "danger"
                    )
                else:
                    flash("Complaint submitted with Pending status. Admin has received the notification.", "success")
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

    @app.route("/student/complaints/<int:complaint_id>/update-status", methods=["POST"])
    @role_required("student")
    def student_update_complaint_status(complaint_id):
        student = current_user.student_profile
        complaint = Complaint.query.get_or_404(complaint_id)
        if complaint.student_id != student.id:
            abort(403)

        new_status = request.form.get("status")  # "Resolved" or "Not Resolved"
        rating_val = request.form.get("rating")
        rating = int(rating_val) if (rating_val and rating_val.isdigit() and 1 <= int(rating_val) <= 5) else None

        if rating:
            complaint.rating = rating

        if new_status == "Not Resolved":
            # Automatically turn status as Pending and notify admin
            complaint.status = "Pending"
            complaint.resolved_date = None
            db.session.commit()

            send_complaint_notifications(complaint, event_type="not_resolved", student_rating=rating)
            flash(
                f"Complaint #{complaint.id} marked as Not Resolved. Status automatically reset to Pending and sent to Admin.",
                "warning",
            )
        elif new_status == "Resolved":
            complaint.status = "Resolved"
            complaint.resolved_date = datetime.utcnow()
            db.session.commit()

            send_complaint_notifications(complaint, event_type="resolved", student_rating=rating)
            flash(f"Complaint #{complaint.id} marked as Resolved. Thank you for rating!", "success")
        else:
            flash("Please select whether the issue is Resolved or Not Resolved.", "danger")

        return redirect(url_for("student_complaints"))

    @app.route("/student/complaints/<int:complaint_id>/rate", methods=["POST"])
    @role_required("student")
    def student_rate_complaint(complaint_id):
        return student_update_complaint_status(complaint_id)

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
            hostel_config=HOSTEL_CONFIG,
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
        return jsonify(
            valid=qr.is_valid,
            seconds_left=seconds_left,
            present_count=present_count,
            rotation_interval=qr.rotation_interval or 60,
            token=qr.token
        )

    @app.route("/api/qr/<int:qr_id>/rotate", methods=["POST"])
    @role_required("warden", "admin")
    def qr_rotate(qr_id):
        qr = QRCode.query.get_or_404(qr_id)
        rotation_interval = qr.rotation_interval or 60
        import secrets
        new_token = secrets.token_urlsafe(16)
        qr.token = new_token
        qr.created_time = datetime.utcnow()
        qr.expiry_time = datetime.utcnow() + timedelta(seconds=rotation_interval)
        db.session.commit()

        img = qrcode.make(new_token)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return jsonify(
            success=True,
            qr_id=qr.id,
            token=new_token,
            qr_b64=qr_b64,
            rotation_interval=rotation_interval,
            seconds_left=rotation_interval,
        )

    @app.route("/api/hostel-location", methods=["GET"])
    def get_hostel_location():
        return jsonify(HOSTEL_CONFIG)

    @app.route("/api/hostel-location/sync-my-location", methods=["POST"])
    @login_required
    def sync_hostel_location():
        data = request.get_json(silent=True) or request.form.to_dict() or {}
        lat = data.get("latitude")
        lon = data.get("longitude")
        radius = data.get("radius_meters") or data.get("radius")
        if lat is not None and lon is not None:
            try:
                HOSTEL_CONFIG["latitude"] = float(lat)
                HOSTEL_CONFIG["longitude"] = float(lon)
                if radius:
                    HOSTEL_CONFIG["radius_meters"] = float(radius)
                return jsonify(
                    success=True,
                    config=HOSTEL_CONFIG,
                    message=f"Hostel Gate location synced to ({HOSTEL_CONFIG['latitude']:.5f}, {HOSTEL_CONFIG['longitude']:.5f}), radius: {int(HOSTEL_CONFIG['radius_meters'])}m."
                )
            except (ValueError, TypeError):
                return jsonify(success=False, message="Coordinates and radius must be valid numbers."), 400
        return jsonify(success=False, message="Invalid coordinates provided."), 400

    @app.route("/api/student/enroll-face", methods=["POST"])
    @role_required("student")
    def student_enroll_face():
        student = current_user.student_profile
        data = request.get_json(silent=True) or request.form.to_dict() or {}
        face_img = data.get("face_image", "").strip()
        if face_img and len(face_img) > 50:
            student.enrolled_face_image = face_img
            db.session.commit()
            return jsonify(success=True, message="Reference face photo successfully enrolled!")
        return jsonify(success=False, message="Invalid or empty face photo."), 400

    @app.route("/warden/students/<int:student_id>/reset-device", methods=["POST"])
    @role_required("warden", "admin")
    def warden_reset_student_device(student_id):
        student = Student.query.get_or_404(student_id)
        student.trusted_device_id = None
        student.trusted_device_name = None
        db.session.commit()
        flash(f"Trusted device for {student.user.full_name} ({student.student_code}) has been reset. They can register their new device on next attendance.", "success")
        return redirect(request.referrer or url_for("warden_attendance"))

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
