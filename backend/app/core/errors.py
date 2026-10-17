"""Centralised error types and the standard error envelope:

{"error": {"code": "...", "message": "...", "details": [...], "request_id": "..."}}
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("servicedesk.errors")


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, details: list | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []
        if code:
            self.code = code


class NotFound(AppError):
    status_code, code = 404, "not_found"


class Forbidden(AppError):
    status_code, code = 403, "forbidden"


class Unauthorized(AppError):
    status_code, code = 401, "unauthorized"


class Conflict(AppError):
    status_code, code = 409, "conflict"


class BusinessRuleError(AppError):
    status_code, code = 422, "business_rule"


class TooManyRequests(AppError):
    status_code, code = 429, "rate_limited"


def _envelope(request: Request, status: int, code: str, message: str, details=None, headers=None):
    rid = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details or [], "request_id": rid}},
        headers=headers,
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return _envelope(request, exc.status_code, exc.code, exc.message, exc.details, headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(p) for p in e.get("loc", []) if p != "body"), "message": e.get("msg", "")}
            for e in exc.errors()
        ]
        return _envelope(request, 422, "validation_error", "Some fields need attention.", details)

    @app.exception_handler(StaleDataError)
    async def _stale(request: Request, exc: StaleDataError):
        return _envelope(request, 409, "conflict",
                         "This record was changed by someone else. Reload and try again.")

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized", 403: "forbidden"}.get(
            exc.status_code, "http_error")
        msg = exc.detail if isinstance(exc.detail, str) else "Request failed."
        details = [{"path": request.url.path}] if exc.status_code == 404 else []
        return _envelope(request, exc.status_code, code, msg, details)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # Full detail goes to server logs only; clients never see stack traces.
        log.exception("Unhandled error request_id=%s", getattr(request.state, "request_id", None))
        return _envelope(request, 500, "internal_error", "An unexpected error occurred.")
