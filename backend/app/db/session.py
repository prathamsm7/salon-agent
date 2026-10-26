"""PostgreSQL engine and session factory."""

import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger("uvicorn.error")

BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")

def _sqlalchemy_url(url: str) -> str:
    """Accept the postgres URLs hosts provide and use the psycopg driver."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql+"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


DATABASE_URL = _sqlalchemy_url(os.environ.get("DATABASE_URL", ""))
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required")

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={
        "prepare_threshold": None,
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    },
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables and seed. A dropped hosted connection is retried."""
    last_error: OperationalError | None = None
    for attempt in range(3):
        try:
            _init_db_once()
            return
        except OperationalError as exc:
            last_error = exc
            engine.dispose()
            logger.warning(
                "Database connection dropped during startup (attempt %s of 3). Retrying.",
                attempt + 1,
            )
            time.sleep(1.5 * (attempt + 1))
    assert last_error is not None
    raise last_error


def _init_db_once() -> None:
    from sqlalchemy import text

    from app.db.models import Base
    from app.db.seed import seed

    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'bookings' AND column_name = 'code'
                    ) THEN
                        ALTER TABLE bookings ALTER COLUMN code TYPE VARCHAR(80);
                    END IF;
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'users' AND column_name = 'phone'
                    ) THEN
                        ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(254);
                        ALTER TABLE users ALTER COLUMN phone DROP NOT NULL;
                        CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email ON users (email);
                    END IF;
                    IF EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'otp_codes' AND column_name = 'phone'
                    ) THEN
                        ALTER TABLE otp_codes ADD COLUMN IF NOT EXISTS email VARCHAR(254);
                        ALTER TABLE otp_codes ALTER COLUMN phone DROP NOT NULL;
                        CREATE UNIQUE INDEX IF NOT EXISTS uq_otp_codes_email ON otp_codes (email);
                    END IF;
                    IF EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = 'bookings'
                    ) THEN
                        ALTER TABLE bookings ADD COLUMN IF NOT EXISTS google_event_id VARCHAR(256);
                        ALTER TABLE bookings ADD COLUMN IF NOT EXISTS google_calendar_id VARCHAR(256);
                    END IF;
                END $$;
                """
            )
        )
    with SessionLocal() as db:
        seed(db)
