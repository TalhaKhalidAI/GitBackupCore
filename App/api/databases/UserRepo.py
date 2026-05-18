from sqlalchemy import Column, Integer, String, Boolean, DateTime,func,VARCHAR,ForeignKey

from datetime import datetime
from typing import List, Optional
from App.api.dependencies.sqlite_connector import Base, engine

from sqlalchemy import UniqueConstraint, Index

class userRepo(Base):
    __tablename__ = "user_repo"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    repo_id = Column(Integer, ForeignKey("repositories.id"), nullable=False)
    permission = Column(String, nullable=False, default="read")  # read, write, admin

    # Soft delete
    deleted_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint('user_id', 'repo_id', name='idx_user_repo_unique'),
        Index('idx_repo_permission', 'repo_id', 'permission'),
    )