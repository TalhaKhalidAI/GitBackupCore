from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
from enum import Enum


class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"


# ==================== LOGIN MODELS ====================

class LoginRequest(BaseModel):
    """Login request model"""
    username: str = Field(..., min_length=1, description="Username or email")
    password: str = Field(..., min_length=1, description="User password")


class LoginResponse(BaseModel):
    """Login response model"""
    access_token: str
    token_type: str = "bearer"
    user: "UserData"


# ==================== SIGNUP MODELS ====================

class SignupRequest(BaseModel):
    """Signup request model"""
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_]+$")
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=100)
    full_name: Optional[str] = Field(None, max_length=100)
    
    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain at least one digit')
        special_chars = '!@#$%^&*()_+-=[]{}|;:,.<>?`~'
        if not any(c in special_chars for c in v):
            raise ValueError('Password must contain at least one special character')
        return v


class SignupResponse(BaseModel):
    """Signup response model"""
    message: str = "User created successfully"
    user: "UserData"


# ==================== USER DATA MODELS ====================

class UserData(BaseModel):
    """User data model (returned in responses)"""
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    user_role: str = "user"
    is_active: bool = True
    disabled: bool = False
    
    class Config:
        from_attributes = True


class UserUpdateRequest(BaseModel):
    """User update request model"""
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(None, max_length=100)
    user_role: Optional[UserRole] = None


class ChangePasswordRequest(BaseModel):
    """Change password request model"""
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=100)
    
    @field_validator('new_password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain at least one digit')
        special_chars = '!@#$%^&*()_+-=[]{}|;:,.<>?`~'
        if not any(c in special_chars for c in v):
            raise ValueError('Password must contain at least one special character')
        return v


class ResetPasswordRequest(BaseModel):
    """Reset password request model (admin only)"""
    new_password: str = Field(..., min_length=8, max_length=100)
    
    @field_validator('new_password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not any(c.islower() for c in v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not any(c.isdigit() for c in v):
            raise ValueError('Password must contain at least one digit')
        special_chars = '!@#$%^&*()_+-=[]{}|;:,.<>?`~'
        if not any(c in special_chars for c in v):
            raise ValueError('Password must contain at least one special character')
        return v


# ==================== RESPONSE MODELS ====================

class MessageResponse(BaseModel):
    """Generic message response"""
    message: str


class ErrorResponse(BaseModel):
    """Error response model"""
    detail: str


class UserListResponse(BaseModel):
    """User list response"""
    users: list[UserData]
    total: int
    skip: int
    limit: int


# Update forward references
LoginResponse.model_rebuild()
SignupResponse.model_rebuild()
