"""HTTP tracing without request bodies, query strings, headers or raw paths."""


class RequestTelemetryMiddleware:
    def __init__(self, app, telemetry) -> None:
        self.app = app
        self.telemetry = telemetry

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        status = 500

        async def tracked_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        with self.telemetry.span("http.request", {"http.method": scope["method"]}):
            try:
                await self.app(scope, receive, tracked_send)
            finally:
                self.telemetry.record_event(
                    "http.response",
                    {
                        "http.status_code": status,
                        "http.route": getattr(scope.get("route"), "path", "unmatched"),
                    },
                )
