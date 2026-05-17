from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
import logging

from App.api.dependencies.sqlite_connector import get_db
from App.api.dependencies.auth import (
    get_current_user,
    get_current_active_user,
    get_admin_user,
    verify_password,
    get_password_hash,
    create_access_token
)
from App.repository.userRepository import UserRepository
from App.models.userModels import (
    LoginRequest,
    LoginResponse,
    SignupRequest,
    SignupResponse,
    UserData,
    UserUpdateRequest,
    ChangePasswordRequest,
    ResetPasswordRequest,
    MessageResponse,
    ErrorResponse,
    UserListResponse,
    UserRole
)

router = APIRouter(prefix="/users", tags=["Users"])

# Logger for user operations
logger = logging.getLogger(__name__)


# ==================== AUTH ENDPOINTS ====================

@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    user_data: SignupRequest,
    db: Session = Depends(get_db)
):
    """Register a new user"""
    repo = UserRepository(db)
    
    # Check if username already exists
    if repo.get_by_username(user_data.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )
    
    # Check if email already exists
    if repo.get_by_email(user_data.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create user
    db_user_data = {
        "username": user_data.username,
        "email": user_data.email,
        "full_name": user_data.full_name,
        "password_hash": get_password_hash(user_data.password),
        "user_role": UserRole.USER.value,
        "is_active": True,
        "disabled": False
    }
    
    user = repo.create_user(db_user_data)
    
    logger.info(f"New user registered: {user.username} (ID: {user.id})")
    
    return SignupResponse(
        user=UserData(
            id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name,
            user_role=user.user_role,
            is_active=user.is_active,
            disabled=user.disabled
        )
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    login_data: LoginRequest,
    db: Session = Depends(get_db)
):
    """Login user and get access token"""
    repo = UserRepository(db)
    user = repo.get_by_username(login_data.username)
    
    # Check if user exists
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify password
    if not verify_password(login_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if user is active
    if not user.is_active or user.disabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled"
        )
    
    # Create access token
    access_token = create_access_token(
        data={
            "sub": user.username,
            "user_id": user.id,
            "email": user.email,
            "role": user.user_role
        }
    )
    
    return LoginResponse(
        access_token=access_token,
        user=UserData(
            id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name,
            user_role=user.user_role,
            is_active=user.is_active,
            disabled=user.disabled
        )
    )


# ==================== USER ENDPOINTS ====================

@router.get("/me", response_model=UserData)
async def get_current_user_info(
    current_user: dict = Depends(get_current_active_user)
):
    """Get current user information"""
    return UserData(
        id=current_user["id"],
        username=current_user.get("username", "unknown"),
        email=current_user["email"],
        full_name=current_user.get("name"),
        user_role=current_user.get("role", "user"),
        is_active=current_user.get("is_active", True),
        disabled=current_user.get("disabled", False)
    )


@router.get("/", response_model=UserListResponse)
async def get_users(
    skip: int = 0,
    limit: int = 100,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Get all users (admin only)"""
    repo = UserRepository(db)
    users = repo.get_users(skip=skip, limit=limit)
    
    user_responses = [
        UserData(
            id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name,
            user_role=user.user_role,
            is_active=user.is_active,
            disabled=user.disabled
        )
        for user in users
    ]
    
    return UserListResponse(
        users=user_responses,
        total=len(user_responses),
        skip=skip,
        limit=limit
    )


@router.get("/{user_id}", response_model=UserData)
async def get_user(
    user_id: int,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get user by ID - normal users get their own info, admins can get any user"""
    repo = UserRepository(db)
    
    # Normal users always get their own profile, admins can specify any user_id
    if current_user.get("role") != "admin":
        # Normal users ignore the user_id and get their own profile
        user = repo.get_by_id(current_user["id"])
    else:
        # Admins can get any user
        user = repo.get_by_id(user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return UserData(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        user_role=user.user_role,
        is_active=user.is_active,
        disabled=user.disabled
    )


@router.put("/{user_id}", response_model=UserData)
async def update_user(
    user_id: int,
    user_update: UserUpdateRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update user information - normal users update own profile, admins update any user"""
    repo = UserRepository(db)
    
    # Normal users always update their own profile, admins can specify any user_id
    if current_user.get("role") != "admin":
        target_user_id = current_user["id"]
    else:
        target_user_id = user_id
    
    # Check if user exists
    existing_user = repo.get_by_id(target_user_id)
    if not existing_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Build update data (exclude None values)
    update_data = {}
    
    # Only admins can update user_role
    if user_update.user_role is not None:
        if current_user.get("role") != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can update user role"
            )
        update_data["user_role"] = user_update.user_role.value
    
    if user_update.email is not None:
        # Check if email is already taken
        email_user = repo.get_by_email(user_update.email)
        if email_user and email_user.id != target_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already in use"
            )
        update_data["email"] = user_update.email
    
    if user_update.full_name is not None:
        update_data["full_name"] = user_update.full_name
    
    updated_user = repo.update_user(target_user_id, update_data)
    
    return UserData(
        id=updated_user.id,
        username=updated_user.username,
        email=updated_user.email,
        full_name=updated_user.full_name,
        user_role=updated_user.user_role,
        is_active=updated_user.is_active,
        disabled=updated_user.disabled
    )


@router.delete("/{user_id}", response_model=MessageResponse)
async def delete_user(
    user_id: int,
    hard_delete: bool = False,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Delete user - normal users delete own account, admins delete any user"""
    repo = UserRepository(db)
    
    # Normal users always delete their own account, admins can delete any user
    if current_user.get("role") != "admin":
        target_user_id = current_user["id"]
        hard_delete = False  # Normal users can't hard delete
    else:
        target_user_id = user_id
    
    # Check if user exists
    existing_user = repo.get_by_id(target_user_id)
    if not existing_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    success = repo.delete_user(target_user_id, soft_delete=not hard_delete)
    
    logger.warning(f"User deleted: ID {target_user_id} by admin {current_user['id']} (hard_delete={hard_delete})")
    
    return MessageResponse(
        message="User deleted successfully" if success else "User not found"
    )


@router.post("/{user_id}/restore", response_model=UserData)
async def restore_user(
    user_id: int,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Restore a soft-deleted user (admin only)"""
    repo = UserRepository(db)
    
    restored_user = repo.restore_user(user_id)
    
    if not restored_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found or not deleted"
        )
    
    return UserData(
        id=restored_user.id,
        username=restored_user.username,
        email=restored_user.email,
        full_name=restored_user.full_name,
        user_role=restored_user.user_role,
        is_active=restored_user.is_active,
        disabled=restored_user.disabled
    )


@router.post("/{user_id}/deactivate", response_model=MessageResponse)
async def deactivate_user(
    user_id: int,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Deactivate a user account (admin only)"""
    repo = UserRepository(db)
    
    success = repo.deactivate_user(user_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return MessageResponse(message="User deactivated successfully")


@router.post("/{user_id}/activate", response_model=MessageResponse)
async def activate_user(
    user_id: int,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Activate a user account (admin only)"""
    repo = UserRepository(db)
    
    success = repo.activate_user(user_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return MessageResponse(message="User activated successfully")


@router.get("/deleted/list", response_model=UserListResponse)
async def get_deleted_users(
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Get all deleted users (admin only)"""
    repo = UserRepository(db)
    users = repo.get_deleted_users()
    
    user_responses = [
        UserData(
            id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name,
            user_role=user.user_role,
            is_active=user.is_active,
            disabled=user.disabled
        )
        for user in users
    ]
    
    return UserListResponse(
        users=user_responses,
        total=len(user_responses),
        skip=0,
        limit=len(user_responses)
    )


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    password_data: ChangePasswordRequest,
    current_user: dict = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Change current user's password"""
    repo = UserRepository(db)
    user = repo.get_by_id(current_user["id"])
    
    # Verify old password
    if not verify_password(password_data.old_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect old password"
        )
    
    # Update password
    success = repo.change_password(
        current_user["id"], 
        get_password_hash(password_data.new_password)
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to change password"
        )
    
    return MessageResponse(message="Password changed successfully")


@router.post("/{user_id}/reset-password", response_model=MessageResponse)
async def reset_user_password(
    user_id: int,
    password_data: ResetPasswordRequest,
    current_user: dict = Depends(get_admin_user),
    db: Session = Depends(get_db)
):
    """Reset any user's password (admin only)"""
    repo = UserRepository(db)
    
    # Check if user exists
    user = repo.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Reset password
    success = repo.reset_password(user_id, get_password_hash(password_data.new_password))
    
    logger.warning(f"Password reset for user ID {user_id} by admin {current_user['id']}")
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reset password"
        )
    
    return MessageResponse(message=f"Password reset successfully for user {user.username}")
