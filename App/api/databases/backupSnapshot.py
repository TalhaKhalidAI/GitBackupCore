from sqlalchemy import Column, Integer, String, Boolean, DateTime, func, VARCHAR, ForeignKey, Text, Float, Index
 
from App.api.dependencies.sqlite_connector import Base, engine

class BackupSnapshot(Base):
    __tablename__ = "backup_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign keys
    repo_id = Column(Integer, ForeignKey("repositories.id"), nullable=False)
    ssh_key_id = Column(Integer, ForeignKey("ssh_keys.id"), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Git commit info
    commit_sha = Column(VARCHAR(40), nullable=False, unique=True)
   
    # SSH transfer info
    client_ip = Column(VARCHAR(45), nullable=True)
    client_hostname = Column(VARCHAR(255), nullable=True)
  
    # Backup type and status
    backup_type = Column(String, default="scheduled")
    backup_status = Column(String, default="pending")
    
    # Stats
    size_mb = Column(Integer, nullable=False, default=0)
    file_count = Column(Integer, nullable=False, default=0)
    changed_files = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Integer, nullable=True)
    transfer_speed_mbps = Column(Integer, nullable=True)  # ← ADD THIS
    
    # Retention
    expires_at = Column(DateTime, nullable=True)
    
    # Soft delete
    deleted_at = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
    
    # ============================================================
    # INDEXES - Fixed (added back commit_sha with unique name)
    # ============================================================
    __table_args__ = (
        Index('idx_repo_snapshots', 'repo_id', 'created_at'),
        Index('idx_snapshot_commit_sha', 'commit_sha'),
        Index('idx_expires_at', 'expires_at'),
    )