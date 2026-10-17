"""Why-Graph API. Every router is wired here up front so feature PRs only touch their own route file."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from whygraph.api.routes import brain, health, incidents, ingest, query, replay

app = FastAPI(title="Why-Graph", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (health.router, ingest.router, incidents.router, query.router, replay.router, brain.router):
    app.include_router(r, prefix="/api")

# F-B5 (feat/mcp): mount the FastMCP app here, e.g.
#   from whygraph.integrations.mcp_server import mcp
#   app.mount("/mcp", mcp.http_app())   # remember to wire its lifespan into FastAPI
