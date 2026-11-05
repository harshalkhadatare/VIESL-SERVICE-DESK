# Setup, deployment, backup & troubleshooting

## A. Local development (no Docker, SQLite) — quickest
Requires Python 3.11+.
```bash
cd backend
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                      # adjust if needed
alembic upgrade head                                      # create schema
python -m app.seed --demo                                 # reference + fictional demo data
uvicorn app.main:app --reload --port 8000
```
Open http://localhost:8000 — demo accounts are listed on the sign-in page (development only).
API docs: http://localhost:8000/api/docs

Run tests: `cd backend && python -m pytest` (uses a throwaway SQLite DB; 158 tests).

## B. Development with SQL Server (Docker Compose)
```bash
cp .env.docker.example .env.docker      # set strong passwords and SECRET_KEY
docker compose --env-file .env.docker up --build
# demo data (optional, dev only):
docker compose --env-file .env.docker exec api python -m app.seed --demo
```
The `db-init` service creates the `ServiceDesk` database and a least-privilege login `sd_app`
(`deploy/sql/init.sql`). The API container runs `alembic upgrade head` and reference seeding on start.
> Note: the Docker setup and SQL Server path were prepared and the SQL Server DDL was compiled offline,
> but they were **not executed against a live SQL Server** in the build environment. Run the stack once
> in your environment and execute `pytest` against it before go-live (see section F).

## C. Production on a company-managed server
1. **Server:** Linux VM (2 vCPU / 4 GB is ample for a few hundred users) or Windows Server with Docker/Python. SQL Server 2019+ (Standard or the existing corporate instance).
2. **Database:** run `deploy/sql/init.sql` (as DBA). For stricter separation, give `sd_app` only `db_datareader`/`db_datawriter`, and run migrations with a separate `sd_migrator` login that has `db_ddladmin`.
   Use `Encrypt=yes&TrustServerCertificate=no` with a valid SQL Server certificate.
3. **Environment** (`backend/.env` or service environment — never in Git):
   `APP_ENV=production`, `SECRET_KEY=<python -c "import secrets;print(secrets.token_urlsafe(64))">`,
   `COOKIE_SECURE=true`, `DATABASE_URL=mssql+pyodbc://...`, `CORS_ORIGINS=https://servicedesk.yourcompany`,
   `UPLOAD_DIR=/srv/data/uploads` (on a backed-up volume), `ENABLE_SCHEDULER=true` on exactly one instance.
   The app refuses to start in production with a weak secret, insecure cookies or SQLite.
4. **Migrate & seed reference data:** `alembic upgrade head && python -m app.seed` (never `--demo`; it is refused in production).
5. **Create the first administrator** (one-off, from the server shell):
   ```bash
   python - <<'PY'
   from app.core.database import SessionLocal
   from app.core.security import hash_password
   from app.models import User, Role, UserRole
   from sqlalchemy import select
   db = SessionLocal()
   u = User(employee_code="E0001", email="it.admin@yourcompany.com", full_name="IT Administrator",
            password_hash=hash_password(input("Password: ")))
   db.add(u); db.flush()
   db.add(UserRole(user_id=u.id, role_id=db.scalar(select(Role.id).where(Role.code=="it_admin"))))
   db.commit(); print("created", u.id)
   PY
   ```
   Then add departments, locations, users and support-group members (user import / AD sync is on the roadmap).
6. **Run:** `uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2 --proxy-headers --forwarded-allow-ips=127.0.0.1`
   under systemd (or the Docker image), behind Nginx/IIS with TLS (`deploy/nginx/servicedesk.conf`).
   With several workers, keep `ENABLE_SCHEDULER=true` on one process only (e.g. a dedicated worker instance), and note the in-memory rate limiter is per process.
7. **Email notifications:** see section H.

## D. Backup & restore
- **Database (SQL Server):** full backup nightly + transaction log backups every 15 min (Full recovery model).
  ```sql
  BACKUP DATABASE ServiceDesk TO DISK = N'/var/opt/mssql/backup/ServiceDesk_full.bak' WITH COMPRESSION, CHECKSUM, INIT;
  BACKUP LOG ServiceDesk TO DISK = N'/var/opt/mssql/backup/ServiceDesk_log.trn' WITH COMPRESSION, CHECKSUM;
  ```
  Restore:
  ```sql
  RESTORE DATABASE ServiceDesk FROM DISK = N'.../ServiceDesk_full.bak' WITH NORECOVERY, REPLACE;
  RESTORE LOG ServiceDesk FROM DISK = N'.../ServiceDesk_log.trn' WITH RECOVERY;
  ```
- **Attachments:** back up `UPLOAD_DIR` with the same schedule (files are immutable; incremental copies work well). The DB stores each file's SHA-256 for integrity checks.
- **Test restores quarterly** into a non-production server and log in to verify.
- **Retention (recommended policy, to be approved):** closed tickets 7 years; audit logs 3 years; notifications 12 months; revoked refresh tokens 30 days. Purge jobs are on the roadmap — until then run them as scheduled SQL agent jobs.

## E. Troubleshooting
| Symptom | Cause / fix |
|---|---|
| App exits: "SECRET_KEY must be set…" | Production guard. Set a strong `SECRET_KEY`, `COOKIE_SECURE=true`, a SQL Server URL. |
| `pyodbc` "Data source name not found" | Install **ODBC Driver 18 for SQL Server** and use `driver=ODBC+Driver+18+for+SQL+Server`. |
| SSL error connecting to SQL Server | Install the server certificate's CA, or (dev only) `TrustServerCertificate=yes`. |
| Signed out every few minutes | Refresh cookie not stored: when using plain HTTP set `COOKIE_SECURE=false` (dev only); check the proxy forwards cookies and the site is same-origin. |
| "Too many sign-in attempts" | Login rate limit (default 10/min/IP). Behind a proxy, enable `--proxy-headers` so the real client IP is used. |
| "Account temporarily locked" | 5 failed attempts → 15-minute lock. An admin can deactivate/activate the user to clear it. |
| Upload rejected "content does not match" | File extension and content differ (e.g. renamed .exe). Only listed types are allowed. |
| SLA due dates look wrong | Check the business calendar hours/working days/holidays and the user's timezone. |
| No SLA warnings / auto-close | `ENABLE_SCHEDULER=true` on exactly one instance; check logs for `servicedesk.scheduler`. |

## F. Verifying against SQL Server
```bash
DATABASE_URL="mssql+pyodbc://sd_app:...@host/ServiceDesk_Test?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=yes" \
  alembic upgrade head && python -m app.seed --demo
```
Point the test suite at a disposable SQL Server database by editing `DATABASE_URL` in `tests/conftest.py`.

## G. Vercel + free Neon PostgreSQL (permanent data, no cost)
Vercel runs the app; **Neon** (free plan: no credit card, 1 GB storage) keeps the data permanently.
Users, tickets, comments, notifications and attachments (stored inside the database) all survive restarts.

1. **Create the database** — Vercel dashboard → your project → **Storage** → **Create Database** → **Neon** → choose
   the **Free** plan and a region close to you (e.g. *Asia Pacific (Singapore)* or *Mumbai* if offered) → **Create**.
2. **Connect it** — on the database page click **Connect Project**, pick `viesl-service-desk`, tick **Production**
   (and Preview if you like) → **Connect**. Vercel adds `DATABASE_URL` and related variables automatically.
3. **Add these environment variables** (Project → Settings → Environment Variables):

| Variable | Value |
|---|---|
| `SECRET_KEY` | a long random string — PowerShell: `python -c "import secrets;print(secrets.token_urlsafe(64))"` |
| `BOOTSTRAP_ADMIN_EMAIL` | your email, e.g. `harshal@visioninfra.co.in` |
| `BOOTSTRAP_ADMIN_PASSWORD` | first password (10+ characters, upper + lower case + a digit) |
| `BOOTSTRAP_ADMIN_NAME` | your name |
| `CRON_SECRET` | any long random string (protects the daily job endpoint) |
| `DEMO_SEED` | optional: `true` to add the fictional demo users and tickets |

4. **Redeploy** (Deployments → ⋯ → Redeploy). On start-up the app creates all tables and reference data,
   then your administrator account.
5. The bootstrap administrator is created **once**; deleting it later in Users & roles is permanent.
   Sign in with the bootstrap email/password, change the password (your name → Change password), then add
   colleagues under **Users & roles → Add user**. You can delete `BOOTSTRAP_ADMIN_PASSWORD` afterwards.

How it works on Vercel
- `api/index.py` detects `DATABASE_URL`, runs the Alembic migrations and seeds reference data on each cold start
  (safe to repeat). Without `DATABASE_URL` it falls back to a temporary demo database.
- Attachments are stored in the database (`ticket_attachment_blobs`); the limit is 4 MB per file because Vercel
  rejects requests larger than 4.5 MB.
- There is no always-on background process, so SLA checks, auto-close and email retries run after user actions
  (at most every 10 minutes) plus once a day via Vercel Cron (`vercel.json` → `/api/v1/internal/jobs`).
- Neon's free compute pauses after 5 minutes without use; the first request afterwards takes about a second longer.

**Speed check:** open `https://viesl-service-desk.vercel.app/api/v1/health`. `db_round_trip_ms` under ~20 is fast;
above ~60 means Vercel and Neon are in different regions (fix below).

**Speed tip — put the app next to the database.** Every request talks to Neon, so the Vercel function should run in
the same region as your Neon database. Check Neon's region (Neon console → project → Settings), then in Vercel open
Project → Settings → Functions → **Function Region** and pick the matching one (e.g. Neon *Singapore* → Vercel
*Singapore, sin1*; Neon *US East* → Vercel *Washington, iad1*), then redeploy. A mismatch adds a delay to every click.
Start-up is fast after the first deployment: migrations and reference data run only when they change, static files are
cached on Vercel's CDN, and database connections are reused between requests.

Free-plan limits to keep in mind: Neon 1 GB storage (roughly tens of thousands of tickets plus a few hundred
screenshots) and 100 compute hours per month; Vercel Hobby is for non-commercial use — check Vercel's terms for
company use, or move to a company server (section C) later. The same code also runs on SQL Server.

## H. Email notifications (erp_helpdesk@visioninfraindia.com)

**Who gets which email**
| Event | Email goes to |
|---|---|
| New ticket — IT department | the employee ("we've received it") + every **IT** administrator |
| New ticket — ERP-IT department | the employee + every **ERP-IT** administrator |
| New ticket — Both | the employee + all IT and ERP-IT administrators |
| Assigned / re-assigned / moved to another team | the employee + the newly assigned administrator |
| Accept & start, every status change, priority change, IT reply, file added by IT, resolved, closed | the employee |
| Employee replies / reopens | the assigned administrator (or the department's administrators if unassigned) |
| Ticket **deleted** | nobody by email (in-app notice only) |

Internal notes are never emailed to employees. Each email has an animated picture for the kind of update, a progress
tracker (Submitted → Assigned → In progress → Resolved → Closed) and the ticket details. People without a real
email (imported with only USER_ID/USER_NAME) are skipped — add their email in Users & roles → Edit or the Excel import.
Administrators need a department (Users & roles → Edit → IT department) so new tickets reach the right people.

**Using the mailbox that another project already uses** — that is fine: one mailbox can send for several
applications. Copy the same SMTP settings the other project uses into Vercel → Project → Settings → Environment Variables:

| Variable | Value |
|---|---|
| `EMAIL_ENABLED` | `true` |
| `SMTP_FROM` | `erp_helpdesk@visioninfraindia.com` |
| `SMTP_FROM_NAME` | `VIESL IT Service Desk` |
| `SMTP_USERNAME` | `erp_helpdesk@visioninfraindia.com` |
| `SMTP_PASSWORD` | the mailbox password / app password the other project uses |
| `SMTP_HOST`, `SMTP_PORT` | same as the other project — Microsoft 365: `smtp.office365.com` / `587`; Google Workspace: `smtp.gmail.com` / `587`; Zoho: `smtp.zoho.in` / `587`; cPanel/hosting mail: `mail.visioninfraindia.com` / `587` (or `465` with `SMTP_SSL=true`) |
| `SMTP_STARTTLS` | `true` for port 587 (`SMTP_SSL=true` and `SMTP_STARTTLS=false` for port 465) |
| `APP_BASE_URL` | `https://viesl-service-desk.vercel.app` (links in emails) |

Then redeploy, sign in as an IT Administrator → **Email notifications** → **Send test email**. If it fails, the page
shows the mail server's exact error. Common causes: Microsoft 365 needs "Authenticated SMTP" enabled for the mailbox
(Microsoft 365 admin → Users → the mailbox → Mail → Manage email apps), and accounts with two-step sign-in need an
**app password** instead of the normal password. Sending limits (Microsoft 365 ≈ 30 emails/minute, 10,000/day) are
shared with the other project; a service desk of this size stays far below them.

## I. Setting up a copy for another client company (one repository per client)
1. Copy this repository to a new GitHub repository (e.g. `abc-service-desk`) and import it as a new Vercel project.
2. Create a new Neon database for it (Vercel → Storage → Neon → Connect to the new project). Never share a database
   between clients.
3. Environment variables (Vercel → Settings → Environment Variables): `SECRET_KEY` (new random value),
   `COMPANY_NAME` (e.g. `ABC Engineering Pvt. Ltd.`), `COMPANY_SHORT` (e.g. `ABC · Pune`),
   `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` / `BOOTSTRAP_ADMIN_NAME`, `APP_BASE_URL`, and the client's own
   `SMTP_*` mailbox (section H). Leave `DEMO_SEED` unset.
4. Deploy, sign in with the bootstrap admin, add users (Excel import), set each admin's IT department, send a test email.
Code fixes are made once in your main repository and copied (merged) into each client repository.
