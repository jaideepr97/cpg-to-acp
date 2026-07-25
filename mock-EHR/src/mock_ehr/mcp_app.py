"""Standalone MCP server for mock-EHR — serves FHIR patient data tools over Streamable HTTP.

The tools proxy to the HAPI FHIR server via REST. Deployed as its own pod
behind the MCP Gateway for governed tool access.
"""

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from mock_ehr.mcp_server import mcp


class AcceptHeaderMiddleware:
    """Ensure MCP requests include text/event-stream in the Accept header.

    The MCP Gateway (Kuadrant v0.6.0) sends Accept: application/json without
    text/event-stream, but the MCP SDK's Streamable HTTP transport requires both.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            accept = headers.get(b"accept", b"").decode()
            if "text/event-stream" not in accept:
                new_accept = f"{accept}, text/event-stream" if accept else "application/json, text/event-stream"
                scope["headers"] = [
                    (k, v) for k, v in scope["headers"] if k != b"accept"
                ] + [(b"accept", new_accept.encode())]
        await self.app(scope, receive, send)


_mcp_app = mcp.streamable_http_app()


async def health(request):
    return JSONResponse({"status": "UP", "service": "mock-ehr-mcp"})


app = Starlette(
    routes=[Route("/health", health)],
    lifespan=_mcp_app.router.lifespan_context,
    middleware=[Middleware(AcceptHeaderMiddleware)],
)
app.mount("/", _mcp_app)
