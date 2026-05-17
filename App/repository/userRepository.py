from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from App.api.databases.Users import User


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, user_id: int) -> Optional[User]:
        """Get user by ID"""
        return self.db.query(User).filter(
            User.id == user_id,
            User.is_deleted == False
        ).first()

    def get_by_username(self, username: str) -> Optional[User]:
        """Get user by username"""
        return self.db.query(User).filter(
            User.username == username,
            User.is_deleted == False
        ).first()

    def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email"""
        return self.db.query(User).filter(
            User.email == email,
            User.is_deleted == False
        ).first()

    def get_users(self, skip: int = 0, limit: int = 100) -> List[User]:
        """Get all active users"""
        return self.db.query(User).filter(
            User.is_deleted == False
        ).offset(skip).limit(limit).all()

    def create_user(self, user_data: Dict[str, Any]) -> User:
        """Create a new user (signup)"""
        db_user = User(**user_data)
        self.db.add(db_user)
        self.db.commit()
        self.db.refresh(db_user)
        return db_user

    def update_user(self, user_id: int, update_data: Dict[str, Any]) -> Optional[User]:
        """Update user information"""
        db_user = self.db.query(User).filter(
            User.id == user_id,
            User.is_deleted == False
        ).first()
        
        if db_user:
            for key, value in update_data.items():
                if hasattr(db_user, key) and key not in ['id', 'password_hash']:
                    setattr(db_user, key, value)
            self.db.commit()
            self.db.refresh(db_user)
        return db_user

    def delete_user(self, user_id: int, soft_delete: bool = True) -> bool:
        """Delete user - soft delete by default, hard delete if specified"""
        db_user = self.db.query(User).filter(User.id == user_id).first()
        if not db_user:
            return False
        
        if soft_delete:
            # Soft Delete
            db_user.is_deleted = True
            db_user.deleted_at = datetime.utcnow()
            db_user.is_active = False
            self.db.commit()
        else:
            # Hard Delete
            self.db.delete(db_user)
            self.db.commit()
        return True

    def restore_user(self, user_id: int) -> Optional[User]:
        """Restore a soft-deleted user"""
        db_user = self.db.query(User).filter(
            User.id == user_id,
            User.is_deleted == True
        ).first()
        
        if db_user:
            db_user.is_deleted = False
            db_user.deleted_at = None
            db_user.is_active = True
            self.db.commit()
            self.db.refresh(db_user)
        return db_user

    def authenticate(self, username: str, password: str) -> Optional[User]:
        """Authenticate user by username and password - returns user if valid"""
        user = self.get_by_username(username)
        if not user:
            return None
        # Note: Password verification is done in auth.py using verify_password
        return user

    def change_password(self, user_id: int, new_password_hash: str) -> bool:
        """Change user password"""
        db_user = self.get_by_id(user_id)
        if not db_user:
            return False
        
        db_user.password_hash = new_password_hash
        self.db.commit()
        return True

    def deactivate_user(self, user_id: int) -> bool:
        """Deactivate user account (soft disable)"""
        db_user = self.get_by_id(user_id)
        if not db_user:
            return False
        
        db_user.disabled = True
        db_user.is_active = False
        self.db.commit()
        return True

    def activate_user(self, user_id: int) -> bool:
        """Activate user account"""
        db_user = self.get_by_id(user_id)
        if not db_user:
            return False
        
        db_user.disabled = False
        db_user.is_active = True
        self.db.commit()
        return True

    def get_deleted_users(self) -> List[User]:
        """Get all soft-deleted users"""
        return self.db.query(User).filter(User.is_deleted == True).all()

    def reset_password(self, user_id: int, new_password_hash: str) -> bool:
        """Reset user password (admin only)"""
        db_user = self.get_by_id(user_id)
        if not db_user:
            return False
        
        db_user.password_hash = new_password_hash
        self.db.commit()
        return True
