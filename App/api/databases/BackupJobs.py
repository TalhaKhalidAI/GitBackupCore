from sqlalchemy import Column, Integer, String, DateTime, func, VARCHAR, ForeignKey, Text, Index
from App.api.dependencies.sqlite_connector import Base, engine

class BackupJob(Base):
    __tablename__ = "backup_jobs"

    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign keys
    repo_id = Column(Integer, ForeignKey("repositories.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    snapshot_id = Column(Integer, ForeignKey("backup_snapshots.id"), nullable=True)
    
    # Job type: backup, restore, verify, prune, migrate
    job_type = Column(String, nullable=False)
    
    # Status: pending → running → success|failed
    status = Column(String, default="pending")  # pending, running, success, failed, cancelled
    
    # For restore jobs
    restore_target_path = Column(Text, nullable=True)
    
    # Progress (0-100, only meaningful when status = 'running')
    progress_percent = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    
    # Scheduling
    scheduled_for = Column(DateTime, nullable=True)  # NULL = run immediately
    
    # Timing
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # Soft delete
    deleted_at = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
    
    # ============================================================
    # INDEXES - Matching your diagram
    # ============================================================
    __table_args__ = (
        Index('idx_jobs_repo_status', 'repo_id', 'status'),
        Index('idx_jobs_user_status', 'user_id', 'status'),
        Index('idx_jobs_scheduled', 'status', 'scheduled_for'),
    )
 