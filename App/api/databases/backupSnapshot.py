from sqlalchemy import Column, Integer, String, Boolean, DateTime, func, VARCHAR, ForeignKey, Text, Float, Index
 
from App.api.dependencies.sqlite_connector import Base, engine
class BackupSnapshot(Base):
    __tablename__ = "backup_snapshots"  # ← FIXED: was "ssh_keys"

    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign keys
    repo_id = Column(Integer, ForeignKey("repositories.id"), nullable=False)
    ssh_key_id = Column(Integer, ForeignKey("ssh_keys.id"), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Git commit info
    commit_sha = Column(VARCHAR(40), nullable=False, unique=True)
    parent_commit_sha = Column(VARCHAR(40), nullable=True)  # ← nullable=True (first commit has no parent)
    
    # SSH transfer info
    client_ip = Column(VARCHAR(45), nullable=True)
    client_hostname = Column(VARCHAR(255), nullable=True)
    git_protocol_version = Column(String, nullable=True)
    
    # Backup type
    backup_type = Column(String, default="scheduled")  # scheduled, manual, full, incremental
    
    # Backup status
    backup_status = Column(String, default="pending")  # pending, running, success, failed, corrupted
    
    # Stats
    size_mb = Column(Integer, nullable=False, default=0)
    file_count = Column(Integer, nullable=False, default=0)
    changed_files = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Integer, nullable=True)
    transfer_speed_mbps = Column(Integer, nullable=True)
    packets_sent = Column(Integer, nullable=True)  # ← FIXED: was packets_send
    packets_received = Column(Integer, nullable=True)
    compression_ratio = Column(Float, nullable=True)
    
    # Commit metadata
    commit_message = Column(Text, nullable=True)
    author_name = Column(String, nullable=True)
    author_email = Column(String, nullable=True)
    commit_time = Column(DateTime, nullable=False)  # ← NOT NULL per diagram
    
    # Source info
    source_path = Column(Text, nullable=True)
    source_hostname = Column(VARCHAR(255), nullable=True)
    source_username = Column(String, nullable=True)
    
    # Verification
    verified_at = Column(DateTime, nullable=True)
    verification_status = Column(String, nullable=True)  # pending, passed, failed
    verification_sha = Column(VARCHAR(40), nullable=True)
    
    # Retention
    expires_at = Column(DateTime, nullable=True)  # NULL = keep forever
    
    # Soft delete
    deleted_at = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
    
    # ============================================================
    # INDEXES - Matching your diagram
    # ============================================================
    __table_args__ = (
        Index('idx_repo_snapshots', 'repo_id', 'created_at'),
        Index('idx_repo_status_time', 'repo_id', 'backup_status', 'created_at'),
        Index('idx_commit_sha', 'commit_sha'),
        Index('idx_backup_ssh_key', 'ssh_key_id'),
        Index('idx_backup_client_ip', 'client_ip'),
        Index('idx_expires_at', 'expires_at'),
        Index('idx_source_hostname', 'source_hostname'),
    )
 