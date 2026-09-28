import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.errors import AppError, error_response
from app.core.logging import setup_logging
from app.db.session import engine

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once on startup, once on shutdown. Closing the engine on the way out
    # is what lets Docker stop the container without hanging on open sockets.
    yield
    await engine.dispose()


app = FastAPI(title="PushTalk", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def handle_app_error(request, exc: AppError):
    return error_response(exc.code, exc.message, exc.status_code, exc.details)


@app.exception_handler(Exception)
async def handle_unexpected_error(request, exc: Exception):
    logging.getLogger().error("unhandled error", exc_info=exc)
    return error_response("INTERNAL_ERROR", "Something went wrong.", 500)


@app.middleware("http")
async def log_request(request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started) * 1000)
    logging.getLogger("http").info(
        "request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


@app.get("/health")
async def health():
    return {"status": "ok"}