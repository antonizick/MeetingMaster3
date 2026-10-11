"""Security middleware: security headers and double-submit CSRF protection (SPEC §15.3 S2)."""

from __future__ import annotations

import hmac
import secrets
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

CSRF_COOKIE = "mm3_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

CSP = (
    "default-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; "
    "object-src 'none'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        return response


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit token: ``mm3_csrf`` cookie (SameSite=Strict) must equal the
    ``X-CSRF-Token`` header on state-changing requests, and any ``Origin`` must be trusted.
    """

    def __init__(self, app: object, trusted_hosts: list[str]) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.trusted_hosts = {h.lower() for h in trusted_hosts}

    def _origin_ok(self, request: Request) -> bool:
        origin = request.headers.get("origin")
        if origin is None:
            return True  # non-browser client; the token check still applies
        host = (urlsplit(origin).hostname or "").lower()
        return host in self.trusted_hosts

    @staticmethod
    def _reject(reason: str) -> Response:
        return JSONResponse(
            {"code": "csrf_failed", "message": reason, "hint": "Reload the page and retry."},
            status_code=403,
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        cookie = request.cookies.get(CSRF_COOKIE)
        token = cookie or secrets.token_urlsafe(32)
        request.state.csrf_token = token

        if request.method not in SAFE_METHODS:
            if not self._origin_ok(request):
                return self._reject("Untrusted Origin.")
            supplied = request.headers.get(CSRF_HEADER, "")
            if not cookie or not hmac.compare_digest(cookie, supplied):
                return self._reject("Missing or invalid CSRF token.")

        response = await call_next(request)
        if not cookie:
            response.set_cookie(
                CSRF_COOKIE, token, samesite="strict", httponly=False, secure=False, path="/"
            )
        return response
