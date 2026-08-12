from fastapi import APIRouter
from .UserAuth import router
from .Admin import admin_router
from .Users import user_router
app_router=APIRouter()
app_router.include_router(router,prefix="/auth")
app_router.include_router(admin_router,prefix="/admin")
app_router.include_router(user_router,prefix="/users")