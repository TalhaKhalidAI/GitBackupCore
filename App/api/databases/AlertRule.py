# App/models/alert_rule.py
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, func, ForeignKey, Index
from App.api.dependencies.sqlite_connector import Base,engine

class AlertRule(Base):
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign keys
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    repo_id = Column(Integer, ForeignKey("repositories.id"), nullable=True)
    
    # Alert type: backup_failed, quota_exceeded, key_expiring, repo_inactive, verification_failed
    alert_type = Column(String, nullable=False)
    
    # Notification settings
    notify_email = Column(Boolean, default=True)
    notify_webhook = Column(Boolean, default=False)
    webhook_url = Column(Text, nullable=True)
    
    # Threshold (hours) - NULL = no threshold, specific to alert type
    threshold_hours = Column(Integer, nullable=True)
    
    # Status
    is_active = Column(Boolean, default=True)
    last_triggered_at = Column(DateTime, nullable=True)
    
    # Soft delete
    deleted_at = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
    
    # Indexes
    __table_args__ = (
        Index('idx_alerts_user_type_active', 'user_id', 'alert_type', 'is_active'),
        Index('idx_alerts_repo_active', 'repo_id', 'is_active'),
    )
 