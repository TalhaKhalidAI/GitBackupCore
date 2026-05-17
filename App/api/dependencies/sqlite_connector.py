from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool  # <--- Import this
from App.core.settings import settings

# SQLite Connector with NullPool
engine = create_engine(
    settings.SQLITE_DATABASE_URL, 
    connect_args={"check_same_thread": False},
    poolclass=NullPool  # <--- Use NullPool here
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()