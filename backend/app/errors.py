"""One place for turning failures into clear, safe responses.

Every error a browser can receive has the same shape:

    {"detail": "A sentence a person can act on."}
    {"detail": {"message": "…", "errors": [{"field": "title", "message": "…"}]}}   (form problems)

Nothing here ever includes request bodies (student text), SQL, or stack traces in
the response. Unexpected errors are logged with a short reference that is also
shown to the user, so support can find the log line.
"""
import logging
import secrets

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError

from .exports import ExportUnavailable

log = logging.getLogger("aicss")

# Pydantic error type -> plain-language message. {ctx} values are filled in when present.
_PLAIN = {
    "missing": "This is required.",
    "string_too_long": "Too long: use at most {max_length} characters.",
    "string_too_short": "Too short: use at least {min_length} characters.",
    "int_parsing": "Enter a whole number.",
    "int_type": "Enter a whole number.",
    "float_parsing": "Enter a number.",
    "bool_parsing": "Choose yes or no.",
    "greater_than_equal": "Must be {ge} or more.",
    "less_than_equal": "Must be {le} or less.",
    "datetime_parsing": "Enter a valid date.",
    "datetime_from_date_parsing": "Enter a valid date.",
    "json_invalid": "The request wasn't valid JSON.",
    "dict_type": "This has the wrong format.",
    "list_type": "This has the wrong format.",
    "string_type": "Enter text here.",
}


def _plain(err: dict) -> str:
    template = _PLAIN.get(err.get("type", ""))
    if template:
        try:
            return template.format(**(err.get("ctx") or {}))
        except (KeyError, IndexError, ValueError):
            pass
    return str(err.get("msg") or "This value isn't valid.")


def reference() -> str:
    return secrets.token_hex(4)


def register(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        errors = []
        for e in exc.errors():
            loc = [str(x) for x in (e.get("loc") or []) if x not in ("body", "query", "path", "header")]
            errors.append({"field": ".".join(loc), "message": _plain(e)})
        first = errors[0] if errors else None
        message = "Some of what was sent isn't valid."
        if first and len(errors) == 1:
            message = f"{first['field'].replace('_', ' ').capitalize()}: {first['message']}" if first["field"] \
                else first["message"]
        return JSONResponse({"detail": {"message": message, "errors": errors}}, status_code=422)

    @app.exception_handler(IntegrityError)
    async def conflict(request: Request, exc: IntegrityError):
        # Two people did the same thing at once, or something was deleted underneath us.
        log.warning("Integrity error on %s %s: %s", request.method, request.url.path, type(exc.orig).__name__)
        return JSONResponse({"detail": "That couldn't be saved because it conflicts with something that already "
                                       "exists or was just changed. Reload the page and try again."}, status_code=409)

    @app.exception_handler(OperationalError)
    async def database_busy(request: Request, exc: OperationalError):
        ref = reference()
        log.error("Database unavailable on %s %s [ref %s]: %s", request.method, request.url.path, ref,
                  type(exc.orig).__name__)
        return JSONResponse({"detail": "The database is busy or unreachable right now. Nothing was lost. "
                                       f"Try again in a moment. (Reference {ref})"}, status_code=503,
                            headers={"Retry-After": "5"})

    @app.exception_handler(DBAPIError)
    async def database_error(request: Request, exc: DBAPIError):
        ref = reference()
        log.error("Database error on %s %s [ref %s]: %s", request.method, request.url.path, ref,
                  type(exc.orig).__name__)
        return JSONResponse({"detail": "The server couldn't complete that because of a database problem. "
                                       f"Try again, and contact support if it keeps happening. (Reference {ref})"},
                            status_code=500)

    @app.exception_handler(ExportUnavailable)
    async def no_export(request: Request, exc: ExportUnavailable):
        return JSONResponse({"detail": str(exc)}, status_code=501)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        # NFR-5.4.11: log enough to diagnose, but never request bodies (student text).
        ref = reference()
        log.exception("Unhandled error on %s %s [ref %s]", request.method, request.url.path, ref)
        return JSONResponse({"detail": "Something went wrong on the server. Your saved work is safe. "
                                       f"Try again, and contact support if it keeps happening. (Reference {ref})"},
                            status_code=500)
