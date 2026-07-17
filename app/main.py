from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.database import init_sqlite_db
from app.config import settings
from app.api.endpoints import documents

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize the SQLite database tables
    print("Initializing TraceGuard Database...")
    await init_sqlite_db()
    print("Database Initialization Complete.")
    yield
    # Shutdown logic can be added here
    print("Shutting down TraceGuard...")

app = FastAPI(
    title=settings.project_name,
    version=settings.version,
    lifespan=lifespan
)

app.include_router(documents.router) 

# Global exception handler to prevent raw stack traces from leaking
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"message": "An internal server error occurred.", "details": str(exc)},
    )

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": settings.project_name}