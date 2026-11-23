"""FastAPI application factory."""

from __future__ import annotations

import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.deps import Services
from app.api.routes import audit, auth, chat, documents, search, tickets
from app.api.schemas import HealthOut
from app.core.config import Settings, get_settings
from app.core.ratelimit import build_limiter
from app.db.session import Database
from app.rag.embeddings import build_embedder
from app.rag.llm import build_generator
from app.rag.pipeline import RagPipeline

STATIC_DIR = Path(__file__).parent / "static"
API_PREFIX = "/api/v1"
_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
access_log = logging.getLogger("app.access")


def build_services(settings: Settings) -> Services:
    db = Database(settings.database_url)
    embedder = build_embedder(settings)
    pipeline = RagPipeline(db, embedder, build_generator(settings), settings)
    return Services(
        settings=settings,
        db=db,
        embedder=embedder,
        pipeline=pipeline,
        limiter=build_limiter(settings),
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        services = build_services(settings)
        app.state.services = services
        await services.db.create_schema()
        if settings.seed_demo:
            from app.demo import seed_demo

            await seed_demo(services)
        yield
        await services.db.dispose()

    app = FastAPI(
        title="RAG Support Agent",
        version=__version__,
        description="Multi-tenant RAG support agent with database-enforced tenant isolation.",
        lifespan=lifespan,
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
            expose_headers=["X-Request-ID", "X-Total-Count", "Retry-After"],
        )

    @app.middleware("http")
    async def request_id_and_access_log(request: Request, call_next):
        """Tag every request with an ID (reused from the caller when well-formed) and log it."""
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if _REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        if request.url.path.startswith(API_PREFIX):
            access_log.info(
                "%s %s %s %.1fms request_id=%s",
                request.method,
                request.url.path,
                response.status_code,
                (time.perf_counter() - started) * 1000,
                request_id,
            )
        return response

    for module in (auth, documents, chat, search, tickets, audit):
        app.include_router(module.router, prefix=API_PREFIX)

    @app.get(f"{API_PREFIX}/health", tags=["system"])
    async def health() -> HealthOut:
        services: Services = app.state.services
        return HealthOut(
            status="ok",
            version=__version__,
            database=services.db.engine.dialect.name,
            row_level_security=services.db.rls,
            embedding_provider=settings.embedding_provider,
            llm_provider=settings.llm_provider,
        )

    @app.get(f"{API_PREFIX}/config", tags=["system"], include_in_schema=False)
    async def public_config() -> dict:
        """Non-secret flags the bundled web UI needs."""
        return {"demo": settings.seed_demo, "signup": settings.allow_public_signup}

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
