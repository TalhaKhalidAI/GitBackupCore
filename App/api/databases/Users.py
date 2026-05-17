from sqlalchemy import Column, Integer, String, Boolean, DateTime
from datetime import datetime
from typing import List, Optional
from App.api.dependencies.sqlite_connector import Base, engine

# User Model
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    full_name = Column(String, nullable=True)
    password_hash = Column(String)
    user_role = Column(String, default="user")  # user, admin
    is_active = Column(Boolean, default=True)
    disabled = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    
    # Soft Delete attributes
    is_deleted = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)

# Create tables
Base.metadata.create_all(bind=engine)

