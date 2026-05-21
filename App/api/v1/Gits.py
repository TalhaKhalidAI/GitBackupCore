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
from App.repository.GitManageRepo import GitRepoManager
 

git_router = APIRouter(prefix="/git", tags=["Git"])

# Logger for user operations
logger = logging.getLogger(__name__)

@git_router.post("/")
async def posts(grm=Depends(GitRepoManager)):
    pass