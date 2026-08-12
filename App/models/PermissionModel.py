from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict,List
from enum import Enum
from App.api.dependencies.permissions import Permission

# ============================================================
# PERMISSION ENUM (Reuse from your existing Permission enum)
# ============================================================

 
class PermissionModel(BaseModel):
    """Model for updating user permissions."""
    
    user_id: int = Field(
        ..., 
        description="User ID to assign permissions to",
        gt=0,
        example=123
    )
    
    permissions: Dict[str, bool] = Field(
        ...,
        description="User permissions dict (permission name: True/False)",
        example={"user.view.self": True, "user.update.self": False, "user.delete.self": False}
    )
    
    @field_validator("permissions")
    @classmethod
    def validate_permissions(cls, v: Dict[str, bool]) -> Dict[str, bool]:
        """Validate that permission names are valid and values are booleans."""
        
        # ✅ Get all valid permission names from your existing Permission enum
       
        valid_permissions = {p.value for p in Permission}
        
        for key, value in v.items():
            # Check if permission name is valid
            if key not in valid_permissions:
                raise ValueError(
                    f"Invalid permission: '{key}'. "
                    f"Valid permissions: {', '.join(sorted(valid_permissions)[:10])}..."
                )
            
            # Check if value is boolean (Pydantic already does this, but explicit check)
            if not isinstance(value, bool):
                raise ValueError(f"Permission '{key}' must be boolean, got {type(value).__name__}")
        
        return v
    
    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: int) -> int:
        """Ensure user_id is positive."""
        if v <= 0:
            raise ValueError(f"user_id must be positive, got {v}")
        return v


# ============================================================
# ALSO: Model for Setting Multiple Users' Permissions
# ============================================================

class BulkPermissionModel(BaseModel):
    all_user_permissions: List[PermissionModel] = Field(
        ...,
        description="List of user permissions to update",
        example=[
            {"user_id": 1, "permissions": {"user.update.self": True, "user.update.email": True}},
            {"user_id": 2, "permissions": {"user.view.any": True, "user.enable": False}},
        ]
    )
    
    @field_validator("all_user_permissions")
    @classmethod
    def validate_unique_users(cls, v: List[PermissionModel]) -> List[PermissionModel]:
        """Ensure no duplicate user IDs."""
        user_ids = [user.user_id for user in v]
        if len(user_ids) != len(set(user_ids)):
            raise ValueError("Duplicate user IDs found in the list")
        return v
# ============================================================
# ALSO: Model for Getting User Permissions (Response)
# ============================================================

class UserPermissionsResponse(BaseModel):
    """Response model for user permissions."""
    
    user_id: int
    user_email: str
    user_name: str
    permissions: Dict[str, bool]
    tier: Optional[str] = None
    
    class Config:
        from_attributes = True

class RemovePermissionsModel(BaseModel):
    user_id: int = Field(..., description="User ID")
    permission_keys: Optional[List[str]] = Field(
        None, 
        description="List of permission keys to remove"
    )
    remove_all: bool = Field(
        False, 
        description="If True, removes ALL permissions"
    )