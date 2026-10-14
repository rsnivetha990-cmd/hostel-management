# Smart Hostel Management System

A working Flask implementation of the 5 core modules from your project spec:

1. **Login & Role Management** – Admin / Warden / Student, role-based access control
2. **QR-Based Attendance** – dynamic QR codes that expire after a few minutes (prevents screenshot sharing)
3. **Smart Room Allocation** – recommends the best room by gender match + least-empty-bed-first logic
4. **Complaint Management** – auto-assigns priority (Emergency/High/Medium/Low) by category, status workflow (Pending → In Progress → Resolved), plus three enhancements:
   - **Anonymous complaints** – students can hide their name from the warden's view for sensitive issues
   - **Satisfaction rating** – students rate resolved complaints 1–5 stars, feeding an average shown on the admin Reports page
   - **Emergency keyword auto-escalation** – if the description mentions safety-related words (fire, harassment, gas leak, etc.), priority is forced to Emergency regardless of the category picked, and the complaint is highlighted in red on the warden's list
5. **Admin/Warden Dashboard & Reports** – live stats + Chart.js graphs (attendance trend, complaints by category)

## Tech stack used
- Backend: Python + Flask, Flask-SQLAlchemy, Flask-Login
- Database: SQLite (swap the URI in `app.py` for MySQL/Postgres in production)
- Frontend: HTML + Bootstrap 5 + Chart.js
- QR: `qrcode` library for generation, `html5-qrcode` (camera) or manual token entry for scanning

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create & seed the database (creates admin/warden/5 sample students, 6 rooms)
python seed.py

# 3. Run the app
python app.py
```

Then open **http://127.0.0.1:5000**

## Demo logins
| Role    | Username | Password    |
|---------|----------|-------------|
| Admin   | admin    | admin123    |
| Warden  | warden   | warden123   |
| Student | nivetha  | student123  |
| Student | priya / arun / suresh / divya | student123 |

## How to demo the "smart" features

**Dynamic QR attendance:**
1. Log in as `warden` → "Generate QR" → set validity (e.g. 3 min) → Generate
2. The QR page shows a live countdown + live "present" counter
3. Log in as a student (new incognito tab) → "Scan QR" → paste the token shown under the QR (or scan with camera if available) → attendance marked as Present/Late

**Smart room recommendation:**
1. Log in as `warden` or `admin` → Rooms
2. Pick an unassigned student (e.g. Divya) → click "Recommend" → it fills in the best-matching room (gender match, prioritizing rooms that are almost full first, to consolidate occupancy)

**Complaint priority automation:**
1. Log in as a student → Complaints → submit a "Water" or "Electrical" complaint → notice it's auto-tagged High priority
2. Log in as warden → Complaints → list is sorted by priority (Emergency first), update status inline

**Dashboard analytics:**
- Admin → Reports shows a 7-day attendance trend line chart and a complaints-by-category donut chart

## Project structure
```
hostel_system/
├── app.py              # Flask app + cloud config + all routes
├── models.py            # SQLAlchemy models (User, Room, Student, Attendance, Complaint, QRCode)
├── extensions.py        # db & login_manager instances
├── seed.py               # sample data loader with cloud image demo
├── requirements.txt     # dependencies (Flask, Gunicorn, PostgreSQL driver, Cloudinary)
├── Procfile             # web process for Render / Heroku / Koyeb
├── render.yaml          # 1-click cloud deployment blueprint
├── .env.example         # cloud credentials template
├── templates/            # Jinja2 + Bootstrap templates (with photo upload & preview)
└── static/
    ├── css/style.css
    └── uploads/         # local upload fallback if cloud keys omitted
```

## Cloud Services Setup (100% Free)

### 1. Cloud Database (Neon.tech PostgreSQL)
1. Sign up at [neon.tech](https://neon.tech) (Free tier, no credit card required).
2. Create a project `smart-hostel` and copy your connection string:
   ```
   DATABASE_URL=postgresql://user:password@ep-xyz.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
3. Set this in your cloud environment variables or local `.env` file.

### 2. Cloud Object Storage (Cloudinary)
1. Sign up at [cloudinary.com](https://cloudinary.com) (Free 25GB media tier, no credit card required).
2. Copy your credentials from the dashboard and set them:
   ```
   CLOUDINARY_CLOUD_NAME=your_cloud_name
   CLOUDINARY_API_KEY=your_api_key
   CLOUDINARY_API_SECRET=your_api_secret
   ```
   *(Note: If Cloudinary keys are omitted, the system automatically falls back to local storage in `static/uploads/`)*

### 3. Deploy Freely on Render
1. Push this repository to GitHub.
2. Sign up on [render.com](https://render.com) and click **New +** → **Web Service**.
3. Connect your GitHub repository.
4. Settings:
   - **Build Command**: `pip install -r requirements.txt && python seed.py`
   - **Start Command**: `gunicorn app:app`
   - **Plan**: `Free`
5. Add the environment variables (`DATABASE_URL`, `CLOUDINARY_*`, `SECRET_KEY`).
6. Click **Deploy Web Service** to get your public HTTPS URL (e.g. `https://smart-hostel.onrender.com`).

## Notes for your project report/presentation
- **Cloud Architecture**: Ephemeral web tier (Render) + Serverless PostgreSQL (Neon) + CDN Media Object Storage (Cloudinary).
- **The RBAC decorator (`role_required`)** in `app.py` enforces access control.
- **The complaint auto-priority mapping and emergency keyword auto-escalation** demonstrates rule-based safety classification.
- **The QR expiry logic (`QRCode.is_valid`)** protects against attendance sharing/replay.
- **Cloud Media Offloading**: Binary images are never stored in the database; only CDN URLs are saved.

