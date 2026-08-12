from fastapi import APIRouter, Depends, HTTPException, status, Query, Request,Response
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from App.repository.UserRepository import UserRepository
from App.core.LoggingInit import get_core_logger
from App.schemas.AuthScheema import TokenResponse
from App.api.dependencies.auth import (
     verify_password,
    get_current_user,
    get_password_hash,
    create_access_token,
    create_short_live_token,
    get_current_user_slt
 
)
from App.schemas.AuthScheema import UserResponse
from App.models.UserAuthModel import User,UpdateUser
from App.models.Permissions import Permission
from App.core.Connector import get_db
from datetime import datetime,timedelta
from App.models.PermissionModel import PermissionModel,BulkPermissionModel,RemovePermissionsModel
from App.api.dependencies.permissions import require_permission


admin_router=APIRouter(prefix="/admin_access",tags=["Admin"])
logger = get_core_logger(__name__)


def _is_restore_token(current_user: Dict[str, Any]) -> bool:
    """Return True when the current auth context comes from a short-lived restore token."""
    return (
        current_user.get("token_purpose") == "restore_account"
        or current_user.get("token_type") == "slts"
        or current_user.get("types") == "slts"
    )

 
@admin_router.put(
    "/account/{user_id}",
    response_model=UserResponse,
    summary="Update user account",
    description="Update user information. Admin can update any user, users can only update themselves."
)
async def update_account(
    user_id: int,
    update_data: UpdateUser,
    current_user: Dict[str, Any] = Depends(require_permission(
        [Permission.ADMIN_SETTINGS_UPDATE, Permission.ADMIN_USERS_PROMOTE, Permission.USER_UPDATE_SELF, Permission.USER_UPDATE_PROFILE],
        mode='any',
        bypass_admin=False
    )),
    db: AsyncSession = Depends(get_db)
):
    """
    Update user account.
    
    Who can update:
    1. ✅ Admin → Can update ANY user
    2. ✅ User with ADMIN_SETTINGS_UPDATE or ADMIN_USERS_PROMOTE → Can update ANY user
    3. ✅ User with USER_UPDATE_SELF or USER_UPDATE_PROFILE → Can ONLY update THEMSELVES (limited fields)
    4. ❌ Anyone else → 403 Forbidden
    """
    try:
        repo = UserRepository(db)
        
        # ============================================================
        # ✅ GET USER DATA
        # ============================================================
        current_user_id = current_user.get("id")
        current_user_role = current_user.get("role")
        current_user_perms = current_user.get("permissions", {})
        current_user_email = current_user.get("email")
        
        # ============================================================
        # ✅ GET TARGET USER
        # ============================================================
        target_user = await repo.get_by_id(user_id)
        if not target_user:
            raise HTTPException(404, "User not found")
        
        # ============================================================
        # ✅ PERMISSION CHECKS
        # ============================================================
        is_admin = current_user_role == "admin"
        is_self = current_user_id == user_id
        
        # Can update ANY user?
        has_admin_update_permission = (
            current_user_perms.get("admin.settings.update", False) or 
            current_user_perms.get("admin.users.promote", False)
        )
        
        # Can update SELF only?
        has_self_update_permission = (
            current_user_perms.get("user.update.self", False) or 
            current_user_perms.get("user.update.profile", False)
        )
        
        # ✅ Determine who can update
        if is_admin or has_admin_update_permission:
            can_update_any = True
        elif is_self and has_self_update_permission:
            can_update_any = False
        else:
            raise HTTPException(403, "You don't have permission to update this user's account")
        
        # ============================================================
        # ✅ PREPARE UPDATE DATA
        # ============================================================
        update_dict = update_data.model_dump(exclude_unset=True)
        
        if not update_dict:
            raise HTTPException(400, "No fields to update")
        
        # ============================================================
        # ✅ RESTRICT SENSITIVE FIELDS (user_role, disabled, is_active)
        # ============================================================
        sensitive_fields = ["user_role", "disabled", "is_active"]
        
        # ✅ Only admin OR admin permission can modify sensitive fields
        if not (is_admin or has_admin_update_permission):
            for field in sensitive_fields:
                if field in update_dict:
                    raise HTTPException(
                        403, 
                        f"Only admin or users with admin permissions can update '{field}'"
                    )
        
        # ============================================================
        # ✅ ADMIN SELF-LOCKOUT PROTECTION
        # ============================================================
        if is_admin and is_self:
            if "user_role" in update_dict:
                raise HTTPException(403, "Admin cannot change their own role")
            if "permissions" in update_dict:
                raise HTTPException(403, "Admin cannot change their own permissions")
            if "disabled" in update_dict:
                raise HTTPException(403, "Admin cannot disable themselves")
            if "is_active" in update_dict:
                raise HTTPException(403, "Admin cannot deactivate themselves")
        
        # ============================================================
        # ✅ EMAIL UNIQUENESS
        # ============================================================
        if "email" in update_dict and update_dict["email"] != target_user.email:
            existing = await repo.get_by_email(update_dict["email"])
            if existing and existing.id != user_id:
                raise HTTPException(400, "Email already in use")
        
        # ============================================================
        # ✅ HASH PASSWORD
        # ============================================================
        if "password" in update_dict:
            update_dict["password_hash"] = get_password_hash(update_dict["password"])
            del update_dict["password"]
        
        # ============================================================
        # ✅ UPDATE
        # ============================================================
        updated_user = await repo.update(user_id, update_dict)
        
        if not updated_user:
            raise HTTPException(500, "Failed to update user")
        
        logger.info(f"✅ User {user_id} updated by {current_user_email}")
        
        return UserResponse.model_validate(updated_user)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Account update error: {e}")
        await db.rollback()
        raise HTTPException(500, f"Update failed: {str(e)}")

@admin_router.post(
    "/account/disable/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disable user account",
    description="Disable user account. Admin can Disable any user, users can only Disable themselves with password verification."
    
)
async def disable_account(
    user_id: int,
    password: Optional[str] = Query(None, description="Required for non-admin users"),
    current_user: Dict[str, Any] = Depends(get_current_user),  # ✅ Just get user, do manual checks
    db: AsyncSession = Depends(get_db)
):
    """Disable user account"""
    try:
        repo = UserRepository(db)
        
        # ============================================================
        # ✅ GET USER DATA
        # ============================================================
        current_user_id = current_user.get("id")
        current_user_role = current_user.get("role")
        current_user_perms = current_user.get("permissions", {})
        
        # Ensure permissions is a dict
        if isinstance(current_user_perms, str):
            import json
            try:
                current_user_perms = json.loads(current_user_perms)
            except:
                current_user_perms = {}
        
        # ============================================================
        # ✅ GET TARGET USER
        # ============================================================
        target_user = await repo.get_by_id(user_id)
        if not target_user:
            raise HTTPException(404, "User not found")
        
        if target_user.disabled:
            raise HTTPException(403, "Account already disabled")
        
        # ============================================================
        # ✅ PERMISSION CHECKS
        # ============================================================
        is_admin = current_user_role == "admin"
        is_self = current_user_id == user_id
        
        has_promote_permission = current_user_perms.get("admin.users.promote", False)
        has_restore_permission = current_user_perms.get("admin.users.restore", False)
        has_self_disable = current_user_perms.get("user.disable.self", False)
        
        # ✅ Can disable ANY user?
        can_disable_any = is_admin or has_promote_permission or has_restore_permission
        
        # ✅ Can disable SELF?
        can_disable_self = is_self and has_self_disable
        
        # ============================================================
        # ✅ WHO CAN DISABLE?
        # ============================================================
        
        # CASE 1: Can disable ANY user
        if can_disable_any:
            # ✅ User with permission can disable any user
            await repo.disable_account(user_id)
            logger.info(f"✅ User {current_user_id} disabled user {user_id}")
            return
        
        # CASE 2: Can disable SELF (with password verification)
        if can_disable_self:
            if not password:
                raise HTTPException(400, "Password required for self-disable")
            
            if not verify_password(password, target_user.password_hash):
                raise HTTPException(401, "Incorrect password")
            
            await repo.disable_account(user_id)
            logger.info(f"✅ User {user_id} disabled their own account")
            return
        
        # CASE 3: No permission
        raise HTTPException(403, "Insufficient permissions to disable this account")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Account disable error: {e}")
        await db.rollback()
        raise HTTPException(500, f"Disable failed: {str(e)}")
 
@admin_router.post("/account/enable/{user_id}")
async def enable_account(
    user_id: int,
    password: Optional[str] = Query(None),
    current_user: Dict[str, Any] = Depends(
        require_permission(
            required_permissions=[
                Permission.USER_SELF_ENABLE,
                Permission.ADMIN_USER_ENABLE,
                Permission.ADMIN_USERS_PROMOTE
            ],
            mode="any",
            bypass_admin=False,
            additional_dependency=get_current_user_slt
        )
    ),
    db: AsyncSession = Depends(get_db)
):
    """
    Enable a disabled or inactive user account.
    
    🔒 Who can enable whom:
    1. ✅ Admin (role = admin) → Can enable ANY user
    2. ✅ User with ADMIN_USER_ENABLE → Can enable ANY user
    3. ✅ User with ADMIN_USERS_PROMOTE → Can enable ANY user
    4. ✅ User with USER_SELF_ENABLE → Can ONLY enable THEMSELVES
    5. ✅ SLT Token → Can enable its OWN user
    6. ❌ Anyone else → 403
    """
    try:
        repo = UserRepository(db)
        
        cur_id = current_user.get("id")
        cur_role = current_user.get("role")
        cur_perms = current_user.get("permissions", {})
        is_slt_token = current_user.get("types") == "slts"
        
        is_admin = cur_role == "admin"
        is_self = cur_id == user_id
        
        # ✅ Check permissions
        has_admin_enable = cur_perms.get("admin.user.enable", False)
        has_admin_promote = cur_perms.get("admin.users.promote", False)
        has_self_enable = cur_perms.get("user.self.enable", False)
        
        # ✅ Can enable any user if: admin OR has admin.enable OR has promote
        can_enable_any = is_admin or has_admin_enable or has_admin_promote
        
        # ============================================================
        # ✅ STEP 1: CHECK PERMISSION
        # ============================================================
        
        # CASE 1: SLT Token → Only its OWN user
        if is_slt_token:
            if cur_id != user_id:
                raise HTTPException(403, f"SLT token can only enable user {cur_id}, not {user_id}")
            # ✅ SLT has permission → Continue
        
        # CASE 2: Admin OR user with admin permission → Can enable ANY user
        elif can_enable_any:
            # ✅ Has permission → Continue
            pass
        
        # CASE 3: User with USER_SELF_ENABLE → Can ONLY enable themselves
        elif has_self_enable:
            if not is_self:
                raise HTTPException(403, "You can only enable your own account")
            # ✅ Self has permission → Continue
        
        # CASE 4: No permission
        else:
            raise HTTPException(403, "You don't have permission to enable this account")
        
        # ============================================================
        # ✅ STEP 2: FETCH TARGET USER
        # ============================================================
        target_user = await repo.get_by_id(user_id)
        if not target_user:
            raise HTTPException(404, "User not found")
        
        # ✅ Validate user status (only after permission check)
        if not target_user.disabled and target_user.is_active:
            raise HTTPException(400, "User is already active. No enable needed.")
        
        if target_user.is_deleted:
            raise HTTPException(400, "User is deleted. Use restore endpoint instead.")
        
        # ============================================================
        # ✅ STEP 3: PERFORM ENABLE
        # ============================================================
        
        if is_slt_token:
            success = await repo.full_restore(user_id)
            if not success:
                raise HTTPException(500, "Failed to enable account with SLT token")
            
            return {
                "status": "success",
                "message": f"Account {user_id} enabled via SLT token",
                "user_id": user_id,
                "user_email": target_user.email,
                "enabled_by": "SLT Token"
            }
        
        if is_admin:
            success = await repo.full_restore(user_id)
            if not success:
                raise HTTPException(500, "Failed to enable user account")
            
            return {
                "status": "success",
                "message": f"User {user_id} enabled by admin",
                "user_id": user_id,
                "user_email": target_user.email,
                "enabled_by": "Admin"
            }
        
        if has_admin_enable or has_admin_promote:
            success = await repo.full_restore(user_id)
            if not success:
                raise HTTPException(500, "Failed to enable user account")
            
            return {
                "status": "success",
                "message": f"User {user_id} enabled by user with permission",
                "user_id": user_id,
                "user_email": target_user.email,
                "enabled_by": "User with permission"
            }
        
        if is_self:
            if not password:
                raise HTTPException(400, "Password required for self-enable")
            
            if not verify_password(password, target_user.password_hash):
                raise HTTPException(401, "Incorrect password")
            
            success = await repo.full_restore(user_id)
            if not success:
                raise HTTPException(500, "Failed to enable your account")
            
            return {
                "status": "success",
                "message": "Your account has been enabled successfully",
                "user_id": user_id,
                "user_email": target_user.email,
                "enabled_by": "Self"
            }
        
        raise HTTPException(403, "You don't have permission to enable this account")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Enable account error: {e}")
        await db.rollback()
        raise HTTPException(500, "Failed to enable account")

@admin_router.post(
    "/account/temp_token/{user_id}",
    status_code=status.HTTP_200_OK,
    summary="Make temp token for user to change password and restore accounts",
    description="Make temporary token expire in 2 min for user to restore disabled/deleted account or reset password."
)
async def temp_token_maker(
    response: Response,
    user_id: int,
    current_user: Dict[str, Any] = Depends(require_permission(required_permissions=[
                            Permission.ADMIN_USERS_PROMOTE, 
                            Permission.ADMIN_USERS_RESTORE, 
                            Permission.ADMIN_USERS_DISABLE],
                            mode="any",
                            bypass_admin=True)),
    db: AsyncSession = Depends(get_db),
    cookie_login: bool = False,
    restore_passwd: bool = False,  # ← NEW: Password restore mode
):
    """
    Create temp token for:
    1. Account restoration (disabled/inactive/deleted users)
    2. Password reset (any user)
    
    - restore_passwd=True: Creates token for password reset (bypasses status check)
    - restore_passwd=False: Creates token for account restoration (requires disabled/inactive/deleted)
    """
    try:
        repo = UserRepository(db)
        
        # 1. Check if admin
        if current_user.get("role") != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admin can access this"
            )
        
        # 2. Get target user
        target_user = await repo.get_by_id(user_id)
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # ✅ 3. Check if user needs token
        #    - Password restore: ALWAYS allowed (bypasses status check)
        #    - Account restoration: Only if disabled/inactive/deleted
        
        if restore_passwd:
            # ✅ Password restore mode - bypass all status checks!
            logger.info(f"🔑 Password restore token requested for user {user_id}")
            # Allow even if user is active, not disabled, etc.
            
        else:
            # ✅ Account restoration mode - only for disabled/inactive/deleted
            if not (target_user.disabled or not target_user.is_active or target_user.is_deleted):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="User is already active and valid. No restoration needed."
                )
        
        # ✅ 4. Create the token
        temp_token = await create_short_live_token(user_id, db)
        
        if cookie_login:
            response.set_cookie(
                key="CSO",
                value=temp_token,
                httponly=True,
                secure=False,
                samesite="lax",
                max_age=timedelta(minutes=2),
                path="/",
                domain=None,
            )
            
            return {
                "status": "success",
                "message": "Temporary token created and set as cookie",
                "user_id": target_user.id,
                "user_name": target_user.name,
                "purpose": "password_restore" if restore_passwd else "account_restoration",
                "expires_in_minutes": 2
            }
        else:
            return {
                "status": "success",
                "message": "Temporary token created",
                "user_id": target_user.id,
                "user_name": target_user.name,
                "user_status": {
                    "disabled": target_user.disabled,
                    "is_active": target_user.is_active,
                    "is_deleted": target_user.is_deleted
                } if not restore_passwd else None,
                "purpose": "password_restore" if restore_passwd else "account_restoration",
                "temp_token": temp_token,
                "expires_in_minutes": 2
            }
            
 
    except Exception as e:
        logger.error(f"Temp token error: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create temp token: {str(e)}"
        )


@admin_router.post(
    "/reset-auto-kill",
    status_code=status.HTTP_200_OK,
    summary="Reset Auto-Kill Switch",
    description="Allows administrators to reset the system from safety mode after an internal error."
)
async def reset_auto_kill(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Reset the auto-kill protection flag"""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can reset the safety mode"
        )
    
    request.app.state.auto_kill_enabled = False
    logger.info(f"System safety mode reset by admin: {current_user.get('email')}")
    return {"status": "success", "message": "System safety mode has been reset."}

@admin_router.delete(
    "/account/{user_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete account",
    description="If normal user delete his accoutn but need password if admin can delete any user account"
)
async def delete_account(
    user_id: int,
    password: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(
        require_permission(
            required_permissions=[
                Permission.USER_DELETE_SELF,
                Permission.ADMIN_USERS_DELETE,
                Permission.ADMIN_USERS_PROMOTE
            ],
            mode="any",
            bypass_admin=False
        )
    ),
    db: AsyncSession = Depends(get_db)
):
    try:
        repo = UserRepository(db)
        
        cur_role = current_user.get("role")
        cur_id = current_user.get("id")
        cur_perms = current_user.get("permissions", {})
        
        is_self_deletion = cur_id == user_id
        is_admin = cur_role == "admin"
        
        # ✅ Check permissions
        has_admin_delete = cur_perms.get("admin.users.delete", False)
        has_admin_promote = cur_perms.get("admin.users.promote", False)
        
        # ✅ Can delete any user if: admin OR has admin_delete OR has admin_promote
        can_delete_any = is_admin or has_admin_delete or has_admin_promote
        
        # ============================================================
        # ✅ STEP 1: CHECK PERMISSION FIRST (NO USER STATUS CHECK!)
        # ============================================================
        
        # CASE 1: Can delete ANY user
        if can_delete_any:
            # ✅ Now we can safely check the user
            target_user = await repo.get_by_id(user_id)
            
            if not target_user:
                raise HTTPException(404, "User not found")
            
            if target_user.is_deleted:
                raise HTTPException(400, "User is already deleted")
            
            if is_self_deletion:
                raise HTTPException(403, "You cannot delete your own account")
            
            success = await repo.delete_account(user_id)
            if not success:
                raise HTTPException(500, "Failed to delete user account")
            
            return {
                "status": "success",
                "message": f"User {user_id} deleted by {current_user.get('email')}"
            }
        
        # ============================================================
        # CASE 2: Self-deletion (normal user)
        # ============================================================
        if is_self_deletion:
            target_user = await repo.get_by_id(user_id)
            
            if not target_user:
                raise HTTPException(404, "User not found")
            
            if target_user.is_deleted:
                raise HTTPException(400, "User is already deleted")
            
            if not password:
                raise HTTPException(400, "Password required for self-deletion")
            
            if not verify_password(password, target_user.password_hash):
                raise HTTPException(401, "Incorrect password")
            
            success = await repo.delete_account(user_id)
            if not success:
                raise HTTPException(500, "Failed to delete your account")
            
            return {
                "status": "success",
                "message": "Your account has been soft deleted"
            }
        
        # ============================================================
        # CASE 3: No permission (DON'T reveal anything!)
        # ============================================================
        # ✅ DON'T check user status at all — just return 403
        raise HTTPException(403, "You don't have permission to delete this account")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete account error: {e}")
        await db.rollback()
        raise HTTPException(500, f"Failed to delete user due to: {str(e)}")
 
@admin_router.post(
    "/account/restore/{user_id}",
    status_code=status.HTTP_200_OK,
    summary="Restore deleted/disabled account",
    description="Restore a soft-deleted or disabled account. Admin can restore any user. Users can restore themselves only with SLT token."
)
async def restore_account(
    user_id: int,
    current_user: Dict[str, Any] = Depends(require_permission(
            required_permissions=[
                Permission.ADMIN_USERS_RESTORE,
                Permission.ADMIN_USERS_PROMOTE
            ],
            mode="any",
            bypass_admin=False,
            additional_dependency=get_current_user_slt
        )),
    db: AsyncSession = Depends(get_db),
):
    """
    Restore a deleted or disabled user account.
    
    🔒 Who can restore:
    1. ✅ Admin (role = admin) → Can restore any user
    2. ✅ User with ADMIN_USERS_RESTORE → Can restore any user
    3. ✅ User with ADMIN_USERS_PROMOTE → Can restore any user
    4. ✅ SLT Token → Bypasses ALL permission checks (can restore its own user)
    5. ❌ Anyone else → 403
    """
    try:
        repo = UserRepository(db)
        
        # ============================================================
        # ✅ GET CURRENT USER DATA
        # ============================================================
        cur_role = current_user.get("role")
        cur_id = current_user.get("id")
        cur_perms = current_user.get("permissions", {})
        is_slt_token = current_user.get("types") == "slts"
        is_admin = cur_role == "admin"
        
        # ============================================================
        # ✅ CHECK PERMISSIONS (But SLT bypasses everything!)
        # ============================================================
        has_restore_permission = cur_perms.get("admin.users.restore", False)
        has_promote_permission = cur_perms.get("admin.users.promote", False)
        can_restore_any = is_admin or has_restore_permission or has_promote_permission or is_slt_token
        
        logger.info(f"🔍 is_admin: {is_admin}")
        logger.info(f"🔍 has_restore_permission: {has_restore_permission}")
        logger.info(f"🔍 has_promote_permission: {has_promote_permission}")
        logger.info(f"🔍 can_restore_any: {can_restore_any}")
        logger.info(f"🔍 is_slt_token: {is_slt_token}")
        
        # ============================================================
        # ✅ STEP 1: SLT TOKEN BYPASS (Highest Priority!)
        # ============================================================
        if is_slt_token:
            slt_user_id = current_user.get("id")
            
            # SLT token can ONLY restore its OWN user
            if not slt_user_id == user_id:
                logger.warning(f"❌ SLT token {slt_user_id} tried to restore user {user_id}")
                raise HTTPException(
                    403,
                    f"SLT token can only restore user {slt_user_id}, not {user_id}"
                )
            
            # ✅ SLT token bypasses ALL checks - proceed directly to restore!
            logger.info(f"✅ SLT token bypass - restoring user {user_id}")
            
            # Get target user
            target_user = await repo.get_by_id(user_id)
            if not target_user:
                raise HTTPException(404, "User not found")
            
            # Check if user needs restoration
            if not target_user.is_deleted and not target_user.disabled and target_user.is_active:
                raise HTTPException(400, "User is already active. No restoration needed.")
            
            # Perform restore
            success = await repo.restore_deleted(user_id)
            if not success:
                success = await repo.restore_disable(user_id)
            
            if not success:
                raise HTTPException(500, "Failed to restore account with SLT token")
            
            logger.info(f"✅ SLT token restored user {user_id}")
            return {
                "status": "success",
                "message": f"Account {user_id} restored via SLT token",
                "user_id": user_id,
                "user_email": target_user.email,
                "restored_by": "SLT Token"
            }
        
        # ============================================================
        # ✅ STEP 2: NORMAL PERMISSION CHECK (Non-SLT users)
        # ============================================================
        
        # Non-SLT users MUST have permission
        if not can_restore_any:
            logger.warning(f"❌ User {current_user.get('email')} tried to restore without permission")
            raise HTTPException(403, "You don't have permission to restore accounts")
        
        # ============================================================
        # ✅ STEP 3: FETCH TARGET USER
        # ============================================================
        target_user = await repo.get_by_id(user_id)
        
        if not target_user:
            raise HTTPException(404, "User not found")
        
        # ✅ Check if user actually needs restoration
        if not target_user.is_deleted and not target_user.disabled and target_user.is_active:
            raise HTTPException(400, "User is already active. No restoration needed.")
        
        logger.info(f"🔍 target_user status: disabled={target_user.disabled}, is_active={target_user.is_active}, is_deleted={target_user.is_deleted}")
        
        # ============================================================
        # ✅ STEP 4: PERFORM RESTORE (Admin or user with permission)
        # ============================================================
        success = False
        
        if target_user.is_deleted:
            success = await repo.restore_deleted(user_id)
        
        if not success:
            success = await repo.restore_disable(user_id)
        
        if not success:
            raise HTTPException(500, "Failed to restore user account")
        
        restored_by = "Admin" if is_admin else "User with permission"
        logger.info(f"✅ {restored_by} restored user {user_id}")
        
        return {
            "status": "success",
            "message": f"User {user_id} restored by {restored_by}",
            "user_id": user_id,
            "user_email": target_user.email,
            "restored_by": restored_by
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Restore account error: {e}")
        await db.rollback()
        raise HTTPException(500, f"Failed to restore account: {str(e)}")

@admin_router.put(
    "/account/password/{user_id}",
    status_code=status.HTTP_200_OK,
    summary="Update user password",
    description="Admin can update any user password. Normal users update their own password. SLT token can only update its own user's password."
)
async def update_password(
    user_id: int,
    new_password: str,
    current_user: Dict[str, Any] = Depends(
        require_permission(
            required_permissions=[
                Permission.USER_UPDATE_PASSWORD,
                Permission.ADMIN_ANY_PASSWORD_UPDATE
            ],
            mode="any",
            bypass_admin=False,
            additional_dependency=get_current_user_slt
        )
    ),
    old_password: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    ## Change password for user.
    
    🔒 Who can update:
    1. ✅ SLT Token → Can update its OWN user's password (bypasses old password)
    2. ✅ Admin → Can update ANY user's password (no old password needed)
    3. ✅ User with ADMIN_ANY_PASSWORD_UPDATE → Can update ANY user's password
    4. ✅ User with USER_UPDATE_PASSWORD → Can update THEIR OWN password (with old password)
    5. ❌ Anyone else → 403
    """
    try:
        repo = UserRepository(db)
        
        cur_role = current_user.get("role")
        cur_id = current_user.get("id")
        is_slt_token = current_user.get("types") == "slts"
        slt_user_id = current_user.get("user_id")
        cur_perms = current_user.get("permissions", {})
        
        # ✅ Check permissions
        has_admin_any = cur_perms.get("admin.anyuser.password.update", False)
        has_user_update = cur_perms.get("user.update.password", False)
        
        target_user = await repo.get_by_id(user_id)
        if not target_user:
            raise HTTPException(404, "User not found")
        
        is_self_update = cur_id == user_id
        is_admin = cur_role == "admin"
        
        # ✅ Can update ANY user
        can_update_any = is_admin or has_admin_any
        
        # ✅ Can update SELF (with old password)
        can_update_self = has_user_update and is_self_update
        
        logger.info(f"🔍 is_admin: {is_admin}")
        logger.info(f"🔍 has_admin_any: {has_admin_any}")
        logger.info(f"🔍 has_user_update: {has_user_update}")
        logger.info(f"🔍 can_update_any: {can_update_any}")
        logger.info(f"🔍 can_update_self: {can_update_self}")
        logger.info(f"🔍 is_slt_token: {is_slt_token}")
        logger.info(f"🔍 is_self_update: {is_self_update}")
        
        # ============================================================
        # CASE 1: SLT TOKEN (Only for its OWN user!)
        # ============================================================
        if is_slt_token:
            if slt_user_id != user_id:
                raise HTTPException(
                    403,
                    f"SLT token can only update password for user {slt_user_id}, not {user_id}"
                )
            
            new_hash = get_password_hash(new_password)
            success = await repo.update_password_hash(user_id, new_hash)
            if not success:
                raise HTTPException(500, "Failed to update password with SLT token")
            
            return {
                "status": "success",
                "message": f"Password updated via SLT token for user {user_id}",
                "user_id": user_id,
                "user_email": target_user.email,
                "updated_by": "SLT Token"
            }
        
        # ============================================================
        # CASE 2: UPDATE ANY USER (Admin OR has_admin_any)
        # ============================================================
        if can_update_any:
            new_hash = get_password_hash(new_password)
            success = await repo.update_password_hash(user_id, new_hash)
            if not success:
                raise HTTPException(500, "Failed to update password")
            
            updated_by = "Admin" if is_admin else "User with admin permission"
            return {
                "status": "success",
                "message": f"Password updated by {updated_by} for user {user_id}",
                "user_id": user_id,
                "user_email": target_user.email,
                "updated_by": updated_by
            }
        
        # ============================================================
        # CASE 3: SELF UPDATE (Requires old password)
        # ============================================================
        if can_update_self:
            if not old_password:
                raise HTTPException(400, "Old password is required to change your password")
            
            if not verify_password(old_password, target_user.password_hash):
                raise HTTPException(401, "Incorrect old password")
            
            new_hash = get_password_hash(new_password)
            success = await repo.update_password_hash(user_id, new_hash)
            if not success:
                raise HTTPException(500, "Failed to update your password")
            
            return {
                "status": "success",
                "message": "Your password has been updated successfully",
                "user_id": user_id,
                "user_email": target_user.email,
                "updated_by": "Self"
            }
        
        # ============================================================
        # CASE 4: NO PERMISSION
        # ============================================================
        raise HTTPException(
            403,
            "You don't have permission to update this user's password"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update password error: {e}")
        await db.rollback()
        raise HTTPException(500, f"Failed to update password: {str(e)}")

@admin_router.get("/get_all_permissions")
async def get_all_permissions(
    current_user: Dict[str, Any] = Depends(require_permission(required_permissions=[Permission.ADMIN_USERS_PROMOTE],mode="any",bypass_admin=False)),  # ← Normal auth
    db=Depends(get_db)
):
    """
    Get all available permissions.
    Admin only.
    """
    try:
        return [{"name": p.name, "value": p.value} for p in Permission]
    except Exception as e:
        logger.error(f"Error getting permissions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving permissions: {str(e)}"
        )

# App/api/v1/Admin.py

@admin_router.post("/set_permissions")
async def setPermissions(
    pm: PermissionModel,
    current_user: Dict[str, Any] = Depends(
        require_permission(
            required_permissions=[Permission.ADMIN_USERS_PROMOTE],
            bypass_admin=False
        )
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Set permissions for a user.
    
    🔒 Who can set permissions:
    1. ✅ User with ADMIN_USERS_PROMOTE → Can update ANY user's permissions
    2. ❌ Anyone else → 403 (handled by require_permission)
    
    ⚠️ Users CANNOT update their OWN permissions!
    """
    
    logger.info(f"🔍 current_user: id={current_user.get('id')}, email={current_user.get('email')}, role={current_user.get('role')}")
    logger.info(f"🔍 current_user permissions: {current_user.get('permissions', {})}")
    logger.info(f"🔍 pm.user_id: {pm.user_id}")
    
    try:
        repo = UserRepository(db)
        uid = current_user.get("id")
        
        # ============================================================
        # ✅ SECURITY: Users cannot update their own permissions!
        # ============================================================
        if uid == pm.user_id:
            logger.warning(f"❌ User {current_user.get('email')} tried to update their own permissions")
            raise HTTPException(403, "You cannot update your own permissions")
        
        # ============================================================
        # ✅ Get target user
        # ============================================================
        target = await repo.get_by_id(pm.user_id)
        if not target:
            raise HTTPException(404, f"User {pm.user_id} not found")
        
        # ============================================================
        # ✅ Update permissions (require_permission already verified access)
        # ============================================================
        logger.info(f"✅ User {current_user.get('email')} (has promote) updating permissions for {pm.user_id}")
        updated = await repo.set_permissions(user_id=pm.user_id, permissions=pm.permissions)
        
        return {
            "status": "success",
            "message": f"Permissions updated for user {pm.user_id}",
            "user_id": pm.user_id,
            "permissions": updated.permissions
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting permissions: {e}")
        await db.rollback()
        raise HTTPException(500, f"Error: {str(e)}")

@admin_router.post("/set_permissions_bulk")
async def setPermissionsBulk(
    bulk_pm: BulkPermissionModel,
    current_user: Dict[str, Any] = Depends(
        require_permission([Permission.ADMIN_USERS_PROMOTE], bypass_admin=False)
    ),
    db: AsyncSession = Depends(get_db),
    replace_all: bool = False,
):
    """
    Set permissions for multiple users in bulk.
    """
    
    logger.info(f"🔍 Bulk permission update initiated by: id={current_user.get('id')}, email={current_user.get('email')}")
    logger.info(f"🔍 Target users: {[p.user_id for p in bulk_pm.all_user_permissions]}")
    logger.info(f"🔍 Mode: {'REPLACE ALL' if replace_all else 'MERGE'}")
    
    repo = UserRepository(db)
    
    try:
        # ============================================================
        # ✅ PERMISSION CHECK
        # ============================================================
        has_promote = current_user.get("permissions", {}).get("admin.users.promote", False)
        
        if not has_promote:
            logger.warning(f"❌ User {current_user.get('email')} tried to set permissions without promote permission")
            raise HTTPException(403, "You don't have permission to set permissions. Need admin.users.promote.")
        
        # ============================================================
        # ✅ VALIDATE: All users exist
        # ============================================================
        user_ids = [p.user_id for p in bulk_pm.all_user_permissions]
        
        existing_users = await repo.get_by_ids(user_ids)
        existing_user_ids = {user.id for user in existing_users}
        
        missing_users = [uid for uid in user_ids if uid not in existing_user_ids]
        if missing_users:
            raise HTTPException(404, f"Users not found with IDs: {missing_users}")
        
        # ============================================================
        # ✅ PREVENT SELF-UPDATE (Security!)
        # ============================================================
        current_user_id = current_user.get("id")
        if current_user_id in user_ids:
            logger.warning(f"❌ User {current_user.get('email')} tried to update their own permissions in bulk")
            raise HTTPException(403, "You cannot update your own permissions")
        
        # ============================================================
        # ✅ PROCESS: Update all permissions
        # ============================================================
        updated_users = []
        
        for perm_update in bulk_pm.all_user_permissions:
            try:
                if replace_all:
                    updated = await repo.replace_all_permissions(
                        perm_update.user_id, 
                        perm_update.permissions
                    )
                    operation = "replaced"
                else:
                    updated = await repo.set_permissions(
                        perm_update.user_id, 
                        perm_update.permissions
                    )
                    operation = "merged"
                
                updated_users.append({
                    "user_id": perm_update.user_id,
                    "permissions": updated.permissions,
                    "status": "success",
                    "operation": operation
                })
                
                logger.info(f"✅ {operation.upper()} permissions for user {perm_update.user_id}")
                
            except Exception as e:
                logger.error(f"❌ Failed to update user {perm_update.user_id}: {str(e)}")
                raise HTTPException(500, f"Failed to update user {perm_update.user_id}: {str(e)}")
        
        await db.commit()
        
        return {
            "status": "success",
            "message": f"Permissions {('replaced' if replace_all else 'merged')} for {len(updated_users)} users",
            "mode": "replace_all" if replace_all else "merge",
            "updated_users": updated_users,
            "total_processed": len(bulk_pm.all_user_permissions),
            "total_success": len(updated_users),
            "total_failed": 0
        }
        
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        logger.error(f"❌ Error in bulk permission update: {e}")
        await db.rollback()
        raise HTTPException(500, f"Error in bulk permission update: {str(e)}")

@admin_router.get("/users/permissions")
async def getUsersPermissions(
    user_id: Optional[int] = Query(None, description="Specific user ID to get permissions for"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum records to return"),
    include_user_info: bool = Query(False, description="Include user email and name"),
    current_user: Dict[str, Any] = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get user permissions with pagination.
    
    🔒 Rules:
    1. ✅ No user_id → Get OWN permissions (any authenticated user)
    2. ✅ User_id provided → Get that user's permissions (admin/promote only)
    3. ❌ Normal user trying to see others → 403
    """
    try:
        repo = UserRepository(db)
        
        current_user_id = current_user.get("id")
        current_user_perms = current_user.get("permissions", {})
        current_user_email = current_user.get("email")
        
        # ✅ Check if user is admin or has permission to view others
        has_promote = current_user_perms.get("admin.users.promote", False)
        has_settings_view = current_user_perms.get("admin.settings.view", False)
        is_admin = current_user.get("role") == "admin"
        
        can_view_any = is_admin or has_promote or has_settings_view
        
        # ============================================================
        # ✅ Determine which user to fetch
        # ============================================================
        
        # If no user_id provided → Get OWN permissions
        if user_id is None:
            target_user_id = current_user_id
            is_viewing_self = True
            logger.info(f"🔍 User {current_user_email} viewing their own permissions")
        
        # If user_id provided
        else:
            # Check if user is viewing themselves
            is_viewing_self = user_id == current_user_id
            
            # If viewing others, must have permission
            if not is_viewing_self and not can_view_any:
                logger.warning(f"❌ User {current_user_email} tried to view permissions for user {user_id} without permission")
                raise HTTPException(
                    403,
                    "You don't have permission to view other users' permissions. Need admin.users.promote or admin.settings.view."
                )
            
            target_user_id = user_id
            logger.info(f"🔍 User {current_user_email} viewing permissions for user {target_user_id}")
        
        # ============================================================
        # ✅ Fetch permissions
        # ============================================================
        result = await repo.get_user_permission_db(
            user_id=target_user_id,
            skip=skip,
            limit=limit,
            include_user_info=include_user_info
        )
        
        return {
            "status": "success",
            "data": result
        }
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting permissions: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@admin_router.delete("/remove_permissions")
async def removePermissions(
    data: RemovePermissionsModel,
    current_user: Dict[str, Any] = Depends(require_permission(
        required_permissions=[Permission.ADMIN_USERS_PROMOTE],
        mode='any',
        bypass_admin=False
    )),
    db: AsyncSession = Depends(get_db),
):
    """
    Remove permissions from a user.
    
    Rules:
    - Admin can delete ANYONE's permissions
    - Normal user with ADMIN_USERS_PROMOTE can delete THEIR OWN permissions
    - Normal user without promote cannot delete anything
    """
    try:
        repo = UserRepository(db)
        
        # ============================================================
        # ✅ GET CURRENT USER DATA
        # ============================================================
        current_user_id = current_user.get("id")
        current_user_role = current_user.get("role")
        current_user_perms = current_user.get("permissions", {})
        current_user_email = current_user.get("email")
        
        # ============================================================
        # ✅ CHECK TARGET USER EXISTS
        # ============================================================
        target = await repo.get_by_id(data.user_id)
        if not target:
            raise HTTPException(404, f"User {data.user_id} not found")
        
        # ============================================================
        # ✅ PERMISSION LOGIC
        # ============================================================
        is_self = current_user_id == data.user_id
        is_admin = current_user_role == "admin"
        has_promote = current_user_perms.get("admin.users.promote", False)
        
        # ✅ Determine if user can delete
        if is_admin:
            can_delete = True
            logger.info(f"✅ Admin {current_user_email} deleting permissions for {target.email}")
        elif is_self and has_promote:
            can_delete = True
            logger.info(f"✅ User {current_user_email} deleting their own permissions")
        else:
            logger.warning(f"❌ User {current_user_email} tried to delete permissions for {target.email}")
            raise HTTPException(403, "You don't have permission to delete permissions")
        
        # ============================================================
        # ✅ SAFETY CHECKS
        # ============================================================
        if is_admin and is_self:
            raise HTTPException(403, "Admin cannot delete their own permissions")
        
        if is_self and not is_admin:
            if data.permission_keys and "admin.users.promote" in data.permission_keys:
                raise HTTPException(403, "You cannot remove your own admin.users.promote permission")
        
        # ============================================================
        # ✅ CHECK PERMISSIONS BEFORE DELETION
        # ============================================================
        target_perms = target.permissions or {}
        if isinstance(target_perms, str):
            import json
            try:
                target_perms = json.loads(target_perms)
            except:
                target_perms = {}
        
        logger.info(f"🔍 Target permissions BEFORE: {target_perms}")
        
        # ============================================================
        # ✅ PERFORM DELETION
        # ============================================================
        if data.remove_all:
            if not target_perms:
                raise HTTPException(404, "User has no permissions to delete")
            
            updated = await repo.remove_all_permissions(data.user_id)
            message = f"All permissions removed for user {target.email}"
            
        elif data.permission_keys:
            # ✅ Check which keys exist
            existing_keys = []
            missing_keys = []
            
            for key in data.permission_keys:
                if key in target_perms:
                    existing_keys.append(key)
                else:
                    missing_keys.append(key)
            
            # If no keys exist, return 404
            if not existing_keys:
                raise HTTPException(
                    404,
                    f"Permissions not found: {', '.join(missing_keys)}"
                )
            
            # ✅ Delete only existing keys
            updated = await repo.remove_permissions(data.user_id, existing_keys)
            message = f"Permissions removed for user {target.email}: {existing_keys}"
            
            # Add warning about missing keys
            if missing_keys:
                message += f" (Warning: {', '.join(missing_keys)} not found)"
            
        else:
            raise HTTPException(400, "Either permission_keys or remove_all must be provided")
        
        # ============================================================
        # ✅ CHECK PERMISSIONS AFTER DELETION
        # ============================================================
        logger.info(f"🔍 Target permissions AFTER: {updated.permissions}")
        
        return {
            "status": "success",
            "message": message,
            "user_id": data.user_id,
            "permissions": updated.permissions,
            "removed_count": len(existing_keys) if data.permission_keys else "all"
        }
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"Error removing permissions: {e}")
        await db.rollback()
        raise HTTPException(500, f"Error: {str(e)}")
    
    