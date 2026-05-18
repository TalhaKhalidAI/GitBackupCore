from sqlalchemy import Column, Integer, String, Boolean, DateTime,func,VARCHAR,ForeignKey,Text

from datetime import datetime
from typing import List, Optional
from App.api.dependencies.sqlite_connector import Base, engine

from sqlalchemy import UniqueConstraint, Index


class SSHKey(Base):  # ← FIX: PascalCase class name
    __tablename__ = "ssh_keys"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    key_name = Column(String, nullable=False)
    public_key = Column(Text, nullable=False)
    fingerprint = Column(VARCHAR(255), nullable=False, unique=True)  
    key_type = Column(VARCHAR(50))
    allowed_repositories = Column(Text)
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime, nullable=True) 
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
    __table_args__ = (
        Index('idx_ssh_fingerprint', 'fingerprint'),
        Index('idx_user_ssh_keys', 'user_id', 'is_active'),
        Index('idx_ssh_expires', 'expires_at'),
    )