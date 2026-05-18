# App/models/retention_policy.py
from sqlalchemy import Column, Integer, DateTime, func, ForeignKey, Index
from App.api.dependencies.sqlite_connector import Base,engine

class RetentionPolicy(Base):
    __tablename__ = "retention_policies"

    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    repo_id = Column(Integer, ForeignKey("repositories.id"), nullable=True)  # NULL = applies to all user repos
    
    # Retention rules
    keep_daily = Column(Integer, default=7)
    keep_weekly = Column(Integer, default=4)
    keep_monthly = Column(Integer, default=6)
    keep_yearly = Column(Integer, default=2)
    min_backup_interval_hours = Column(Integer, default=1)
    
    # Soft delete
    deleted_at = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
    
    # Indexes
    __table_args__ = (
        Index('idx_policy_user_repo', 'user_id', 'repo_id', unique=True),
    )
