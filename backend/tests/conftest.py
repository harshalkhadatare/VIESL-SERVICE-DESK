import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="sdtest_")
os.environ.update({
    "APP_ENV": "testing",
    # Set TEST_DATABASE_URL to run the suite against PostgreSQL / SQL Server (use an empty database)
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db"),
    "UPLOAD_DIR": f"{_tmp}/uploads",
    "ENABLE_SCHEDULER": "false",
    "SECRET_KEY": "test-secret-key-0123456789abcdef0123456789",
    "SERVE_FRONTEND": "false",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal, engine  # noqa: E402
from app.core.rate_limit import api_limiter, login_limiter  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, Category, User  # noqa: E402
from app.seed import seed_demo, seed_reference  # noqa: E402

PASSWORD = "Vision@Demo2026"
EMAILS = {
    "employee": "anjali.sharma@demo.example.com",
    "employee2": "manoj.gupta@demo.example.com",
    "employee3": "meera.pillai@demo.example.com",
    "admin": "rohan.mehta@demo.example.com",          # Head of IT (Service Desk + Security teams)
    "erp_admin": "amit.deshmukh@demo.example.com",     # ERP team
    "erp_admin2": "priya.nair@demo.example.com",       # ERP team
    "infra_admin": "rahul.kulkarni@demo.example.com",  # Infrastructure + EUC teams
    "sd_admin": "sneha.iyer@demo.example.com",         # Service Desk + EUC teams
}


@pytest.fixture(scope="session", autouse=True)
def database():
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_reference(db)
        seed_demo(db, n_tickets=8)
    yield


@pytest.fixture(autouse=True)
def _reset_limits():
    login_limiter.reset()
    api_limiter.reset()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    with SessionLocal() as s:
        yield s


def user_id(email: str) -> int:
    with SessionLocal() as s:
        return s.scalar(select(User.id).where(User.email == email))


def auth(role: str) -> dict:
    token, _ = create_access_token(user_id(EMAILS[role]))
    return {"Authorization": f"Bearer {token}"}


def category_id(code: str) -> int:
    with SessionLocal() as s:
        return s.scalar(select(Category.id).where(Category.code == code))


def make_ticket(client, role="employee", code="ERP_APP", impact=2, urgency=2, subject=None, **extra) -> dict:
    body = {"subject": subject or f"Test ticket {code}", "description": "Detailed description for testing.",
            "category_id": category_id(code), "impact": impact, "urgency": urgency, **extra}
    r = client.post("/api/v1/tickets", json=body, headers=auth(role))
    assert r.status_code == 201, r.text
    return r.json()
