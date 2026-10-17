"""Bound the request body before multipart parsing can spool an oversized upload."""

import uuid

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse


class RequestBodyTooLarge(HTTPException):
    def __init__(self):
        super().__init__(413, "Request body exceeds the configured size limit.")


class BodyLimitMiddleware:
    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        consumed = 0
        response_started = False

        async def bounded_receive():
            nonlocal consumed
            message = await receive()
            consumed += len(message.get("body", b""))
            if consumed > self.max_bytes:
                raise RequestBodyTooLarge
            return message

        async def tracked_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, bounded_receive, tracked_send)
        except RequestBodyTooLarge:
            if response_started:
                raise
            await JSONResponse(
                status_code=413,
                content={
                    "error_id": f"err_{uuid.uuid4().hex[:10]}",
                    "code": "upload_too_large",
                    "message": "Request body exceeds the configured size limit.",
                },
            )(scope, receive, send)
