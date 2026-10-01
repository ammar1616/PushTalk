"""Test setup.

Three decisions worth knowing about:

1. Tests run against the compose Postgres, but in their own database
   (`pushtalk_test`), not the dev one. Same server, so no extra moving part,
   but a failing test cannot eat the data used by hand.

2. `DATABASE_URL` is set before anything from `app` is imported. Settings are
   built at import time and alembic's env.py reads them, so setting it in a
   fixture would be too late and the tests would quietly run against the dev
   database. conftest is imported before test modules, which is what makes
   the override reliable.

3. The schema comes from running the real migrations, not from
   `Base.metadata.create_all`. create_all would build whatever the models say
   today, which is not necessarily what the migrations actually produced, and
   then the tests would be validating a schema nothing else uses.
"""

import os
import shutil
import subprocess
import uuid
from pathlib import Path

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://pushtalk:pushtalk@db:5432/pushtalk_test",
)
os.environ["JWT_SECRET"] = "test-secret-not-used-anywhere-else"
# Its own media root, so tests never write into the volume the dev containers
# are using.
os.environ["MEDIA_ROOT"] = os.environ.get("TEST_MEDIA_ROOT", "/tmp/pushtalk-test-media")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.security import create_access_token  # noqa: E402
from app.db.session import SessionLocal, engine, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services import audio_service, auth_service, channel_service  # noqa: E402

# TRUNCATE in dependency order. Restoring identity keeps id sequences at 1 so a
# failure does not change what a later run sees.
TRUNCATE = (
    "TRUNCATE message_statuses, messages, memberships, channels, users "
    "RESTART IDENTITY CASCADE"
)


def _ensure_test_database() -> None:
    """Create `pushtalk_test` if it is not there yet.

    A reviewer starting from a clean checkout runs `docker compose up` and then
    `pytest`, and the compose file only creates the dev database. Making the
    suite create its own database keeps that path working without a manual
    step, and keeps the hand-created database from being a hidden requirement.

    Connects to the default `postgres` database to issue CREATE DATABASE, which
    cannot be run from inside the target database itself.
    """
    import asyncio

    import asyncpg
    from sqlalchemy.engine import make_url

    url = make_url(os.environ["DATABASE_URL"])
    target = url.database

    async def create_if_missing() -> None:
        conn = await asyncpg.connect(
            host=url.host,
            port=url.port or 5432,
            user=url.username,
            password=url.password,
            database="postgres",
        )
        try:
            exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", target
            )
            if not exists:
                # The name comes from our own DATABASE_URL, not user input.
                await conn.execute(f'CREATE DATABASE "{target}"')
        finally:
            await conn.close()

    asyncio.run(create_if_missing())


def pytest_configure(config: pytest.Config) -> None:
    """Create the media root and bring the test schema up to head, once."""
    Path(os.environ["MEDIA_ROOT"]).mkdir(parents=True, exist_ok=True)
    _ensure_test_database()
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")


@pytest_asyncio.fixture(autouse=True)
async def clean_db():
    """Empty every table, and the media directory, before each test.

    Uploads write into a media root shared by the whole session, so without
    clearing it a test that asserts "no file was left behind" sees the files
    an earlier test deliberately created and fails for the wrong reason.

    This also doubles as the reachability check: if the database were down,
    the TRUNCATE would be where every test reported it, with a real
    connection error instead of a confusing fixture error.
    """
    async with engine.begin() as conn:
        await conn.execute(text(TRUNCATE))
    root = Path(os.environ["MEDIA_ROOT"])
    for sub in (audio_service.ORIGINAL_DIR, audio_service.NORMALIZED_DIR):
        shutil.rmtree(root / sub, ignore_errors=True)
        (root / sub).mkdir(parents=True, exist_ok=True)
    yield
    # pytest-asyncio gives every test a fresh event loop, but `engine` is a
    # module-level singleton whose pooled connections belong to the loop that
    # opened them. Without disposing, the next test gets a connection attached
    # to a closed loop and fails with "attached to a different loop".
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session():
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session):
    """An HTTP client wired to the test database.

    get_db is replaced so the route and the test share one session. That means
    a test can read rows the route just wrote without a second connection
    blocking on an uncommitted transaction.
    """

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def user_factory(db_session):
    async def make(username: str | None = None, password: str = "supersecret123"):
        name = username or f"user{uuid.uuid4().hex[:8]}"
        user = await auth_service.create_user(db_session, name, password)
        await db_session.commit()
        return user

    return make


@pytest_asyncio.fixture
async def channel_factory(db_session):
    async def make(owner):
        channel = await channel_service.create_channel(db_session, "general", owner.id)
        await db_session.commit()
        return channel

    return make


@pytest.fixture
def auth_headers():
    def make(user) -> dict:
        return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}

    return make


@pytest.fixture
def owner_setup(user_factory, channel_factory):
    """The common case: one signed-in user who created their channel."""

    async def make(username: str = "owner"):
        user = await user_factory(username=username)
        channel = await channel_factory(user)
        return user, channel

    return make


def _clip(directory: Path, seconds: float, name: str) -> Path:
    """Encode a tone to ogg/opus with the settings the worker normalizes to."""
    path = directory / name
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-ac", "1", "-ar", "48000", "-c:a", "libopus",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    return path


@pytest.fixture(scope="session")
def valid_audio(tmp_path_factory) -> Path:
    """A real clip between the min and max duration."""
    return _clip(tmp_path_factory.mktemp("audio"), 1.0, "valid.ogg")


@pytest.fixture(scope="session")
def short_audio(tmp_path_factory) -> Path:
    """Under settings.min_audio_seconds."""
    return _clip(tmp_path_factory.mktemp("audio"), 0.2, "short.ogg")


@pytest.fixture(scope="session")
def long_audio(tmp_path_factory) -> Path:
    """Over settings.max_audio_seconds."""
    return _clip(tmp_path_factory.mktemp("audio"), 61.0, "long.ogg")


@pytest.fixture(scope="session")
def text_file(tmp_path_factory) -> Path:
    """Valid-looking bytes that are not audio at all."""
    path = tmp_path_factory.mktemp("audio") / "notes.txt"
    path.write_bytes(b"RIFFnope" + b"not audio at all" * 500)
    return path