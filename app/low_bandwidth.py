"""Conservative compression for H3 JSON API reads on very slow Tailscale relays.

Use Starlette's tested ASGI GZipMiddleware only for known JSON GET endpoints.
Applying it globally could buffer/compress FileResponse MP4 and JPEG downloads,
prevent range requests, and waste CPU: media routes are deliberately excluded.
"""
from __future__ import annotations

import re
from starlette.middleware.gzip import GZipMiddleware


_JSON_GET = frozenset({
    "/api/state",
    "/api/models",
    "/api/jobs/history",
    "/api/upscale/jobs",
    "/api/upscale/methods",
    "/api/interpolate/jobs",
    "/api/interpolate/status",
})
_JOB_DETAIL = re.compile(r"/api/jobs/[0-9a-f]{32}\Z")


class SelectiveJsonGZipMiddleware:
    """Wrap only named read-only JSON APIs; rely on Accept-Encoding negotiation."""

    def __init__(self, app):
        self.app = app
        self.compressed = GZipMiddleware(app, minimum_size=512, compresslevel=5)

    async def __call__(self, scope, receive, send):
        if (scope.get("type") == "http" and scope.get("method") in ("GET", "HEAD")
                and (scope.get("path") in _JSON_GET
                     or _JOB_DETAIL.fullmatch(scope.get("path", "")))):
            await self.compressed(scope, receive, send)
        else:
            await self.app(scope, receive, send)
