import os
import tempfile
from pathlib import Path

import pytest

# Settings are read at import time, so the environment must be set first.
# ENV_FILE="" stops pydantic-settings reading the developer's own .env: the
# suite must assert the same thing on a laptop holding live API keys as it
# does in CI, where no .env exists.
os.environ["ENV_FILE"] = ""
_tmpdir = tempfile.mkdtemp(prefix="hd-tests-")
os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{_tmpdir}/test.db"
os.environ["TIMEZONE"] = "Europe/London"
os.environ["API_TOKEN"] = "test-token"
os.environ["ENVIRONMENT"] = "test"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def session():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth():
    return {"Authorization": "Bearer test-token"}
