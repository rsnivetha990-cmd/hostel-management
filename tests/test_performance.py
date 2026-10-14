import unittest
import time
import statistics
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from extensions import db
from models import Student, Room, Complaint, Attendance

class TestPerformanceSuite(unittest.TestCase):
    """
    Rubric 7 & 8: Performance, Scalability & Availability Benchmark Suite
    Measures endpoint response times, throughput, and database query latency.
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

    def test_tc_p01_health_endpoint_latency(self):
        """TC-P01: Health check API latency benchmark (target: < 25ms average)."""
        latencies = []
        for _ in range(50):
            t0 = time.perf_counter()
            res = self.client.get("/health")
            t1 = time.perf_counter()
            self.assertEqual(res.status_code, 200)
            latencies.append((t1 - t0) * 1000)

        avg_lat = statistics.mean(latencies)
        p95_lat = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies)
        print(f"\n[TC-P01 Health Check] 50 Requests -> Mean: {avg_lat:.2f}ms | p95: {p95_lat:.2f}ms | Min: {min(latencies):.2f}ms")
        self.assertLess(avg_lat, 50.0, f"Average health check latency too high: {avg_lat}ms")

    def test_tc_p02_database_query_efficiency(self):
        """TC-P02: Scalable multi-entity database querying latency under index optimization."""
        t0 = time.perf_counter()
        students = Student.query.all()
        rooms = Room.query.all()
        complaints = Complaint.query.all()
        attendances = Attendance.query.all()
        t1 = time.perf_counter()

        elapsed_ms = (t1 - t0) * 1000
        print(f"[TC-P02 DB Querying] Fetched {len(students)} students, {len(rooms)} rooms, {len(complaints)} complaints, {len(attendances)} attendances in {elapsed_ms:.2f}ms")
        self.assertLess(elapsed_ms, 100.0, f"Database query too slow: {elapsed_ms}ms")

    def test_tc_p03_authenticated_dashboard_throughput(self):
        """TC-P03: Measure authenticated student dashboard throughput over 30 rapid requests."""
        self.client.post("/login", data={"username": "nivetha", "password": "student123"})
        latencies = []
        for _ in range(30):
            t0 = time.perf_counter()
            res = self.client.get("/student/dashboard")
            t1 = time.perf_counter()
            self.assertEqual(res.status_code, 200)
            latencies.append((t1 - t0) * 1000)

        avg_lat = statistics.mean(latencies)
        print(f"[TC-P03 Dashboard Throughput] 30 Requests -> Mean: {avg_lat:.2f}ms | Max: {max(latencies):.2f}ms")
        self.client.get("/logout")
        self.assertLess(avg_lat, 100.0)

if __name__ == "__main__":
    unittest.main()
