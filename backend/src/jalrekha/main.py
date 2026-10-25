from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from jalrekha.api.routers import agent, node, alerts, cap, demo_inject, runtime, sites, sync, volunteer
from jalrekha.db.database import init_db
from jalrekha.services.storage import get_fixture_dir, get_upload_dir


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    get_upload_dir()
    get_fixture_dir().mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="NadiSaathi API (JalRekha engine)", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cloud profile: every write that is not a public submission needs the operator PIN.
# Public: volunteer reports, relief requests/photo checks, the red-team sandbox, scenario
# replays and the CAP preview. Camera uploads carry their own key; approvals check the PIN in-route.
_PUBLIC_WRITES = re.compile(
    r"^/(api/)?(reports|relief/requests|relief/photo-check|agent/red-team|agent/cycle|scenarios/[^/]+/run|cap/emit"
    r"|approvals/\d+/decision|relief/requests/\d+/decision)$"
)


@app.middleware("http")
async def _protect_writes(request, call_next):
    if os.environ.get("JALREKHA_PROTECT_WRITES") == "1" and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if not _PUBLIC_WRITES.match(request.url.path):
            from fastapi.responses import JSONResponse

            from jalrekha.agent import dispatch

            fwd = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
            client = fwd[-1] if fwd else (request.client.host if request.client else "unknown")
            if dispatch.locked_out(client):
                return JSONResponse({"detail": "too many wrong PINs; try again in 10 minutes"}, status_code=429)
            if not dispatch.check_pin(request.headers.get("x-operator-pin"), client):
                return JSONResponse({"detail": "operator PIN required for this action (X-Operator-Pin)"}, status_code=401)
    return await call_next(request)


get_fixture_dir().mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(get_upload_dir())), name="uploads")
app.mount("/fixtures", StaticFiles(directory=str(get_fixture_dir())), name="fixtures")

for router in (
    runtime.router,
    sites.router,
    node.router,
    volunteer.router,
    alerts.router,
    sync.router,
    cap.router,
    agent.router,
):
    app.include_router(router, prefix="/api")

app.include_router(cap.router)

if demo_inject.demo_inject_enabled():
    app.include_router(demo_inject.router, prefix="/api")

# Built PWA served from the same origin in the cloud deployment (no CORS, one URL).
_web_dist = os.environ.get("JALREKHA_WEB_DIST")
if _web_dist and Path(_web_dist, "index.html").is_file():
    from fastapi.responses import FileResponse

    app.mount("/assets", StaticFiles(directory=str(Path(_web_dist, "assets"))), name="web-assets")

    @app.get("/{path:path}", include_in_schema=False)
    def _spa(path: str):
        if path.startswith(("api/", "uploads/", "fixtures/")):
            from fastapi import HTTPException

            raise HTTPException(status_code=404)
        # Hashed files under /assets may be cached; the page, service worker and manifest must be
        # revalidated so a new deploy reaches browsers that already installed the PWA.
        revalidate = {"Cache-Control": "no-cache"}
        candidate = Path(_web_dist, path)
        if path and candidate.is_file() and Path(_web_dist).resolve() in candidate.resolve().parents:
            return FileResponse(candidate, headers=revalidate)
        return FileResponse(Path(_web_dist, "index.html"), headers=revalidate)


# Backward-compatible aliases for older tests/scripts that import from main.py.
is_online = True

