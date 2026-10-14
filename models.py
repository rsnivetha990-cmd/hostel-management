from datetime import datetime, timedelta
import secrets
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # admin, warden, student
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))

    student_profile = db.relationship(
        "Student", backref="user", uselist=False, cascade="all, delete-orphan"
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Room(db.Model):
    __tablename__ = "rooms"

    id = db.Column(db.Integer, primary_key=True)
    block = db.Column(db.String(20), nullable=False)
    floor = db.Column(db.Integer, nullable=False)
    room_number = db.Column(db.String(20), unique=True, nullable=False)
    capacity = db.Column(db.Integer, nullable=False, default=4)
    gender = db.Column(db.String(10), default="any")
    status = db.Column(db.String(20), default="active")

    students = db.relationship("Student", backref="room", lazy=True)

    @property
    def occupied_count(self):
        return len(self.students)

    @property
    def available_beds(self):
        return max(self.capacity - self.occupied_count, 0)

    def to_dict(self):
        return {
            "id": self.id,
            "room_number": self.room_number,
            "block": self.block,
            "floor": self.floor,
            "capacity": self.capacity,
            "occupied": self.occupied_count,
            "available": self.available_beds,
            "gender": self.gender,
            "status": self.status,
        }


class Student(db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    student_code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    department = db.Column(db.String(80))
    year = db.Column(db.Integer)
    gender = db.Column(db.String(10), default="any")
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"), nullable=True)

    # --- Anti-Proxy Verifications ---
    trusted_device_id = db.Column(db.String(120), nullable=True)
    trusted_device_name = db.Column(db.String(120), nullable=True)
    enrolled_face_image = db.Column(db.Text, nullable=True)
    hostel_location = db.Column(db.String(120), nullable=True)

    attendances = db.relationship("Attendance", backref="student", lazy=True)
    complaints = db.relationship("Complaint", backref="student", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "student_code": self.student_code,
            "name": self.user.full_name,
            "department": self.department,
            "year": self.year,
            "room": self.room.room_number if self.room else None,
            "trusted_device": self.trusted_device_name or "Not Registered",
        }


class QRCode(db.Model):
    __tablename__ = "qr_codes"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False)
    created_time = db.Column(db.DateTime, default=datetime.utcnow)
    expiry_time = db.Column(db.DateTime, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    session_label = db.Column(db.String(40), default="General")
    rotation_interval = db.Column(db.Integer, default=60)

    @staticmethod
    def generate(validity_seconds=60, created_by=None, session_label="General"):
        qr = QRCode(
            token=secrets.token_urlsafe(16),
            expiry_time=datetime.utcnow() + timedelta(seconds=validity_seconds),
            created_by=created_by,
            session_label=session_label,
            rotation_interval=validity_seconds,
        )
        db.session.add(qr)
        db.session.commit()
        return qr

    @property
    def is_valid(self):
        return datetime.utcnow() <= self.expiry_time


class Attendance(db.Model):
    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    date = db.Column(db.Date, default=lambda: datetime.utcnow().date(), index=True)
    time = db.Column(db.DateTime, default=datetime.utcnow)
    qr_id = db.Column(db.Integer, db.ForeignKey("qr_codes.id"))
    status = db.Column(db.String(20), default="Present")

    # --- Combined Verification Pillars ---
    verification_status = db.Column(db.String(80), default="Verified")
    device_id = db.Column(db.String(120), nullable=True)
    device_name = db.Column(db.String(120), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    distance_meters = db.Column(db.Float, nullable=True)
    face_verified = db.Column(db.Boolean, default=False)
    face_snapshot = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("student_id", "date", name="uix_student_date"),
    )


class Complaint(db.Model):
    __tablename__ = "complaints"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    category = db.Column(db.String(40), nullable=False)
    description = db.Column(db.Text, nullable=False)
    priority = db.Column(db.String(10), default="Medium", index=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default="Pending", index=True)
    assigned_to = db.Column(db.String(120))
    resolved_date = db.Column(db.DateTime)

    # --- quick-win enhancements ---
    is_anonymous = db.Column(db.Boolean, default=False)
    rating = db.Column(db.Integer, nullable=True)  # 1-5, set by student after resolution
    escalated_by_keyword = db.Column(db.Boolean, default=False)
    image_url = db.Column(db.String(500), nullable=True)  # Cloudinary or cloud storage CDN URL

    CATEGORY_PRIORITY = {
        "Water": "High",
        "Electrical": "High",
        "Fire/Safety": "Emergency",
        "Bathroom": "Medium",
        "Wi-Fi": "Low",
        "Cleaning": "Low",
        "Food/Mess": "Medium",
        "Room": "Medium",
        "Maintenance": "Medium",
    }

    # Keywords that force Emergency priority regardless of chosen category,
    # in case a student picks the wrong dropdown option under stress.
    EMERGENCY_KEYWORDS = [
        "fire", "smoke", "spark", "sparking", "gas leak", "burning",
        "electrocut", "short circuit", "flood", "flooding", "collapse",
        "unconscious", "bleeding", "assault", "harassment", "stalking",
        "intruder", "break-in", "trapped", "explosion", "toxic",
    ]

    @staticmethod
    def auto_priority(category, description=""):
        text = (description or "").lower()
        if any(kw in text for kw in Complaint.EMERGENCY_KEYWORDS):
            return "Emergency", True
        return Complaint.CATEGORY_PRIORITY.get(category, "Medium"), False

    @property
    def display_name(self):
        """Name shown to warden -- hidden if the complaint was filed anonymously."""
        return "Anonymous" if self.is_anonymous else self.student.user.full_name


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    recipient_role = db.Column(db.String(20), nullable=False, index=True)  # "admin" or "warden"
    recipient_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey("complaints.id"), nullable=True)
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(40), default="info")  # "danger", "warning", "info", "success"
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False, index=True)

    complaint = db.relationship("Complaint", backref=db.backref("notifications", cascade="all, delete-orphan"))
