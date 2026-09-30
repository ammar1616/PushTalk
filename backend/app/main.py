import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.errors import AppError, error_response
from app.core.logging import setup_logging
from app.core.queue import get_redis
from app.db.session import engine
from app.api import auth, channels, messages, ws
from app.realtime.manager import listen

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One Redis listener for the whole process, started here and cancelled on
    # shutdown. Without it the API would never see events published by the
    # worker. Closing the engine on the way out is what lets Docker stop the
    # container without hanging on open sockets.
    redis = await get_redis()
    task = asyncio.create_task(listen(redis))
    try:
        yield
    finally:
        task.cancel()
        await engine.dispose()


app = FastAPI(title="PushTalk", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(channels.router)
app.include_router(messages.router)
app.include_router(ws.router)

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


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request, exc: RequestValidationError):
    # Pydantic's own 422 uses {"detail": [...]}. Rewrapping it here means the
    # frontend has exactly one error shape to parse, as the spec requires.
    return error_response(
        "VALIDATION_ERROR",
        "That request was not valid.",
        422,
        {"fields": exc.errors()},
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request, exc: Exception):
    logging.getLogger().error("unhandled error", exc_info=exc)
    return error_response("INTERNAL_ERROR", "Something went wrong.", 500)


@app.middleware("http")
async def log_request(request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started) * 1000)

    fields = {
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "duration_ms": duration_ms,
    }
    # get_current_user stashes the id here, so signed-in requests get it in
    # the log line without the route having to pass it down.
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        fields["user_id"] = user_id

    logging.getLogger("http").info("request", extra=fields)
    return response


@app.get("/health")
async def health():
    return {"status": "ok"}