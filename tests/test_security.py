import unittest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from extensions import db
from models import User, Student, Complaint

class TestSecuritySuite(unittest.TestCase):
    """
    Rubric 6 & 8: Security & Privacy Testing Suite
    Validates role-based authorization, security headers, password hashing,
    and cross-tenant privacy boundaries.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    def setUp(self):
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_tc_s01_role_elevation_protection(self):
        """TC-S01: Unauthorized student attempting access to Admin and Warden endpoints is blocked (403/Redirect)."""
        # Log in as Student
        self.client.post("/login", data={"username": "nivetha", "password": "student123"})

        # Try to access Admin dashboard -> MUST fail
        res_admin = self.client.get("/admin/dashboard")
        self.assertEqual(res_admin.status_code, 403)

        # Try to access Warden dashboard -> MUST fail
        res_warden = self.client.get("/warden/dashboard")
        self.assertEqual(res_warden.status_code, 403)

        # Try to access Warden room allocation POST -> MUST fail
        res_alloc = self.client.post("/warden/rooms/allocate", data={"student_id": 1, "room_id": 1})
        self.assertEqual(res_alloc.status_code, 403)

        self.client.get("/logout")

    def test_tc_s02_http_security_headers(self):
        """TC-S02: HTTP Security response headers (nosniff, SAMEORIGIN, XSS-Protection)."""
        res = self.client.get("/login")
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(res.headers.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertEqual(res.headers.get("X-XSS-Protection"), "1; mode=block")
        self.assertEqual(res.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")

    def test_tc_s03_password_cryptographic_hashing(self):
        """TC-S03: Passwords stored as irreversible cryptographic hashes (Werkzeug PBKDF2/scrypt)."""
        users = User.query.all()
        for u in users:
            self.assertFalse(u.password_hash.startswith("password"))
            self.assertFalse(u.password_hash.startswith("admin123"))
            self.assertFalse(u.password_hash.startswith("student123"))
            # Must be a valid salted hash string
            self.assertTrue(
                u.password_hash.startswith("scrypt:") or u.password_hash.startswith("pbkdf2:"),
                f"Password for {u.username} not using standard cryptographic hashing scheme!"
            )

    def test_tc_s04_cross_student_complaint_tampering_blocked(self):
        """TC-S04: A student cannot update or rate another student's complaint."""
        # Find complaint belonging to student 1 (nivetha)
        s1 = User.query.filter_by(username="nivetha").first().student_profile
        s1_complaint = Complaint.query.filter_by(student_id=s1.id).first()
        self.assertIsNotNone(s1_complaint)

        # Find another student (e.g. priya)
        s2_user = User.query.filter_by(username="priya").first()
        if not s2_user:
            # Create a second student if not seeded
            s2_user = User(username="other_student", role="student", full_name="Other Student")
            s2_user.set_password("student123")
            db.session.add(s2_user)
            db.session.flush()
            s2_stud = Student(user_id=s2_user.id, student_code="ST_OTHER")
            db.session.add(s2_stud)
            db.session.commit()

        # Log in as Student 2
        self.client.post("/login", data={"username": s2_user.username, "password": "student123"})

        # Try to modify Student 1's complaint status -> MUST receive 403 Forbidden!
        res_tamper = self.client.post(
            f"/student/complaints/{s1_complaint.id}/update-status",
            data={"status": "Resolved", "rating": "5"}
        )
        self.assertEqual(res_tamper.status_code, 403)
        self.client.get("/logout")

    def test_tc_s05_unauthenticated_protected_route_redirection(self):
        """TC-S05: Unauthenticated access attempts to protected routes redirect to login."""
        protected_routes = [
            "/student/dashboard",
            "/student/attendance/scan",
            "/student/complaints",
            "/warden/dashboard",
            "/warden/attendance",
            "/admin/dashboard",
            "/admin/students",
            "/admin/reports",
        ]
        for route in protected_routes:
            res = self.client.get(route)
            self.assertEqual(res.status_code, 302, f"Route {route} did not redirect unauthenticated user!")
            self.assertIn("/login", res.headers.get("Location", ""))

if __name__ == "__main__":
    unittest.main()
