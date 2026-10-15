"""
Utility script to view or update a user's registered email address in the database.

Usage:
    python set_user_email.py
        -> Lists all users and their currently registered email addresses

    python set_user_email.py <username> <new_email>
        -> Updates <username> with <new_email>
        Example: python set_user_email.py nivetha myrealemail@gmail.com
"""
import os
import sys

# Built-in lightweight .env loader
env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_file):
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))

def get_connection():
    db_url = os.environ.get("DATABASE_URL", "sqlite:///hostel.db")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    if db_url.startswith("postgresql://"):
        import psycopg2
        return "pg", psycopg2.connect(db_url, connect_timeout=10)
    else:
        import sqlite3
        path = db_url.replace("sqlite:///", "")
        return "sqlite", sqlite3.connect(path)

def main():
    db_type, conn = get_connection()
    cur = conn.cursor()

    if len(sys.argv) == 3:
        username = sys.argv[1].strip()
        new_email = sys.argv[2].strip()

        placeholder = "%s" if db_type == "pg" else "?"
        cur.execute(f"SELECT id, full_name, email FROM users WHERE LOWER(username) = LOWER({placeholder})", (username,))
        row = cur.fetchone()
        if not row:
            print(f"[ERROR] User '{username}' was not found in the database.")
            conn.close()
            sys.exit(1)

        user_id, full_name, old_email = row
        cur.execute(f"UPDATE users SET email = {placeholder} WHERE id = {placeholder}", (new_email, user_id))
        conn.commit()
        conn.close()

        print(f"[SUCCESS] Updated user '{username}' ({full_name}):")
        print(f"  Old Email: {old_email or '(none)'}")
        print(f"  New Email: {new_email}")
        print(f"\nYou can now request a password reset for '{username}' or '{new_email}'.")
        print(f"The reset link will be sent to '{new_email}'.")
    else:
        cur.execute("SELECT id, username, role, full_name, email FROM users ORDER BY id ASC")
        rows = cur.fetchall()
        print("=" * 70)
        print(" Registered Users in Database:")
        print("=" * 70)
        for r in rows:
            uid, uname, role, fname, email = r
            email_display = email if email else "(NO EMAIL CONFIGURED)"
            print(f"  ID: {uid:<2} | User: {uname:<18} | Role: {role:<9} | Email: {email_display}")
        print("=" * 70)
        print("To assign your real email to a user, run:")
        print("    python set_user_email.py <username> <your_actual_email>")
        print("\nExample:")
        print("    python set_user_email.py nivetha myemail@gmail.com")
        conn.close()

if __name__ == "__main__":
    main()
