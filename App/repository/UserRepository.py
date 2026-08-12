# App/repository/UserRepository.py - CLEANER VERSION
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_,or_
from typing import Optional, List, Dict, Any, Tuple
import logging
from datetime import datetime,timezone
# Import ONLY SQLAlchemy model
from App.api.databases.MigrateTable import User as UserModel

logger = logging.getLogger(__name__)

class UserRepository:
    """Repository for user database operations - NO SCHEMA DEPENDENCIES"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    # ========== BASIC CRUD ==========
    
    async def get_by_id(self, user_id: int) -> Optional[UserModel]:
        """Get user by ID"""
        try:
            result = await self.session.execute(
                select(UserModel).where(UserModel.id == user_id)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error getting user by ID {user_id}: {e}")
            return None

    async def get_by_ids(self, user_ids: List[int]) -> List[UserModel]:
        """
        Get multiple users by their IDs.
        
        Args:
            user_ids: List of user IDs
            
        Returns:
            List of User objects
        """
        try:
            if not user_ids:
                return []
            
            result = await self.session.execute(
                select(UserModel).where(UserModel.id.in_(user_ids))
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error getting users by IDs {user_ids}: {e}")
            return []

    async def get_by_email(self, email: str) -> Optional[UserModel]:
        """Get user by email"""
        try:
            result = await self.session.execute( 
                select(UserModel).where(UserModel.email == email)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error getting user by email {email}: {e}")
            return None
    
    async def get_by_name(self, name: str) -> Optional[UserModel]:
        """Get user by name"""
        try:
            result = await self.session.execute(
                select(UserModel).where(UserModel.name == name)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error getting user by name {name}: {e}")
            return None
    
    async def create(self, user_data: Dict[str, Any]) -> Optional[UserModel]:
        """Create new user from dictionary"""
        try:
            user = UserModel(**user_data)
            self.session.add(user)
            await self.session.commit()
            await self.session.refresh(user)
            
            logger.info(f"Created new user: {user.email}")
            return user
            
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Error creating user: {e}")
            return None
    
    async def update(self, user_id: int, update_data: Dict[str, Any]) -> Optional[UserModel]:
        """Update user with dictionary"""
        try:
            user = await self.get_by_id(user_id)
            if not user:
                return None
            
            for field, value in update_data.items():
                if hasattr(user, field):
                    setattr(user, field, value)
            
            await self.session.commit()
            await self.session.refresh(user)
            
            logger.info(f"Updated user {user_id}")
            return user
            
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Error updating user {user_id}: {e}")
            return None
    
    async def update_password_hash(self, user_id: int, password_hash: str) -> bool:
        """Update only password hash"""
        try:
            user = await self.get_by_id(user_id)
            if not user:
                return False
            
            user.password_hash = password_hash
            await self.session.commit()
            logger.info(f"Updated password hash for user {user_id}")
            return True
            
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Error updating password for user {user_id}: {e}")
            return False
    
    # FIXED delete method - allows account restoration
    async def disable_account(self, user_id: int) -> bool:
        """Soft delete user (disable only)"""
        try:
            user = await self.get_by_id(user_id)
            if not user:
                return False
            
            # Only set disabled flag, keep is_active for possible restoration
            user.disabled = True
            await self.session.commit()
            
            logger.info(f"Soft deleted (disabled) user {user_id}")
            return True
            
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Error deleting user {user_id}: {e}")
            return False

 
    async def restore_disable(self, user_id: int) -> bool:
        """Fully restore a disabled user account"""
        try:
            user = await self.get_by_id(user_id)
            if not user:
                return False
            if user.disabled:
                user.disabled = False
                user.is_active = True  # ✅ Restore active status
                # ✅ Don't touch is_deleted (deleted is separate)
                await self.session.commit()
                await self.session.refresh(user)
                logger.info(f"✅ User {user_id} fully restored from disabled")
                return True
            return False
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Error restoring user {user_id}: {e}")
            return False

    async def full_restore(self, user_id: int) -> bool:
        """Complete account restoration - handles all states"""
        try:
            user = await self.get_by_id(user_id)
            if not user:
                return False
            
            # ✅ Restore EVERYTHING
            user.disabled = False
            user.is_active = True
            user.is_deleted = False
            user.deleted_at = None
            
            await self.session.commit()
            await self.session.refresh(user)
            logger.info(f"✅ User {user_id} fully restored")
            return True
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Error fully restoring user {user_id}: {e}")
            return False
            
    async def delete_account(self, user_id: int) -> bool:
        """
        Soft delete a user account.
        Sets is_deleted=True, disabled=True, is_active=False, and records deletion timestamp.
        """
        try:
            user = await self.get_by_id(user_id)
            if not user:
                logger.warning(f"User {user_id} not found for deletion")
                return False
            
            # ✅ Check if already deleted
            if user.is_deleted:
                logger.info(f"User {user_id} is already deleted")
                return False
            
            # ✅ Soft delete the user
            user.is_deleted = True
            
            user.disabled = True
            user.is_active = False
            
            await self.session.commit()
            await self.session.refresh(user)
            
            logger.info(f"✅ User {user_id} soft deleted at {user.deleted_at}")
            return True
            
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Error soft deleting user {user_id}: {e}")
            return False

    async def restore_deleted(self, user_id: int) -> bool:
        """Restore a soft-deleted user account"""
        try:
            user = await self.get_by_id(user_id)
            if not user:
                logger.warning(f"User {user_id} not found for restoration")
                return False
            
            # ✅ Check if user is actually deleted
            if not user.is_deleted:
                logger.info(f"User {user_id} is not deleted")
                return False
            
            # ✅ Restore the user
            user.is_deleted = False
            user.deleted_at = None          # ← Clear deletion timestamp
            user.disabled = False
            user.is_active = True
            
            # ✅ Save changes
            await self.session.commit()
            await self.session.refresh(user)
            
            logger.info(f"✅ User {user_id} restored successfully")
            return True
            
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Error restoring user {user_id}: {e}")
            return False
            
            pass
        except Exception as e:
            await self.session.rollback()
            logging.error(f"Error restore delete user due to {e}")
            return False
    
    # ========== QUERIES ==========
    
    async def get_user_role(self, user_id: int) -> Optional[str]:
        """Get user role by ID"""
        user = await self.get_by_id(user_id)
        return user.user_role if user else None
    
    async def is_user_active(self, user_id: int) -> bool:
        """Check if user is active and not disabled"""
        user = await self.get_by_id(user_id)
        return bool(user and user.is_active and not user.disabled)
    
    async def is_user_disabled(self, user_id: int) -> bool:
        """Check if user is disabled"""
        user = await self.get_by_id(user_id)
        return bool(user and user.disabled)
    
    async def search_users(
        self, 
        skip: int = 0, 
        limit: int = 100,
        active_only: bool = True,
        search: Optional[str] = None
    ) -> List[UserModel]:
        """Search users with pagination"""
        try:
            query = select(UserModel)
            
            # Apply filters
            if active_only:
                query = query.where(
                    and_(
                        UserModel.is_active == True,
                        UserModel.disabled == False
                    )
                )
            
            # Apply search
            if search:
                search_filter = UserModel.name.ilike(f"%{search}%")
                if '@' in search:  # Likely an email search
                    search_filter = search_filter | UserModel.email.ilike(f"%{search}%")
                query = query.where(search_filter)
            
            # Apply pagination and ordering
            query = query.offset(skip).limit(limit).order_by(UserModel.created_at.desc())
            
            result = await self.session.execute(query)
            return result.scalars().all()
            
        except Exception as e:
            logger.error(f"Error searching users: {e}")
            return []
    
    async def count_users(self, active_only: bool = True) -> int:
        """Count total users"""
        try:
            query = select(UserModel)
            
            if active_only:
                query = query.where(
                    and_(
                        UserModel.is_active == True,
                        UserModel.disabled == False
                    )
                )
            
            result = await self.session.execute(query)
            return len(result.scalars().all())
            
        except Exception as e:
            logger.error(f"Error counting users: {e}")
            return 0
    
    async def exists_by_email(self, email: str) -> bool:
        """Check if user exists by email"""
        user = await self.get_by_email(email)
        return user is not None
    
    async def get_with_profile(self, user_id: int) -> Optional[Tuple[UserModel, Any]]:
        """Get user with related profile data (if you have profiles)"""
        try:
            from sqlalchemy.orm import joinedload
            
            result = await self.session.execute(
                select(UserModel)
                .options(joinedload(UserModel.profile))  # If you have relationship
                .where(UserModel.id == user_id)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error getting user with profile {user_id}: {e}")
            return None
    
    # ========== UTILITIES ==========
    
    def to_dict(self, user: UserModel, exclude: List[str] = None) -> Dict[str, Any]:
        """Convert SQLAlchemy model to dictionary (NO Pydantic dependency)"""
        if exclude is None:
            exclude = []
        
        result = {}
        for column in user.__table__.columns:
            col_name = column.name
            if col_name not in exclude:
                result[col_name] = getattr(user, col_name)
        
        return result
    
    def to_safe_dict(self, user: UserModel) -> Dict[str, Any]:
        """Convert to dictionary excluding sensitive fields"""
        exclude_fields = ['password_hash', 'secret_key', 'token']
        return self.to_dict(user, exclude=exclude_fields)
    
    async def bulk_create(self, users_data: List[Dict[str, Any]]) -> List[UserModel]:
        """Create multiple users"""
        users = []
        try:
            for user_data in users_data:
                user = UserModel(**user_data)
                self.session.add(user)
                users.append(user)
            
            await self.session.commit()
            
            # Refresh all users
            for user in users:
                await self.session.refresh(user)
            
            logger.info(f"Created {len(users)} users")
            return users
            
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Error in bulk create: {e}")
            return []
    
    async def bulk_update(self, user_updates: List[Tuple[int, Dict[str, Any]]]) -> int:
        """Bulk update users"""
        updated_count = 0
        try:
            for user_id, update_data in user_updates:
                user = await self.get_by_id(user_id)
                if user:
                    for field, value in update_data.items():
                        if hasattr(user, field):
                            setattr(user, field, value)
                    updated_count += 1
            
            await self.session.commit()
            logger.info(f"Bulk updated {updated_count} users")
            return updated_count
            
        except Exception as e:
            await self.session.rollback()
            logger.error(f"Error in bulk update: {e}")
            return 0
    
    @classmethod
    async def create_admin_if_not_exists(
        cls,
        session: AsyncSession,  # ← MUST pass session explicitly
        email: str,
        password_hash: str,
        name: str = "System Administrator",
        role: str = "admin",
        permissions: Dict[str, bool] = None,
    ) -> Optional[UserModel]:
        """
        Create admin user if it doesn't exist.
        
        This is a CLASS METHOD for use in migrations.
        Pass session explicitly.
        
        Args:
            session: Database session (required)
            email: Admin email
            password_hash: Hashed password
            name: Admin name
            role: User role
        """
        try:
            # ✅ Use session directly (no self)
            result = await session.execute(
                select(UserModel).where(or_(UserModel.email == email,UserModel.name==name))
            )
            existing_user = result.scalar_one_or_none()
            
            # If user exists
            if existing_user:
                if existing_user.user_role == "admin":
                    logger.info(f"✅ Admin already exists: {email}")
                    return existing_user
                
                # Promote to admin
                logger.info(f"🔄 Promoting user to admin: {email}")
                existing_user.user_role = "admin"
              
                await session.commit()
                await session.refresh(existing_user)
                logger.info(f"✅ Promoted user to admin: {email}")
                return existing_user
            
            # Create new admin
            logger.info(f"🆕 Creating new admin: {email}")
            new_admin = UserModel(
                name=name,
                email=email,
                password_hash=password_hash,
                user_role=role,
                is_active=True,
                disabled=False,
                is_deleted=False,
                permissions=permissions or {}
          
            )
            session.add(new_admin)
            await session.commit()
            await session.refresh(new_admin)
            logger.info(f"✅ New admin created: {email}")
            return new_admin
            
        except Exception as e:
            await session.rollback()
            logger.error(f"❌ Error creating/promoting admin: {e}")
            return None
 
    async def set_permissions(self, user_id: int, permissions: Dict[str, bool]) -> UserModel:
        """
        Set permissions for a user (MERGE behavior):
        - If permission key exists, update its value
        - If permission key doesn't exist, add it
        - Other existing permissions remain unchanged
        
        Args:
            user_id: User ID
            permissions: Dict of permissions to merge
            
        Returns:
            Updated User object
            
        Raises:
            ValueError: If user not found or update fails
        """
        try:
            # Use empty dict if None
            permissions = permissions or {}
            
            # Get user
            user = await self.get_by_id(user_id)
            if not user:
                raise ValueError(f"User {user_id} not found")
            
            # Initialize permissions if None
            if user.permissions is None:
                user.permissions = {}
            
            # MERGE: Update only the provided keys
            for key, value in permissions.items():
                user.permissions = {**user.permissions, **permissions}  # ← CORRECT! Merges

            
            # Commit changes
            await self.session.commit()
            await self.session.refresh(user)
            
            return user
            
        except ValueError:
            # Re-raise ValueError as-is
            raise
        except Exception as e:
            await self.session.rollback()
            raise ValueError(f"Failed to merge permissions for user {user_id}: {str(e)}")
    
    async def replace_all_permissions(self, user_id: int, permissions: Dict[str, bool]) -> UserModel:
        """
        Replace ALL permissions for a user with new ones.
        (Use this if you want to completely overwrite)
        
        Args:
            user_id: User ID
            permissions: New permissions dict to replace all existing permissions
            
        Returns:
            Updated User object
            
        Raises:
            ValueError: If user not found or update fails
        """
        try:
            # Use empty dict if None
            permissions = permissions or {}
            
            # Get user
            user = await self.get_by_id(user_id)
            if not user:
                raise ValueError(f"User {user_id} not found")
            
            # Replace entire permissions dict
            user.permissions = permissions
            
            # Commit changes
            await self.session.commit()
            await self.session.refresh(user)
            
            return user
            
        except ValueError:
            # Re-raise ValueError as-is
            raise
        except Exception as e:
            await self.session.rollback()
            raise ValueError(f"Failed to replace permissions for user {user_id}: {str(e)}")

    async def remove_permissions(self, user_id: int, permission_keys: List[str]) -> UserModel:
        try:
            permission_keys = permission_keys or []

            user = await self.get_by_id(user_id)
            if not user:
                raise ValueError(f"User {user_id} not found")

            current_perms = dict(user.permissions or {})  # copy, don't mutate original

            removed_keys = []
            for key in permission_keys:
                if key in current_perms:
                    del current_perms[key]
                    removed_keys.append(key)

            user.permissions = current_perms  # ✅ reassignment -> flags column dirty

            await self.session.commit()
            await self.session.refresh(user)

            if removed_keys:
                logger.info(f"🗑️ Removed permissions for user {user_id}: {removed_keys}")
            else:
                logger.info(f"ℹ️ No permissions removed for user {user_id}")

            return user

        except ValueError:
            raise
        except Exception as e:
            await self.session.rollback()
            logger.error(f"❌ Failed to remove permissions for user {user_id}: {str(e)}")
            raise ValueError(f"Failed to remove permissions for user {user_id}: {str(e)}")   
 
    async def remove_all_permissions(self, user_id: int) -> UserModel:
        """
        Remove ALL permissions from a user.
        
        Args:
            user_id: User ID
            
        Returns:
            Updated User object
            
        Raises:
            ValueError: If user not found or update fails
        """
        try:
            user = await self.get_by_id(user_id)
            if not user:
                raise ValueError(f"User {user_id} not found")
            
            user.permissions = {}
            
            await self.session.commit()
            await self.session.refresh(user)
            
            logger.info(f"🗑️ Removed ALL permissions for user {user_id}")
            
            return user
            
        except ValueError:
            raise
        except Exception as e:
            await self.session.rollback()
            logger.error(f"❌ Failed to remove ALL permissions for user {user_id}: {str(e)}")
            raise ValueError(f"Failed to remove ALL permissions for user {user_id}: {str(e)}")
        
    async def get_user_permission_db(
        self, 
        user_id: Optional[int] = None,
        skip: int = 0,
        limit: int = 100,
        include_user_info: bool = False
    ) -> Dict[str, Any]:
        """
        Get user permissions with pagination support.
        
        Args:
            user_id: Optional user ID. If provided, returns permissions for specific user.
            skip: Number of records to skip (pagination)
            limit: Maximum number of records to return (pagination)
            include_user_info: If True, includes user email and name in response
            
        Returns:
            If user_id provided:
                {
                    "permissions": {"calc.basic": true, "calc.filters": true},
                    "user_info": {"id": 1, "email": "user@example.com", "name": "User Name"}  # if include_user_info=True
                }
            If no user_id:
                {
                    "users": {
                        "1": {
                            "permissions": {"calc.basic": true, "calc.filters": true},
                            "email": "user1@example.com",
                            "name": "User One"
                        }
                    },
                    "pagination": {
                        "total": 10,
                        "skip": 0,
                        "limit": 100,
                        "has_next": False,
                        "next": None
                    }
                }
        """
        try:
            from sqlalchemy import select, func
            
            # ============================================================
            # ✅ CASE 1: Get permissions for specific user
            # ============================================================
            if user_id is not None:
                user = await self.get_by_id(user_id)
                if not user:
                    raise ValueError(f"User {user_id} not found")
                
                if include_user_info:
                    return {
                        "permissions": user.permissions or {},
                        "user_info": {
                            "id": user.id,
                            "email": user.email,
                            "name": user.name,
                            "role": user.user_role
                        }
                    }
                else:
                    return user.permissions or {}
            
            # ============================================================
            # ✅ CASE 2: Get permissions for ALL users (with pagination)
            # ============================================================
            
            # Get total count for pagination
            count_query = select(func.count()).select_from(UserModel)
            count_query = count_query.where(
                and_(
                    UserModel.is_active == True,
                    UserModel.disabled == False,
                    UserModel.is_deleted == False
                )
            )
            total_result = await self.session.execute(count_query)
            total_count = total_result.scalar()
            
            # Get paginated users
            query = select(UserModel).where(
                and_(
                    UserModel.is_active == True,
                    UserModel.disabled == False,
                    UserModel.is_deleted == False
                )
            ).order_by(UserModel.id).offset(skip).limit(limit)
            
            result = await self.session.execute(query)
            users = result.scalars().all()
            
            # Build response
            users_dict = {}
            for user in users:
                if include_user_info:
                    users_dict[str(user.id)] = {
                        "permissions": user.permissions or {},
                        "email": user.email,
                        "name": user.name,
                        "role": user.user_role
                    }
                else:
                    users_dict[str(user.id)] = user.permissions or {}
            
            # Build pagination info
            next_skip = skip + limit
            has_next = next_skip < total_count
            
            response = {
                "users": users_dict,
                "pagination": {
                    "total": total_count,
                    "skip": skip,
                    "limit": limit,
                    "has_next": has_next,
                    "next": f"/api/v1/admin/users/permissions?skip={next_skip}&limit={limit}" if has_next else None
                }
            }
            
            return response
            
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error getting permissions: {e}")
            raise ValueError(f"Error getting permissions from DB: {str(e)}")