from fastapi import APIRouter
from .Users import router as users_router
from .Gits import git_router
v1_router=APIRouter()
v1_router.include_router(users_router)
v1_router.include_router(git_router)