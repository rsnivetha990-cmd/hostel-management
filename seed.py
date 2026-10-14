"""Run once to create tables and load sample data.
   Usage: python seed.py [--force]
"""
import sys
from datetime import datetime, timedelta
from app import create_app
from extensions import db
from models import User, Room, Student, Complaint

app = create_app()

force_seed = "--force" in sys.argv

with app.app_context():
    if not force_seed and User.query.filter_by(username="admin").first():
        print("Database already initialized with admin user. Skipping seed to preserve existing records.")
        sys.exit(0)

    if force_seed:
        db.drop_all()

    db.create_all()

    admin = User(username="admin", role="admin", full_name="Hostel Admin", email="admin@hostel.edu")
    admin.set_password("admin123")

    warden = User(username="warden", role="warden", full_name="Mr. Ramesh Kumar", email="warden@hostel.edu")
    warden.set_password("warden123")

    db.session.add_all([admin, warden])

    rooms_data = [
        ("A", 1, "A101", 4, "male"),
        ("A", 1, "A102", 4, "male"),
        ("A", 1, "A103", 4, "male"),
        ("B", 1, "B101", 4, "female"),
        ("B", 1, "B102", 4, "female"),
        ("B", 2, "B201", 2, "female"),
    ]
    rooms = []
    for block, floor, num, cap, gender in rooms_data:
        r = Room(block=block, floor=floor, room_number=num, capacity=cap, gender=gender)
        db.session.add(r)
        rooms.append(r)
    db.session.flush()

    students_data = [
        # (username, name, code, dept, year, gender, room, bed_number)
        ("nivetha", "Nivetha S", "ST001", "CSE", 2, "female", rooms[3], 1),
        ("priya",   "Priya R",   "ST002", "ECE", 2, "female", rooms[3], 2),
        ("arun",    "Arun Kumar","ST003", "CSE", 3, "male",   rooms[0], 1),
        ("suresh",  "Suresh M",  "ST004", "MECH",1, "male",   rooms[0], 2),
        ("divya",   "Divya K",   "ST005", "IT",  2, "female", None,     None),
    ]
    for username, name, code, dept, year, gender, room, bed_num in students_data:
        u = User(username=username, role="student", full_name=name, email=f"{username}@hostel.edu")
        u.set_password("student123")
        db.session.add(u)
        db.session.flush()
        s = Student(
            user_id=u.id, student_code=code, department=dept,
            year=year, gender=gender, room_id=room.id if room else None,
            bed_number=bed_num
        )
        db.session.add(s)

    db.session.flush()

    # --- Sample complaints demonstrating the new features ---
    student_map = {s.student_code: s for s in Student.query.all()}

    sample_complaints = [
        # (student_code, category, description, status, is_anonymous, rating, days_ago)
        ("ST001", "Electrical", "Room fan not working since yesterday.", "Resolved", False, 5, 4),
        ("ST002", "Wi-Fi", "Wi-Fi signal very weak in B101.", "Pending", False, None, 1),
        ("ST003", "Food/Mess", "Food quality has dropped this week.", "In Progress", False, None, 2),
        ("ST004", "Room", "Someone keeps entering our room without knocking, feels unsafe.",
         "Pending", True, None, 0),  # anonymous
        ("ST005", "Water", "Water leakage near the bathroom, sparking noticed near the switchboard too.",
         "Pending", False, None, 0),  # will auto-escalate due to "sparking"
    ]
    for code, category, desc, status, anon, rating, days_ago in sample_complaints:
        s = student_map.get(code)
        if not s:
            continue
        priority, escalated = Complaint.auto_priority(category, desc)
        c = Complaint(
            student_id=s.id,
            category=category,
            description=desc,
            priority=priority,
            status=status,
            is_anonymous=anon,
            rating=rating,
            escalated_by_keyword=escalated,
            image_url="https://images.unsplash.com/photo-1584622650111-993a426fbf0a?w=500&q=80" if code == "ST005" else None,
            date=datetime.utcnow() - timedelta(days=days_ago),
            resolved_date=datetime.utcnow() - timedelta(days=max(days_ago - 1, 0)) if status == "Resolved" else None,
        )
        db.session.add(c)

    db.session.commit()
    print("Database seeded successfully!")
    print("\nLogin credentials:")
    print("  Admin   -> username: admin   password: admin123")
    print("  Warden  -> username: warden  password: warden123")
    print("  Student -> username: nivetha password: student123 (also priya/arun/suresh/divya)")
