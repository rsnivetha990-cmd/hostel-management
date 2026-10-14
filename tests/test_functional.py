import unittest
import os
import sys
from datetime import date, datetime

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from extensions import db
from models import User, Student, Room, Attendance, Complaint, Notification

class TestFunctionalSuite(unittest.TestCase):
    """
    Rubric 8: Systematic Functional Testing Suite
    Validates end-to-end functionality across Student, Warden, and Admin workflows.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.app.config["WTF_CSRF_ENABLED"] = False
        cls.client = cls.app.test_client()

    def setUp(self):
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_tc_f01_registration_with_all_constraints(self):
        """TC-F01: Registration with valid member code, room selection, picture, and hostel GPS."""
        room = [r for r in Room.query.all() if r.available_beds > 0][0]
        test_uname = "func_student_01"
        # Cleanup if exists
        u = User.query.filter_by(username=test_uname).first()
        if u:
            Student.query.filter_by(user_id=u.id).delete()
            db.session.delete(u)
            db.session.commit()

        payload = {
            "registration_code": "HOSTEL2026",
            "full_name": "Functional Test Student",
            "student_code": "ST_F01",
            "department": "CSE",
            "year": "2",
            "gender": "female",
            "room_id": str(room.id),
            "room_number": room.room_number,
            "hostel_location_name": "Main Campus Hostel Gate",
            "hostel_lat": "12.9716",
            "hostel_lon": "77.5946",
            "enrolled_face": "data:image/jpeg;base64," + ("A" * 100),
            "email": "functest@hostel.edu",
            "phone": "9876543210",
            "username": test_uname,
            "password": "password123",
            "confirm_password": "password123",
        }
        res = self.client.post("/register", data=payload, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Registration successful", res.data)

        # Verify database entity creation
        created_user = User.query.filter_by(username=test_uname).first()
        self.assertIsNotNone(created_user)
        self.assertEqual(created_user.role, "student")
        self.assertEqual(created_user.student_profile.room_id, room.id)
        self.assertIsNotNone(created_user.student_profile.enrolled_face_image)
        self.assertEqual(created_user.student_profile.hostel_location, "Main Campus Hostel Gate")

    def test_tc_f02_registration_rejected_invalid_code(self):
        """TC-F02: Registration rejected when invalid member code is supplied."""
        payload = {
            "registration_code": "INVALID_CODE_999",
            "full_name": "Intruder User",
            "student_code": "ST_BAD",
            "department": "ECE",
            "year": "1",
            "gender": "male",
            "room_id": "1",
            "enrolled_face": "data:image/jpeg;base64," + ("A" * 100),
            "username": "intruder_user",
            "password": "password123",
            "confirm_password": "password123",
        }
        res = self.client.post("/register", data=payload, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Invalid registration code", res.data)
        self.assertIsNone(User.query.filter_by(username="intruder_user").first())

    def test_tc_f03_registration_rejected_missing_picture(self):
        """TC-F03: Registration rejected if student picture is missing."""
        payload = {
            "registration_code": "HOSTEL2026",
            "full_name": "No Picture User",
            "student_code": "ST_NOPIC",
            "department": "ECE",
            "year": "1",
            "gender": "male",
            "room_id": "1",
            "enrolled_face": "",
            "username": "nopic_user",
            "password": "password123",
            "confirm_password": "password123",
        }
        res = self.client.post("/register", data=payload, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Student Picture Required", res.data)
        self.assertIsNone(User.query.filter_by(username="nopic_user").first())

    def test_tc_f04_authentication_and_roles(self):
        """TC-F04: Role-based login and redirection for Student, Warden, and Admin."""
        # 1. Admin login
        res_admin = self.client.post("/login", data={"username": "admin", "password": "admin123"}, follow_redirects=True)
        self.assertEqual(res_admin.status_code, 200)
        self.assertIn(b"Admin Dashboard", res_admin.data)
        self.client.get("/logout")

        # 2. Warden login
        res_warden = self.client.post("/login", data={"username": "warden", "password": "warden123"}, follow_redirects=True)
        self.assertEqual(res_warden.status_code, 200)
        self.assertIn(b"Warden Dashboard", res_warden.data)
        self.client.get("/logout")

        # 3. Student login
        res_student = self.client.post("/login", data={"username": "nivetha", "password": "student123"}, follow_redirects=True)
        self.assertEqual(res_student.status_code, 200)
        self.assertIn(b"Student Dashboard", res_student.data)
        self.client.get("/logout")

    def test_tc_f05_3pillar_attendance_verification(self):
        """TC-F05: 3-Pillar Attendance (Device Binding + GPS Geofence + Live Face Snapshot)."""
        student_user = User.query.filter_by(username="nivetha").first()
        student = student_user.student_profile

        # Reset today's attendance for clean test
        Attendance.query.filter_by(student_id=student.id, date=date.today()).delete()
        db.session.commit()

        self.client.post("/login", data={"username": "nivetha", "password": "student123"})
        payload = {
            "device_id": student.trusted_device_id or "test_bound_phone_uuid",
            "device_name": "Test iPhone 15 Pro",
            "latitude": "12.9716",
            "longitude": "77.5946",
            "face_image": "data:image/jpeg;base64," + ("B" * 120),
            "demo_bypass_gps": "true"
        }
        res = self.client.post("/student/attendance/scan", data=payload, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Attendance Successfully Marked", res.data)

        # Verify database record
        att = Attendance.query.filter_by(student_id=student.id, date=date.today()).first()
        self.assertIsNotNone(att)
        self.assertIsNone(att.qr_id)  # Zero QR reliance!
        self.assertTrue(att.face_verified)
        self.assertEqual(att.verification_status, "Verified (Device + GPS + Live Face)")
        self.client.get("/logout")

    def test_tc_f06_untrusted_device_blocking(self):
        """TC-F06: Anti-proxy mechanism blocks attendance attempts from unregistered devices."""
        student_user = User.query.filter_by(username="nivetha").first()
        student = student_user.student_profile
        student.trusted_device_id = "real_student_registered_phone"
        # Ensure no attendance record exists today so device check is evaluated
        Attendance.query.filter_by(student_id=student.id, date=date.today()).delete()
        db.session.commit()

        self.client.post("/login", data={"username": "nivetha", "password": "student123"})
        # Attempt attendance from friend's phone
        payload = {
            "device_id": "friend_phone_untrusted_device_id",
            "device_name": "Friend's Android",
            "latitude": "12.9716",
            "longitude": "77.5946",
            "face_image": "data:image/jpeg;base64," + ("C" * 100),
            "demo_bypass_gps": "true"
        }
        res = self.client.post("/student/attendance/scan", data=payload, follow_redirects=True)
        self.assertIn(b"Untrusted Device Blocked", res.data)

        # Check that alert notification was created for warden
        notif = Notification.query.filter(
            Notification.recipient_role == "warden",
            Notification.title.like("%Untrusted Device Blocked%")
        ).first()
        self.assertIsNotNone(notif)
        self.client.get("/logout")

    def test_tc_f07_complaint_emergency_auto_escalation(self):
        """TC-F07: Autonomous NLP/keyword-based complaint escalation to Emergency."""
        self.client.post("/login", data={"username": "nivetha", "password": "student123"})
        payload = {
            "category": "Electrical",
            "description": "Urgent! Short circuit sparking near water pipe, risk of fire!",
        }
        res = self.client.post("/student/complaints", data=payload, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # Verify escalated priority in database
        latest_c = Complaint.query.filter(Complaint.description.like("%Short circuit%")).first()
        self.assertIsNotNone(latest_c)
        self.assertEqual(latest_c.priority, "Emergency")
        self.assertTrue(latest_c.escalated_by_keyword)
        self.client.get("/logout")

    def test_tc_f08_anonymous_complaint_privacy(self):
        """TC-F08: Anonymous complaint privacy: Admin notified, Warden withheld."""
        self.client.post("/login", data={"username": "nivetha", "password": "student123"})
        payload = {
            "category": "Food/Mess",
            "description": "Sensitive mess grievance submitted anonymously for hostel inspection.",
            "is_anonymous": "on"
        }
        res = self.client.post("/student/complaints", data=payload, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        latest_c = Complaint.query.filter(Complaint.description.like("%Sensitive mess%")).first()
        self.assertIsNotNone(latest_c)
        self.assertTrue(latest_c.is_anonymous)

        # Admin MUST have a notification for this complaint
        admin_n = Notification.query.filter_by(complaint_id=latest_c.id, recipient_role="admin").first()
        self.assertIsNotNone(admin_n)

        # Warden MUST NOT have a notification for this anonymous complaint
        warden_n = Notification.query.filter_by(complaint_id=latest_c.id, recipient_role="warden").first()
        self.assertIsNone(warden_n)
        self.client.get("/logout")

    def test_tc_f09_complaint_resolution_workflow(self):
        """TC-F09: Student marks complaint Not Resolved -> auto-reopens as Pending & notifies admin."""
        student_user = User.query.filter_by(username="nivetha").first()
        complaint = Complaint.query.filter_by(student_id=student_user.student_profile.id).first()
        self.assertIsNotNone(complaint)

        self.client.post("/login", data={"username": "nivetha", "password": "student123"})
        payload = {
            "status": "Not Resolved",
            "rating": "2"
        }
        res = self.client.post(f"/student/complaints/{complaint.id}/update-status", data=payload, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        db.session.refresh(complaint)
        self.assertEqual(complaint.status, "Pending")
        self.assertEqual(complaint.rating, 2)
        self.client.get("/logout")

    def test_tc_f10_warden_gps_gate_calibration(self):
        """TC-F10: Warden 1-click GPS gate calibration API."""
        self.client.post("/login", data={"username": "warden", "password": "warden123"})
        payload = {
            "latitude": 13.0827,
            "longitude": 80.2707,
            "radius_meters": 200
        }
        res = self.client.post("/api/hostel-location/sync-my-location", json=payload)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json["success"])
        self.assertEqual(res.json["config"]["latitude"], 13.0827)
        self.assertEqual(res.json["config"]["radius_meters"], 200.0)
        self.client.get("/logout")

if __name__ == "__main__":
    unittest.main()
