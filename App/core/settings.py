# settings.py - SQLite version (configured from .env)
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr, Field, field_validator
from typing import Any
import os


class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    REPO_PATH:str=Field(...,description="path dir for repo to store all  repos data git init repo")
    
    # Security (REQUIRED)
    SECRET_KEY: SecretStr = Field(
        description="Secret key for JWT token signing"
    )
    
    ALGORITHM: str = Field(
        description="JWT algorithm (HS256, HS384, HS512, RS256, etc.)"
    )
    
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        description="Access token expiration time in minutes"
    )
    
    # Kill Switch / Maintenance Mode
    KILL_SWITCH_ENABLED: bool = Field(
        default=False,
        description="Global kill switch to disable the API (Maintenance Mode)"
    )
    
    # Rate Limiting
    RATE_LIMIT_DEFAULT: str = Field(
        description="Default rate limit for all endpoints (e.g., 100/minute)"
    )
    
    # SQLite Configuration
    SQLITE_DATABASE_URL: str = Field(
        description="SQLite database URL"
    )
    
    # Logging
    LOG_FILEPATH: str = Field(
        description="Path to log files directory"
    )
    
    # Argon2 Hashing
    MEMORY_COST: int = Field(
        description="Memory cost for Argon2 hashing"
    )
    
    PARALLELISM: int = Field(
        description="Parallelism factor for Argon2"
    )
    
    HASH_LENGTH: int = Field(
        description="Hash length for Argon2"
    )
    
    SALT_LENGTH: int = Field(
        description="Length of salt for password hashing"
    )
    
    # Admin Configuration
    ADMIN_USERNAME: str = Field(
        description="Default admin username"
    )
    
    ADMIN_EMAIL: str = Field(
        description="Default admin email"
    )
    
    ADMIN_PASSWORD: str = Field(
        description="Default admin password"
    )
    
    # Environment
    ENVIRONMENT: str = Field(
        default="development",
        description="Environment (development/production)"
    )
    
    # CORS
    ALLOWED_ORIGINS: str = Field(
        default="*",
        description="Allowed CORS origins (comma-separated)"
    )
    
    @field_validator('RATE_LIMIT_DEFAULT', mode='before')
    @classmethod
    def validate_rate_limit(cls, v: Any) -> Any:
        """Ensure RATE_LIMIT_DEFAULT is in a valid format"""
        if v is None:
            return "100/minute"
        v_str = str(v).strip()
        if v_str.isdigit():
            return f"{v_str}/minute"
        if "/" not in v_str:
            return f"{v_str}/minute"
        return v_str
    
    @field_validator('ACCESS_TOKEN_EXPIRE_MINUTES', mode='before')
    @classmethod
    def validate_token_expiry(cls, v: Any) -> Any:
        """Convert string to int if needed"""
        if v is None:
            return 790
        try:
            return int(v)
        except (ValueError, TypeError):
            return 790
    
    @field_validator('MEMORY_COST', mode='before')
    @classmethod
    def validate_memory_cost(cls, v: Any) -> Any:
        """Convert string to int if needed"""
        if v is None:
            return 65536
        try:
            return int(v)
        except (ValueError, TypeError):
            return 65536
    
    @field_validator('PARALLELISM', mode='before')
    @classmethod
    def validate_parallelism(cls, v: Any) -> Any:
        """Convert string to int if needed"""
        if v is None:
            return 2
        try:
            return int(v)
        except (ValueError, TypeError):
            return 2
    
    @field_validator('HASH_LENGTH', mode='before')
    @classmethod
    def validate_hash_length(cls, v: Any) -> Any:
        """Convert string to int if needed"""
        if v is None:
            return 32
        try:
            return int(v)
        except (ValueError, TypeError):
            return 32
    
    @field_validator('SALT_LENGTH', mode='before')
    @classmethod
    def validate_salt_length(cls, v: Any) -> Any:
        """Convert string to int if needed"""
        if v is None:
            return 16
        try:
            return int(v)
        except (ValueError, TypeError):
            return 16
    
    @field_validator('KILL_SWITCH_ENABLED', mode='before')
    @classmethod
    def validate_kill_switch(cls, v: Any) -> Any:
        """Convert string to bool if needed"""
        if v is None:
            return False
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ('true', '1', 'yes', 'on')
        return False
    
    # Computed properties
    @property
    def secret_key_str(self) -> str:
        """Get the secret key as string"""
        return self.SECRET_KEY.get_secret_value()
    
    def get_argon2_params(self) -> dict:
        """Get Argon2 parameters as a dictionary"""
        return {
            "memory_cost": self.MEMORY_COST,
            "parallelism": self.PARALLELISM,
            "hash_len": self.HASH_LENGTH
        }


# Create singleton instance
settings = Settings()
