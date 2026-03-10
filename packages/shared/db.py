import logging
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

from packages.shared.config import settings

logger = logging.getLogger(__name__)

# Ensure data directory and db file exist conceptually
db_path = Path(settings.data_dir) / "chat.db"
db_path.parent.mkdir(parents=True, exist_ok=True)

# Create an async SQLAlchemy engine
DATABASE_URL = f"sqlite+aiosqlite:///{db_path}"

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False}
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False
)

Base = declarative_base()

async def init_db() -> None:
    """Create all tables if they don't exist."""
    from packages.memory.models import ChatThread, ChatMessage  # register models

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info(f"Database initialized at {db_path}")

async def get_db_session():
    """Dependency provider for database sessions."""
    async with AsyncSessionLocal() as session:
        yield session

