from sqlalchemy import Column, Integer, String, Boolean, DateTime,func,VARCHAR,ForeignKey

from datetime import datetime
from typing import List, Optional
from App.api.dependencies.sqlite_connector import Base, engine

from sqlalchemy import UniqueConstraint, Index

class Repository(Base):
    __tablename__ = "repositories"

    id = Column(Integer, primary_key=True, index=True)
    repo_name = Column(String, nullable=False,unique=True)
    commit_sha_id = Column(VARCHAR(40), nullable=False) 
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    deleted=Column(Boolean,default=False)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

   