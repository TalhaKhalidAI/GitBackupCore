# App/core/Connector.py - PRODUCTION READY VERSION

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, AsyncEngine
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import AsyncAdaptedQueuePool
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from typing import AsyncGenerator, Optional, Dict, Any
from contextlib import asynccontextmanager
import logging
from tenacity import retry, stop_after_attempt, wait_exponential
from fastapi import HTTPException, status

from App.core.settings import settings

logger = logging.getLogger(__name__)

class Database:
    """Professional PostgreSQL database connector - Production Ready"""
    
    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or settings.database_url
        self._engine: Optional[AsyncEngine] = None
        self._session_factory: Optional[async_sessionmaker] = None
        self._is_connected = False
        self._connection_error: Optional[str] = None  # ✅ Track errors
    
# App/core/Connector.py - REPLACE connect() WITH THIS

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def connect(self) -> None:
        """Connect to database with retry logic"""
        if self._is_connected:
            return
        
        try:
            # Mask password in logs
            safe_url = self.db_url
            if '@' in safe_url:
                parts = safe_url.split('@')
                if ':' in parts[0]:
                    user_pass = parts[0].split(':')
                    if len(user_pass) > 1:
                        safe_url = f"{user_pass[0]}:****@{parts[1]}"
            
            logger.info(f"🔄 Connecting to database: {safe_url}")
            
            pool_params = {
                "pool_size": 10,
                "max_overflow": 20,
                "pool_recycle": 1800,
                "pool_timeout": 30
            }
            
            self._engine = create_async_engine(
                self.db_url,
                echo=settings.DATABASE_ECHO if hasattr(settings, 'DATABASE_ECHO') else False,
                poolclass=AsyncAdaptedQueuePool,
                pool_size=pool_params["pool_size"],
                max_overflow=pool_params["max_overflow"],
                pool_recycle=pool_params["pool_recycle"],
                pool_timeout=pool_params["pool_timeout"],
                pool_pre_ping=True,
                connect_args={
                    "server_settings": {
                        "search_path": settings.DATABASE_SCHEMA if hasattr(settings, 'DATABASE_SCHEMA') else "public",
                        "application_name": settings.DATABASE_NAME if hasattr(settings, 'DATABASE_NAME') else "fastapi_app",
                        "timezone": "UTC"
                    },
                    "command_timeout": settings.DATABASE_CONNECT_TIMEOUT if hasattr(settings, 'DATABASE_CONNECT_TIMEOUT') else 30,
                },
                future=True,
                execution_options={
                    "isolation_level": "READ COMMITTED"  # ✅ Better for performance
                }
            )
            
            # Test connection
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                logger.debug("Database connection test successful")
            
            self._session_factory = async_sessionmaker(
                bind=self._engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autocommit=False,
                autoflush=False,
            )
            
            self._is_connected = True
            self._connection_error = None
            logger.info("✅ Database connected successfully")
            
        except OperationalError as e:
            self._is_connected = False
            self._connection_error = str(e)
            logger.error(f"❌ Database connection error: {e}")
            raise  # Re-raise for retry
            
        except Exception as e:
            self._is_connected = False
            self._connection_error = str(e)
            logger.error(f"❌ Database error: {e}")
            raise RuntimeError(f"Database connection failed: {e}")
    
    async def disconnect(self) -> None:
        """Disconnect from database"""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            self._is_connected = False
            self._connection_error = None
            logger.info("Database disconnected")
    
    async def health_check(self) -> Dict[str, Any]:  # ✅ Returns dict with details
        """Check database health with detailed status"""
        if not self._is_connected:
            return {
                "status": "disconnected",
                "connected": False,
                "error": self._connection_error or "Not connected"
            }
        
        try:
            async with self._engine.connect() as conn:
                result = await conn.execute(text("SELECT 1"))
                return {
                    "status": "healthy",
                    "connected": True,
                    "error": None
                }
        except Exception as e:
            self._is_connected = False
            self._connection_error = str(e)
            logger.warning(f"Database health check failed: {e}")
            return {
                "status": "error",
                "connected": False,
                "error": str(e)
            }
    
    @property
    def is_connected(self) -> bool:
        return self._is_connected
    
    @property
    def connection_error(self) -> Optional[str]:
        return self._connection_error
    
    @property
    def engine(self) -> AsyncEngine:
        if not self._engine:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._engine
    
    @property
    def session_factory(self) -> async_sessionmaker:
        if not self._session_factory:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._session_factory
    
    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Context manager for database sessions
        Automatically handles commit/rollback
        """
        # ✅ Check connection before creating session
        if not self._is_connected:
            logger.warning("Database not connected, attempting to reconnect...")
            try:
                await self.connect()
            except Exception as e:
                logger.error(f"Failed to reconnect: {e}")
                raise RuntimeError(f"Database connection failed: {e}")
        
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except OperationalError as e:
                await session.rollback()
                self._is_connected = False
                self._connection_error = str(e)
                logger.error(f"Database operational error: {e}")
                raise  # Re-raise for get_db() to handle
            except SQLAlchemyError as e:
                await session.rollback()
                logger.error(f"Database SQL error: {e}")
                raise
            except Exception as e:
                await session.rollback()
                logger.error(f"Database session error: {e}")
                raise
            finally:
                await session.close()
    
    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession, None]:
        """Context manager for transactions"""
        async with self.session() as session:
            async with session.begin():
                yield session

# SQLAlchemy Base for models
Base = declarative_base()

# Database instance (singleton for the application)
database = Database()

# ========== PRODUCTION-READY get_db() ==========
# App/core/Connector.py - REPLACE get_db() WITH THIS

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency injection for database sessions.
    Auto-connects if not connected. Returns proper HTTP errors.
    """
    # ✅ 1. Auto-connect if not connected
    if not database.is_connected:
        logger.warning("⚠️ Database not connected, attempting to connect on-demand...")
        try:
            await database.connect()
            logger.info("✅ Database connected successfully on-demand!")
        except Exception as e:
            logger.error(f"❌ On-demand connection failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "database_unavailable",
                    "message": "Database service is temporarily unavailable. Please try again later.",
                    "status": "disconnected"
                }
            )
    
    try:
        # ✅ 2. Try to get session
        async with database.session() as session:
            yield session
            
    except OperationalError as e:
        # ✅ 3. Handle database connection errors
        logger.error(f"❌ Database operational error: {e}")
        database._is_connected = False
        database._connection_error = str(e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "database_connection_lost",
                "message": "Database connection was lost. Please try again.",
                "status": "error"
            }
        )
        
    except SQLAlchemyError as e:
        # ✅ 4. Handle SQL errors
        logger.error(f"❌ Database SQL error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "database_error",
                "message": "A database error occurred. Please try again.",
                "status": "error"
            }
        )
        
    except HTTPException:
        # ✅ 5. Re-raise HTTP exceptions (don't wrap them)
        raise
        
    except Exception as e:
        # ✅ 6. Handle unexpected errors
        logger.error(f"❌ Database unexpected error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "internal_error",
                "message": "An unexpected database error occurred.",
                "status": "error"
            }
        )

# Repository base class
class BaseRepository:
    """Base repository for database operations"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def execute_raw(self, query: str, params: dict = None):
        """Execute raw SQL query"""
        from sqlalchemy import text
        return await self.session.execute(text(query), params or {})