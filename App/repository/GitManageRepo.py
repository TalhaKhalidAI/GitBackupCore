from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from App.core.git_core import GitCore
from App.core.settings import settings
from App.core.LoggingInit import get_core_logger

class GitRpoManager:
    
    def __init__(self,gc:GitCore):
        self.core=gc.GitCore(max_repos=settings.MAX_REPOS)
    
    async def create_repo(self):
        try:
             pass
        except Exception as e:
            raise ValueError(f"Error creating repo due to {e}")
