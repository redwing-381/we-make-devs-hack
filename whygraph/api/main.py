"""Why-Graph API. Every router is wired here up front so feature PRs only touch their own route file."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from whygraph.api.routes import brain, guard, health, incidents, ingest, query, replay
from whygraph.integrations.mcp_server import mcp

mcp_app = mcp.http_app(path="/")  # streamable HTTP; clients connect to http(s)://<host>/mcp/
app = FastAPI(title="Why-Graph", version="0.1.0", lifespan=mcp_app.lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (
    health.router,
    ingest.router,
    incidents.router,
    query.router,
    replay.router,
    guard.router,
    brain.router,
):
    app.include_router(r, prefix="/api")

app.mount("/mcp", mcp_app)  # bearer WHYGRAPH_API_TOKEN; tools in whygraph/integrations/mcp_server.py
