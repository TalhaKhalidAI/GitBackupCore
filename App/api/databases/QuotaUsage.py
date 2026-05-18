# App/models/quota_usage.py
from sqlalchemy import Column, Integer, DateTime, Date, func, ForeignKey, Index
from App.api.dependencies.sqlite_connector import Base,engine

class QuotaUsage(Base):
    __tablename__ = "quota_usage"

    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    repo_id = Column(Integer, ForeignKey("repositories.id"), nullable=True)
    
    # Usage data
    usage_date = Column(Date, nullable=False)
    storage_used_mb = Column(Integer, nullable=False, default=0)
    backup_count = Column(Integer, nullable=False, default=0)
    
    # Soft delete
    deleted_at = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
    
    # Indexes
    __table_args__ = (
        Index('idx_quota_user_date', 'user_id', 'usage_date'),
        Index('idx_quota_repo_date', 'repo_id', 'usage_date'),
    )
 