from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings
from app.models.sql_models import Base

# --- SQLite Configuration (Relational Tree) ---
engine = create_async_engine(
    settings.sqlite_url,
    connect_args={"check_same_thread": False},
    echo=False
)

AsyncSessionLocal = async_sessionmaker(
    engine, 
    expire_on_commit=False, 
    class_=AsyncSession
)

async def get_db():
    """Dependency injection for FastAPI endpoints."""
    async with AsyncSessionLocal() as session:
        yield session

async def init_sqlite_db():
    """Creates all relational tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

# --- MongoDB Configuration (Document Store for LLM Outputs) ---
mongo_client = AsyncIOMotorClient(settings.mongodb_url)
mongo_db = mongo_client[settings.mongodb_db_name]
mongo_collection = mongo_db["qa_test_cases"]

def get_mongo_collection():
    """Dependency injection for MongoDB collection."""
    return mongo_collection