# App/api/v1/UserAuth.py - PROFESSIONAL REFACTORED VERSION

from fastapi import APIRouter, Depends, HTTPException, status, Query, Body,Response
from App.schemas.AuthScheema import TokenResponse
from sqlalchemy.ext.asyncio import AsyncSession
from App.core.LoggingInit import get_core_logger
from App.core.Connector import get_db
from App.models.UserAuthModel import User,UpdateUser,LoginUser
from App.schemas.AuthScheema import UserResponse
from App.api.dependencies.auth import (
    authenticate_user,
    create_access_token,
    create_refresh_token,

    get_password_hash,

    validate_password_strength
)
from typing import Optional
from App.repository.UserRepository import UserRepository
from App.core.settings import settings
# Initialize logger
logger = get_core_logger(__name__)

# Pydantic Models (Request/Response schemas)
 




# Create router
router = APIRouter(prefix="/basic_auth", tags=["Authentication"])

@router.post(
    "/login",
    status_code=status.HTTP_200_OK,
    summary="User login",
    description="Authenticate user with email and password"
)
async def login(
    res: Response,
    form_data: LoginUser,
    db: AsyncSession = Depends(get_db),
    cookie_login: Optional[bool] = False,
):
    """
    Login endpoint supporting OAuth2 password flow.
    Returns access and refresh tokens.
    """
    try:
        # Get password from SecretStr
        password = form_data.password.get_secret_value()
        
        # Authenticate user
        user = await authenticate_user(form_data.username, password, db)
         
        if not user:
            logger.warning(f"Failed login attempt for email: {form_data.username}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password or account is not there or disable!\n\nContact admin",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # ✅ CREATE TOKENS FIRST - BEFORE ANY CONDITION!
        
        access_token = create_access_token(
            data={
                "type":"token",
                "sub": user["email"],
                "user_id": user["id"],
                "name": user["name"],
                "role": user["role"]
            }
        )
        
        refresh_token = create_refresh_token(
            data={
                "type":"rf_token",
                "sub": user["email"],
                "user_id": user["id"]
            }
        )
        
        expires_in_seconds = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        
        logger.info(f"User logged in successfully: {user['email']}")
        
        # ========== COOKIE MODE ==========
        if cookie_login:
            # ✅ Set access token cookie
            res.set_cookie(
                key="CSO",
                value=access_token,  # ✅ Now defined!
                httponly=True,
                secure=False,
                samesite="lax",
                max_age=expires_in_seconds,
                path="/",
                domain=None,
                
            )
            
            
            
            # ✅ Return user data (tokens in cookies)
            return {
                "token":access_token,
                "status": "success",
                "message": "Logged in successfully",
                "user": {
                    "id": user["id"],
                    "email": user["email"],
                    "name": user["name"],
                    "role": user["role"]
                }
            }
        
        # ========== JSON MODE ==========
        else:
            return TokenResponse(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_in=expires_in_seconds
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during login"
        )
    
# App/api/v1/UserAuth.py - FIXED VERSION
@router.post(
    "/signup",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register new user",
    description="Create a new user account"
)
async def signup(
    
    user_data: User,
    db: AsyncSession = Depends(get_db),
   
):
    """Register a new user"""
    try:
        repo = UserRepository(db)
        
        # Check if user exists
        existing_user = await repo.get_by_email(user_data.email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        
        # Create user data dictionary
        user_dict = user_data.model_dump()
        
        # Validate and hash password
        if "password" not in user_dict:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password is required"
            )
        
        # Validate password strength
        if not validate_password_strength(user_dict["password"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters with uppercase, lowercase, digit, and special character"
            )
        
        user_dict["password_hash"] = get_password_hash(user_dict["password"])
        del user_dict["password"]  # Remove plain password
        
        # Set default values
        user_dict["user_role"] = "user"
        user_dict["is_active"] = True
        user_dict["permissions"] = {
            # ===== USER SELF-MANAGEMENT =====
            "user.view.self": True,
            "user.update.self": True,
            "user.update.email": True,
            "user.update.password": True,
            "user.update.profile": True,
            "user.delete.self": True,
            "user.history.view": True,
            "user.history.delete": True,
            "user.self.enable": True,
            "user.disable.self": True,
        }
        
        user = await repo.create(user_dict)
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create user"
            )
        
        logger.info(f"New user registered: {user.email}")
        
        # FIX: Convert SQLAlchemy model to dictionary before validation
        user_dict_response = {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "profile_pic": user.profile_pic or None,  # Ensure None if empty
            "permissions":{ 
            "user.view.self": True,
            "user.update.self": True,
            "user.update.email": True,
            "user.update.password": True,
            "user.update.profile": True,
            "user.delete.self": True,
            "user.history.view": True,
            "user.history.delete": True,
            "user.self.enable": True,
            "user.disable.self": True,
            }
        }
        
        # Validate with UserResponse model
        return UserResponse(**user_dict_response)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Signup error: {e}")
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(e)}"
        )
