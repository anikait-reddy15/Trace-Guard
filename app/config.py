from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    project_name: str = "TraceGuard QA Engine"
    version: str = "1.0.0"
    
    # SQLite connection for the relational document tree
    sqlite_url: str = "sqlite+aiosqlite:///./traceguard.db"
    
    # MongoDB connection for LLM-generated test cases
    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_db_name: str = "traceguard_generations"
    
    # LLM Provider Key (Google or OpenAI)
    llm_api_key: Optional[str] = None
    
    class Config:
        env_file = ".env"

settings = Settings()