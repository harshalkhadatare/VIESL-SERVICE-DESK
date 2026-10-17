import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.v1 import auth, dashboard, meta, platform, tickets
from app.core.config import get_settings
from app.core.database import engine
from app.core.errors import register_error_handlers
from app.core.rate_limit import api_limiter

settings = get_settings()
logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("servicedesk")


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = asyncio.Event()
    task = None
    if settings.enable_scheduler and settings.app_env != "testing":
        from app.services.scheduler import scheduler_loop
        task = asyncio.create_task(scheduler_loop(stop))
    yield
    stop.set()
    if task:
        await task


class StripFunctionPrefix:
    """On Vercel, requests can arrive with the serverless function path (/api/index...)
    instead of the URL the visitor opened. Normalise it so normal routing works."""

    PREFIXES = ("/api/index.py", "/api/index")

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            # vercel.json forwards the visitor's original path as ?__path=...
            qs = scope.get("query_string", b"").decode("latin-1")
            if "__path=" in qs:
                from urllib.parse import parse_qsl, quote, urlencode
                pairs = parse_qsl(qs, keep_blank_values=True)
                orig = next((v for k, v in pairs if k == "__path"), "/") or "/"
                if not orig.startswith("/"):
                    orig = "/" + orig
                rest = urlencode([(k, v) for k, v in pairs if k != "__path"])
                scope = dict(scope, path=orig, raw_path=quote(orig).encode(),
                             query_string=rest.encode("latin-1"))
                await self.app(scope, receive, send)
                return
            path = scope.get("path", "")
            for pre in self.PREFIXES:
                if path == pre or path.startswith(pre + "/"):
                    path = path[len(pre):] or "/"
                    scope = dict(scope, path=path, raw_path=path.encode())
                    break
        await self.app(scope, receive, send)


app = FastAPI(
    title="Vision Infra IT Service Desk API", version="1.0.0", lifespan=lifespan,
    docs_url=None if settings.is_production else "/api/docs",
    redoc_url=None if settings.is_production else "/api/redoc",
    openapi_url=None if settings.is_production else "/api/openapi.json",
)
register_error_handlers(app)
app.add_middleware(StripFunctionPrefix)

app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Requested-With"],
)

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = request.headers.get("X-Request-ID")
    request.state.request_id = rid if rid and len(rid) <= 36 else str(uuid.uuid4())
    if request.url.path.startswith("/api/"):
        key = f"api:{request.client.host if request.client else 'x'}"
        if not api_limiter.allow(key, 600, 60):
            return JSONResponse(status_code=429, content={"error": {
                "code": "rate_limited", "message": "Too many requests.", "details": [],
                "request_id": request.state.request_id}})
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = CSP
    if settings.cookie_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


api = APIRouter(prefix="/api/v1")
for r in (auth.router, tickets.router, meta.router, dashboard.router, platform.router):
    api.include_router(r)


@api.get("/health", tags=["Health"])
def health():
    with engine.connect() as c:
        c.execute(text("SELECT 1"))
    return {"status": "ok", "env": settings.app_env}


app.include_router(api)

# Serve the static frontend (same origin => no CORS needed, strict CSP works)
frontend = (Path(__file__).resolve().parent.parent / settings.frontend_dir).resolve()
if settings.serve_frontend and frontend.exists():
    app.mount("/static", StaticFiles(directory=frontend), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(frontend / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/index.html", include_in_schema=False)
    def index_html():
        return FileResponse(frontend / "index.html", headers={"Cache-Control": "no-cache"})
elif settings.serve_frontend:
    log.warning("Frontend folder not found at %s — only the API is served", frontend)

    @app.get("/", include_in_schema=False)
    def frontend_missing():
        return JSONResponse(status_code=404, content={"error": {
            "code": "frontend_missing", "details": [], "request_id": None,
            "message": f"Frontend files not found at {frontend}. Deploy the whole project folder "
                       "(backend + frontend) or set FRONTEND_DIR."}})

