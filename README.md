<div align="center">

<img src="frontend/assets/logo-full.png" alt="Vision Infra" height="90">

# Vision Infra · IT Service Desk & Task Management

**One web portal for IT tickets, ERP-IT support and internal task assignment, built for Vision Infra Equipment Solutions Ltd. (VIESL).**

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.14x-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%2B-4169E1?logo=postgresql&logoColor=white)
![Vercel](https://img.shields.io/badge/Hosted%20on-Vercel%20(Mumbai)-000000?logo=vercel&logoColor=white)
![Licence](https://img.shields.io/badge/Licence-Proprietary-red)

</div>

---

## Contents
- [What it is](#what-it-is)
- [Screenshots](#screenshots)
- [Features](#features)
- [Roles and permissions](#roles-and-permissions)
- [Tech stack](#tech-stack)
- [Architecture](#architecture)
- [Project structure](#project-structure)
- [Run it locally](#run-it-locally)
- [Configuration](#configuration)
- [Tests](#tests)
- [Deployment](#deployment)
- [Backups](#backups)
- [Documentation](#documentation)
- [Licence](#licence)

---

## What it is

The system has two areas. Users with task rights switch between them from the sidebar.

| Area | Who uses it | What it does |
|---|---|---|
| **IT Service Desk** | Every employee | Raise IT and ERP-IT tickets and follow them to resolution. IT administrators work queues against business-hours SLAs. |
| **Task Management** | Managing Director, IT administrators, Manager L1 and L2 | Assign work with deadlines. People discuss it in a chat-style thread, submit it for approval and ask for deadline extensions. |

Employees sign in with their **Employee ID** and password. Email addresses can't be used to sign in, because many staff share one company mailbox.

---

## Screenshots

| Sign in | Employee home |
|---|---|
| ![Sign in](docs/screenshots/readme/01_login.jpg) | ![Employee home](docs/screenshots/readme/02_emp_home.jpg) |
| **IT dashboard** | **Working a ticket** |
| ![IT dashboard](docs/screenshots/readme/08_admin_dash.jpg) | ![Ticket detail](docs/screenshots/readme/10_admin_ticket.jpg) |
| **Task overview** | **Task conversation** |
| ![Task overview](docs/screenshots/readme/13_tasks_overview.jpg) | ![Task chat](docs/screenshots/readme/16_task_chat.jpg) |
| **Dark mode** | **Phone** |
| ![Dark mode](docs/screenshots/readme/24_dark.jpg) | ![Phone](docs/screenshots/readme/25_mobile_home.jpg) |

*All screenshots use fictional demo data.*

---

## Features

### IT Service Desk (ticketing)
- **Two support desks:** **IT** (hardware, network, email, printers and so on) and **ERP-IT** (ERP issues, Bin Code requests, user accounts and access). Employees pick IT, ERP-IT or Both, then a category and subcategory.
- **Smart ticket form:** extra ERP fields appear for ERP categories. Priority comes from an impact × urgency matrix. The form warns about possible duplicates, suggests knowledge-base articles, and takes attachments (images and PDF).
- **Automatic routing:** a rules engine sends each ticket to the right support group using round-robin or least-loaded assignment. Admins can reassign from the ⋮ menu on any ticket row.
- **Full lifecycle:** status transitions are configured in the database. Some changes need a reason. Resolution and closure are separate steps, with a reopen window and cancel.
- **Conversation:** public replies and private internal notes, the complete change history, and related or duplicate ticket links. Related tickets are shown at the top of *Details*. Employees can rate the service.
- **SLA engine:** runs on a business calendar of working hours, working days and holidays. The clock pauses when it should and never resets. There are breach warnings, escalation, and auto-close, which never applies to protected categories.
  - Default targets: P1 1 h response / 9 h resolve, P2 4 h / 27 h, P3 8 h / 45 h.
- **Dashboards and reports:**
  - an operations dashboard with live and period metrics, trend, mix and workload, switchable between IT, ERP-IT and All;
  - an SLA report and global search;
  - CSV export and a formatted Excel export.
- **Notifications:** in-app notifications plus email through SMTP. New tickets go to the right desk's admins, and employees hear about every step.
- **Admin tools:**
  - users and roles; bulk user import from Excel, and **Export users → edit → upload** to update existing people (email, Employee ID, department, phone, status) with an old → new preview;
  - announcements, the knowledge base, and quick replies;
  - an email settings page with a test send;
  - the audit log and permanent user delete.

### Task Management
- **Overview tiles:** Total, Open, Pending, In progress, Overdue, Completed and Due this week. The Managing Director can switch between *My tasks* and *Whole company*.
- **Assigning tasks:** pick people, a deadline, a priority and attachments. Who can assign to whom follows the role rules below.
- **Views:** by deadline, board and list, with advanced search filters.
- **Chat-style conversation:** each message shows the sender's name. Progress updates, file attachments and deep links to a single file are all in the thread.
- **Approval flow:** the assignee submits the task and the assigner approves it or sends it back. Assignees can request a deadline extension; the assigner approves or rejects it, and can change the deadline at any time.
- **Export to Excel:** sheets for Tasks, Updates and Attachments, with links straight back to each task and file.
- **Few emails:** email is sent only for a new task, a completed task and deadline changes. Everything else stays in the app, under task notifications kept separate from ticket notifications.
- **Privacy:** a task is visible only to its assigner and assignees, plus the Managing Director.

### General
- Sky-themed interface with 7 colour themes and dark mode.
- Collapsible sidebar and layout that works on phones.
- Built-in *How to use* guide.
- Employee ID is shown next to every name.

---

## Roles and permissions

Roles are listed in order of authority.

| Role | Service Desk | Task Management |
|---|---|---|
| **Managing Director** | Sees and comments on every ticket. Tickets the MD raises are **private**: the MD picks the IT admin, and only the MD and that admin see the ticket. | Sees every task and can comment. Assigns to IT admins, Manager L1 and Manager L2. |
| **IT Administrator** | Works, assigns and manages all tickets except the MD's private tickets. Has all admin settings. | Assigns to IT admins, Manager L1 and L2. Sees only tasks they are on. |
| **Manager L1** | Views and comments on all IT and ERP-IT tickets. | Assigns to IT admins, Manager L1 and L2. Sees only tasks they are on. |
| **Manager L2** | Own tickets, like an employee. | Receives and completes tasks; can't assign. |
| **Employee** | Raises and follows own tickets. | No access. |

**Rules:**
- Nobody can assign a task to the Managing Director.
- The MD gets email only when a ticket the MD raised is resolved or closed, or when a task the MD assigned is submitted or completed.

The full matrix is in [docs/PERMISSIONS.md](docs/PERMISSIONS.md), and task rules are in [docs/TASKS.md](docs/TASKS.md).

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, **FastAPI**, Pydantic v2, SQLAlchemy 2, **Alembic** migrations |
| Database | **PostgreSQL** in production. SQLite for local development. Microsoft SQL Server is supported. |
| Frontend | HTML, CSS and vanilla JavaScript (ES modules, **no build step**) |
| Auth | Argon2id passwords, short-lived JWT plus a rotating HttpOnly refresh cookie, lockout, rate limiting |
| Files | Attachments stored in the database or on disk (`ATTACHMENT_STORAGE`) |
| Excel | openpyxl for user import, ticket export and task export |
| Email | SMTP (STARTTLS or SSL) |
| Hosting | Vercel serverless (Mumbai `bom1` region), with a nightly cron job |
| Tests | pytest, run on SQLite and PostgreSQL |

---

## Architecture

```
 Browser (vanilla JS SPA)
        │  HTTPS  helpdesk.visioninfraindia.com
        ▼
 Cloudflare DNS ──► Vercel (bom1, Mumbai)
                     └─ api/index.py → FastAPI app
                          ├─ /api/v1/*      REST API
                          └─ /              static frontend
                                │  TLS (sslmode=require)
                                ▼
                     PostgreSQL on the company Ubuntu server
                          └─ nightly pg_dump backups (14 days kept)
```

---

## Project structure

```
vision-servicedesk/
├── api/index.py              # Vercel entry point (wraps the FastAPI app)
├── vercel.json               # Region, routing, cron
├── backend/
│   ├── app/
│   │   ├── api/v1/           # Routes: auth, tickets, tasks, meta, platform (admin), …
│   │   ├── core/             # Settings, security, errors
│   │   ├── models/           # SQLAlchemy models (tickets, tasks, users, SLA, audit…)
│   │   ├── schemas/          # Pydantic request/response models
│   │   ├── services/         # Business logic: tickets, tasks, SLA, routing, access, notifications, exports
│   │   ├── seed.py           # Roles, permissions, categories, demo data
│   │   └── main.py
│   ├── alembic/versions/     # Migrations 0001 … 0016
│   ├── tests/                # pytest suite
│   └── requirements*.txt
├── frontend/
│   ├── index.html
│   ├── css/app.css
│   ├── js/                   # app.js, api.js, state.js, ui.js, pages/*.js
│   └── assets/               # Logos, background images
├── docs/                     # Architecture, API, permissions, deployment, security, tasks
├── deploy/                   # Server scripts (optional self-hosting)
├── docker-compose.yml
└── LICENSE
```

---

## Run it locally

You need Python 3.12 or newer; nothing else. SQLite is used by default.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env               # Windows: copy .env.example .env
alembic upgrade head
python -m app.seed --demo
uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000** and sign in with a demo Employee ID. The password for every demo user is `Vision@Demo2026`, and all of them are fictional.

| Employee ID | Name | Role |
|---|---|---|
| `D-ADM01` | Rohan Mehta | IT Administrator (Head of IT) |
| `D-ADM02` | Amit Deshmukh | IT Administrator (ERP) |
| `D-ADM04` | Rahul Kulkarni | IT Administrator (Network) |
| `D-EMP01` | Anjali Sharma | Employee (Finance) |
| `D-EMP02` | Manoj Gupta | Employee (Procurement) |

To try the Managing Director, Manager L1 or Manager L2 roles, sign in as `D-ADM01` and give the role to a demo user under **Users & roles**.

> ⚠️ Never point a local copy at the production database. Keep `DATABASE_URL` on SQLite or a local PostgreSQL.

---

## Configuration

All settings come from environment variables: `backend/.env` locally, and *Project → Settings → Environment Variables* on Vercel. The main ones:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | e.g. `sqlite:///./servicedesk.db` or `postgresql+psycopg://user:pass@host:port/servicedesk?sslmode=require` |
| `SECRET_KEY` | Long random string for signing tokens (`openssl rand -hex 32`) |
| `APP_BASE_URL` | Public URL used in email links, e.g. `https://helpdesk.visioninfraindia.com` |
| `APP_TIMEZONE` | `Asia/Kolkata` |
| `EMAIL_ENABLED`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` | Outgoing email |
| `ATTACHMENT_STORAGE`, `MAX_UPLOAD_MB` | Where files are stored, and the size limit |
| `LOGIN_RATE_LIMIT_PER_MINUTE`, `MAX_FAILED_LOGINS`, `LOCKOUT_MINUTES` | Sign-in protection |
| `ENABLE_SCHEDULER` | Background SLA jobs (on Vercel, the daily cron does this) |

See [`backend/.env.example`](backend/.env.example) for the full list.

> 🔒 Never commit `.env`, database passwords or SMTP passwords. On Vercel, mark secrets as **Sensitive**.

---

## Tests

```bash
cd backend
python -m pytest -q                                   # SQLite
TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost/sdtest python -m pytest -q   # PostgreSQL
```

There are **130 tests**. They cover:
- sign-in and lockout;
- the role × action matrix, MD private tickets and the MD email rule;
- ticket lifecycle, routing, SLA, attachments, exports, audit and notifications;
- task assignment rules, task privacy, approvals, extensions, attachments and the Excel export.

---

## Deployment

Production runs on Vercel with the PostgreSQL database on the company server:

1. Push to `main` on GitHub. Vercel builds and deploys automatically.
2. Migrations and seeding of roles, permissions and categories run automatically on start-up.
3. `vercel.json` pins the functions to **`bom1` (Mumbai)**. The functions then sit close to the database, so saves are fast.
4. The custom domain `helpdesk.visioninfraindia.com` is a Cloudflare CNAME to Vercel, set to *DNS only*.

The full guides (Vercel, Docker, SQL Server, self-hosting) are in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

---

## Backups

- The database server runs `pg_dump` every night at **2:00 AM IST** and keeps **14 days** of `.dump` files.
- To check a backup, restore it into a **separate** database such as `servicedesk_check`, never into the live `servicedesk`:
  ```bash
  pg_restore -d servicedesk_check --no-owner sd_YYYY-MM-DD.dump
  ```

---

## Documentation

| Document | Contents |
|---|---|
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Modules, ER diagram, design decisions |
| [PERMISSIONS](docs/PERMISSIONS.md) | Role-permission matrix |
| [TASKS](docs/TASKS.md) | Task management rules: roles, emails, files, export, privacy |
| [API](docs/API.md) | Endpoints and error format (`openapi.json` included) |
| [DEPLOYMENT](docs/DEPLOYMENT.md) | Setup, hosting, backup and restore, troubleshooting |
| [SECURITY](docs/SECURITY.md) | Security checklist |
| [ROADMAP](docs/ROADMAP.md) | Known limitations and planned work |

The interactive API docs are at `/api/docs` when running locally.

---

## Support

For access or password problems, contact the **ERP-IT team** or the **IT team**. Their names and numbers are on the sign-in page under *Forgot password*.

---

## Licence

**Proprietary. © 2026 Harshal Khadatare. All rights reserved.**

This software is confidential. Copying, modifying, redistributing or re-uploading it, in whole or in part, without written permission is not allowed. See [LICENSE](LICENSE).

<div align="center"><sub>© 2026 Service Desk · Vision Infra Equipment Solutions Ltd.</sub></div>
