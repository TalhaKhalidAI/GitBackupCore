from contextlib import asynccontextmanager
import os
from fastapi import FastAPI, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from App.api.v1 import v1_router
from App.core.settings import settings
from App.core.LoggingInit import get_core_logger

# Initialize Logger
logger = get_core_logger(__name__)

# Initialize Limiter
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMIT_DEFAULT] if settings.RATE_LIMIT_DEFAULT else ["100/minute"]
)

def create_default_admin():
    """Create default admin user on startup if not exists"""
    from App.api.dependencies.sqlite_connector import SessionLocal
    from App.repository.userRepository import UserRepository
    from App.api.dependencies.auth import get_password_hash
    
    db = SessionLocal()
    try:
        repo = UserRepository(db)
        admin_username = os.getenv("ADMIN_USERNAME", "admin")
        admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
        admin_password = os.getenv("ADMIN_PASSWORD", "Admin@123")
        
        # Check if admin exists
        existing_admin = repo.get_by_username(admin_username)
        if not existing_admin:
            admin_data = {
                "username": admin_username,
                "email": admin_email,
                "full_name": "System Administrator",
                "password_hash": get_password_hash(admin_password),
                "user_role": "admin",
                "is_active": True,
                "disabled": False,
                "is_admin": True
            }
            repo.create_user(admin_data)
            logger.info(f"Default admin user created: {admin_username}")
        else:
            logger.info(f"Admin user already exists: {admin_username}")
    except Exception as e:
        logger.error(f"Error creating default admin: {e}")
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app):
    logger.info("App started")
    
    # Create default admin user
    create_default_admin()
    
    yield
    logger.info("app end")

app = FastAPI(title="Langchain API", version="0.0.1", lifespan=lifespan)

# State and Exception Handlers
app.state.limiter = limiter
app.state.auto_kill_enabled = False  # Global flag for automatic protection




@app.exception_handler(RateLimitExceeded)
async def custom_rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Robust rate limit handler that avoids AttributeError if exc is not as expected"""
    detail = getattr(exc, "detail", str(exc))
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"error": f"Rate limit exceeded: {detail}"}
    )

@app.middleware("http")
async def kill_switch_middleware(request: Request, call_next):
    """Global middleware for emergency kill switch (Maintenance Mode)"""
    # Whitelist System and Documentation endpoints
    path = request.url.path
    is_whitelisted = (
        path == "/health" or 
        path.startswith("/docs") or 
        path.startswith("/redoc") or 
        path.startswith("/openapi.json")
    )
    
    # Check both manual and automatic kill switches
    is_killed = settings.KILL_SWITCH_ENABLED or app.state.auto_kill_enabled
    
    if is_killed and not is_whitelisted:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": "Service is temporarily unavailable due to maintenance.",
                "type": "auto_kill" if app.state.auto_kill_enabled else "manual_kill"
            }
        )
    
    try:
        response = await call_next(request)
        return response
    except Exception as e:
        logger.error(f"CRITICAL: Unhandled exception detected. Triggering AUTO-KILL. Error: {e}")
        app.state.auto_kill_enabled = True
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An internal error occurred. System has entered safety mode."}
        )

# Add Middlewares (Order: Outermost -> Innermost)
# 1. CORS (Outermost)
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)

# 2. Rate Limiter Middleware (Inner)
app.add_middleware(SlowAPIMiddleware)



@app.get("/health", status_code=status.HTTP_200_OK, tags=["System"])
async def health_check():
    """Simple health check endpoint for monitoring"""
    return {"status": "healthy", "version": "0.0.1"}

app.include_router(v1_router, prefix="/app/v1")
