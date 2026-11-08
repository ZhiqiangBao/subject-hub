from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import FileResponse, JSONResponse

from .api.auth import router as auth_router
from .api.parent import router as parent_router
from .api.papers import router as papers_router
from .api.student import router as student_router
from .api.uploads import router as uploads_router
from .config import ADMIN_HOST, ADMIN_PORT, COOKIE_NAME, FRONTEND_DIST, HOST, PORT, ensure_dirs, secret_key
from .db import Base, SessionLocal, engine, migrate
from .services.bank import BankError, bank
from .services.llm import start_worker
from .services.snapshots import backfill_legacy_papers

def initialize() -> None:
    ensure_dirs()
    Base.metadata.create_all(bind=engine)
    migrate()
    bank.reload()
    with SessionLocal() as db:
        backfill_legacy_papers(db)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize()
    start_worker()
    admin_server = None
    admin_task = None
    if ADMIN_PORT and ADMIN_PORT != PORT:
        import uvicorn

        config = uvicorn.Config(
            _app,
            host=ADMIN_HOST,
            port=ADMIN_PORT,
            log_level="info",
            lifespan="off",
        )
        admin_server = uvicorn.Server(config)
        admin_task = asyncio.create_task(admin_server.serve())
    yield
    if admin_server is not None:
        admin_server.should_exit = True
    if admin_task is not None:
        await admin_task


app = FastAPI(title="学科 Hub", lifespan=lifespan)


@app.exception_handler(BankError)
async def invalid_bank_input(_request: Request, exc: BankError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:8091",
        "http://127.0.0.1:8091",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    SessionMiddleware,
    secret_key=secret_key(),
    session_cookie=COOKIE_NAME,
    same_site="lax",
    https_only=False,
    max_age=60 * 60 * 24 * 14,
)
app.include_router(auth_router)
app.include_router(student_router)
app.include_router(papers_router)
app.include_router(parent_router)
app.include_router(uploads_router)


@app.middleware("http")
async def api_method_guard(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/") and response.status_code == 405:
        return JSONResponse({"detail": "找不到这个接口，重启答题服务后再试"}, status_code=404)
    return response


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "items": len(bank.items)}


if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa(request: Request, full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "找不到这个接口，重启答题服务后再试"}, status_code=404)
        # Vite emits index.html and /assets only. Never interpret a client
        # route as an operating-system file name (including Windows paths).
        index = FRONTEND_DIST / "index.html"
        if any(part == ".." for part in full_path.replace("\\", "/").split("/")):
            return JSONResponse({"detail": "找不到这个文件"}, status_code=404)
        if index.is_file() and index.resolve().parent == FRONTEND_DIST.resolve():
            return FileResponse(index)
        return JSONResponse({"detail": "网页还没构建"}, status_code=404)


def run() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=HOST, port=PORT, app_dir=str(Path(__file__).resolve().parents[1]))
