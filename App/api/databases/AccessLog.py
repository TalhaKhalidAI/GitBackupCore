# App/models/access_log.py
from sqlalchemy import Column, Integer, String, DateTime, Text, func, VARCHAR, ForeignKey, Index
from App.api.dependencies.sqlite_connector import Base,engine

class AccessLog(Base):
    __tablename__ = "access_logs"

    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign keys (nullable because user/repo might be deleted)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    repo_id = Column(Integer, ForeignKey("repositories.id"), nullable=True)
    ssh_key_id = Column(Integer, ForeignKey("ssh_keys.id"), nullable=True)
    
    # Operation: clone, pull, push, restore, list, create_repo, delete_repo, add_key, remove_key
    operation = Column(String, nullable=False)
    
    # Network info
    client_ip = Column(VARCHAR(45), nullable=True)
    user_agent = Column(Text, nullable=True)
    
    # Outcome
    status = Column(String, default="success")  # success, failed, denied
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    
    # Timestamp
    created_at = Column(DateTime, nullable=False, default=func.now())
    
    # Indexes
    __table_args__ = (
        Index('idx_logs_time', 'created_at'),
        Index('idx_logs_user', 'user_id', 'created_at'),
        Index('idx_logs_repo', 'repo_id', 'created_at'),
        Index('idx_logs_operation', 'operation', 'created_at'),
        Index('idx_logs_status', 'status', 'created_at'),
    )
