from fastapi import APIRouter, Depends, HTTPException, status, Response, Query,File, UploadFile, Form
from sqlalchemy.orm import Session
from typing import List, Optional,Dict,Any
import logging
 
import base64
from App.api.dependencies.auth import (
    get_current_user,
    get_current_active_user,
    get_admin_user,
    verify_password,
    get_password_hash,
    create_access_token,
)
from App.repository.userRepository import UserRepository
from App.repository.GitManageRepo import GitRepoManager
from App.core.git_core import GitCore
from functools import lru_cache
from App.core.settings import settings
from operator import itemgetter
from App.models.GitRepoModel import (
    MakeRepo,
    BranchCreate,
    BranchDelete,
    CommitCreate,
    CheckoutRequest,
    MergeRequest,
    TagCreate,
    TagDelete,
    ResetRequest,
    StashCreate,
    CompareRequest,
    FileListRequest,
    FileContentRequest,
    RepoUpdateRequest,
    FileUploadRequest,
    BulkFileUploadRequest,
    FileDeleteRequest,
    FileMoveRequest,
    
)
import shutil
import os
import aiofiles
git_router = APIRouter(prefix="/git", tags=["Git"])
logger = logging.getLogger(__name__)


@lru_cache
def get_git_core() -> GitCore:
    return GitCore(max_repos=settings.MAX_REPOS)


async def get_git_manager(
    db: Session = Depends(get_db),
    gcore: GitCore = Depends(get_git_core),
) -> GitRepoManager:
    """Dependency that provides a GitRepoManager instance."""
    return GitRepoManager(gcore=gcore, db=db)


# ==================== REPOSITORY ENDPOINTS ====================

@git_router.get("/repositories")
async def list_repositories(
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    """List all repositories accessible to the user."""
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        all_repos = await gcore.list_repositories()
        
        # Filter by user permissions (implement in GitRepoManager for production)
        # For now, return all repos
        total = len(all_repos)
        repos = all_repos[skip:skip+limit]
        
        return {
            "success": True,
            "total": total,
            "skip": skip,
            "limit": limit,
            "data": repos
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list repositories: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list repositories: {str(e)}"
        )


@git_router.get("/repositories/{repo_name}")
async def get_repository(
    repo_name: str,
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get detailed repository information."""
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        info = await gcore.get_repository_info(repo_name)
        
        return {
            "success": True,
            "data": info
        }
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository '{repo_name}' not found"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get repository info: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get repository info: {str(e)}"
        )


# ==================== BRANCH ENDPOINTS ====================
@git_router.post("/{repo_name}/branches")
async def create_branch_endpoint(
    repo_name: str,
    branch_name: str = Query(..., description="Branch name"),
    branch_from: str = Query("main", description="Source branch"),
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Create a new branch using pure Git.
    """
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        
        # Check if repo exists
        repo_path = os.path.join(gcore.main_repo_path, repo_name)
        if not os.path.exists(os.path.join(repo_path, ".git")):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Repository '{repo_name}' not found"
            )
        
        result = await gcore.create_branch(
            repo_name=repo_name,
            branch_name=branch_name,
            branch_from=branch_from
        )
        
        return {
            "success": True,
            "message": f"Branch '{branch_name}' created successfully",
            "data": result
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create branch: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create branch: {str(e)}"
        )



@git_router.delete("/{repo_name}/branches/{branch_name}")
async def delete_branch_endpoint(
    repo_name: str,
    branch_name: str,
    force: bool = Query(False),
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Delete a branch using pure Git.
    """
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        
        # Check if repo exists
        repo_path = os.path.join(gcore.main_repo_path, repo_name)
        if not os.path.exists(os.path.join(repo_path, ".git")):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Repository '{repo_name}' not found"
            )
        
        result = await gcore.delete_branch(
            repo_name=repo_name,
            branch_name=branch_name,
            force=force
        )
        
        return {
            "success": True,
            "message": f"Branch '{branch_name}' deleted successfully",
            "data": result
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete branch: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete branch: {str(e)}"
        )


@git_router.get("/{repo_name}/branches")
async def list_branches_endpoint(
    repo_name: str,
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    List all branches using pure Git.
    """
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        
        # Check if repo exists
        repo_path = os.path.join(gcore.main_repo_path, repo_name)
        if not os.path.exists(os.path.join(repo_path, ".git")):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Repository '{repo_name}' not found"
            )
        
        result = await gcore.list_branches(repo_name)
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list branches: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list branches: {str(e)}"
        )


# ==================== COMMIT ENDPOINTS ====================

@git_router.post("/{repo_name}/commits")
async def create_commit_endpoint(
    repo_name: str,
    message: str = Query("Auto commit", description="Commit message"),
    backup_type: str = Query("manual", description="Backup type"),
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Create a new commit using pure Git (no database).
    """
    try:
        # Validate user exists (for authentication only)
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        
        # Check if repo exists on disk
        repo_path = os.path.join(gcore.main_repo_path, repo_name)
        if not os.path.exists(os.path.join(repo_path, ".git")):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Repository '{repo_name}' not found on disk"
            )
        
        # Create commit using GitCore
        result = await gcore.create_commit(
            repo_name=repo_name,
            message=message or f"Auto commit by {user.username}"
        )
        
        logger.info(f"Commit created in '{repo_name}' by user {cuser['id']}: {result['commit']}")
        
        return {
            "success": True,
            "message": f"Commit created successfully: {result['commit']}",
            "data": {
                "repo_name": repo_name,
                "commit_sha": result["commit"],
                "backup_type": backup_type,
                "created_by": user.username
            }
        }
        
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=str(e)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository '{repo_name}' not found"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create commit: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create commit: {str(e)}"
        )

@git_router.get("/{repo_name}/commits")
async def get_commit_history(
    repo_name: str,
    branch: str = Query("main"),
    limit: int = Query(10, ge=1, le=100),
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get commit history for a repository."""
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        
        # ✅ Check if repo exists
        repo_path = os.path.join(gcore.main_repo_path, repo_name)
        if not os.path.exists(os.path.join(repo_path, ".git")):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Repository '{repo_name}' not found"
            )
        
        history = await gcore.get_log(repo_name, branch, limit)
        
        return {
            "success": True,
            "data": history,
            "count": len(history)
        }
        
    except ValueError as e:
        # ✅ Branch not found
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository '{repo_name}' not found"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get commit history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get commit history: {str(e)}"
        )

@git_router.get("/{repo_name}/commits/{sha}")
async def get_commit_details(
    repo_name: str,
    sha: str,
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get details for a specific commit."""
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        details = await gcore.get_commit_show(repo_name, sha)
        
        return {
            "success": True,
            "data": details
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get commit details: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get commit details: {str(e)}"
        )


@git_router.post("/{repo_name}/commits/{sha}/revert")
async def revert_commit(
    repo_name: str,
    sha: str,
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Revert a specific commit."""
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        result = await gcore.revert(repo_name, sha)
        
        return {
            "success": True,
            "message": f"Commit '{sha[:8]}' reverted successfully",
            "data": result
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to revert commit: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to revert commit: {str(e)}"
        )


# ==================== CHECKOUT ENDPOINTS ====================

@git_router.post("/{repo_name}/checkout")
async def checkout_endpoint(
    repo_name: str,
    checkout_data: CheckoutRequest,
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Checkout a branch or commit."""
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        result = await gcore.checkout(
            repo_name=repo_name,
            target=checkout_data.target,
            force=checkout_data.force
        )
        
        return {
            "success": True,
            "message": f"Checked out '{checkout_data.target}' successfully",
            "data": result
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to checkout: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to checkout: {str(e)}"
        )


@git_router.get("/{repo_name}/status")
async def get_status(
    repo_name: str,
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get working tree status."""
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        status_data = await gcore.git_status(repo_name)
        
        return {
            "success": True,
            "data": status_data
        }
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository '{repo_name}' not found"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get status: {str(e)}"
        )


# ==================== COMPARE & MERGE ENDPOINTS ====================

@git_router.get("/{repo_name}/compare/{source_branch}/{target_branch}")
async def compare_branches_endpoint(
    repo_name: str,
    source_branch: str,
    target_branch: str,
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Compare two branches."""
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        diff = await gcore.compare_branches(repo_name, source_branch, target_branch)
        
        return {
            "success": True,
            "source_branch": source_branch,
            "target_branch": target_branch,
            "data": diff
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to compare branches: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to compare branches: {str(e)}"
        )


@git_router.post("/{repo_name}/merge")
async def merge_branches_endpoint(
    repo_name: str,
    merge_data: MergeRequest,
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Merge two branches."""
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        result = await gcore.merge_branches(
            repo_name=repo_name,
            source_branch=merge_data.source_branch,
            target_branch=merge_data.target_branch
        )
        
        if result.get("status") == "CONFLICT":
            return {
                "success": False,
                "status": "CONFLICT",
                "message": "Merge conflicts detected",
                "conflicting_files": result.get("conflicting_files", [])
            }
        
        return {
            "success": True,
            "message": f"Merged '{merge_data.source_branch}' into '{merge_data.target_branch}'",
            "data": result
        }
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to merge branches: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to merge branches: {str(e)}"
        )


# ==================== TAG ENDPOINTS ====================

@git_router.post("/{repo_name}/tags")
async def create_tag_endpoint(
    repo_name: str,
    tag_data: TagCreate,
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Create a new tag."""
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        result = await gcore.create_tag(
            repo_name=repo_name,
            tag_name=tag_data.tag_name,
            target=tag_data.target
        )
        
        return {
            "success": True,
            "message": f"Tag '{tag_data.tag_name}' created successfully",
            "data": result
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create tag: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create tag: {str(e)}"
        )


@git_router.get("/{repo_name}/tags")
async def list_tags_endpoint(
    repo_name: str,
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List all tags."""
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        tags = await gcore.list_tags(repo_name)
        
        return {
            "success": True,
            "data": tags,
            "count": len(tags)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list tags: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list tags: {str(e)}"
        )


@git_router.delete("/{repo_name}/tags/{tag_name}")
async def delete_tag_endpoint(
    repo_name: str,
    tag_name: str,
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Delete a tag."""
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        result = await gcore.delete_tag(repo_name, tag_name)
        
        return {
            "success": True,
            "message": f"Tag '{tag_name}' deleted successfully",
            "data": result
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete tag: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete tag: {str(e)}"
        )


# ==================== STASH ENDPOINTS ====================

@git_router.post("/{repo_name}/stash")
async def stash_push_endpoint(
    repo_name: str,
    stash_data: StashCreate = Depends(),
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Stash changes."""
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        result = await gcore.stash_push(repo_name, stash_data.message)
        
        return {
            "success": True,
            "message": "Changes stashed successfully",
            "data": result
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to stash: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stash: {str(e)}"
        )


@git_router.post("/{repo_name}/stash/pop")
async def stash_pop_endpoint(
    repo_name: str,
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Pop the most recent stash."""
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        result = await gcore.stash_pop(repo_name)
        
        return {
            "success": True,
            "message": "Stash popped successfully",
            "data": result
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to pop stash: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to pop stash: {str(e)}"
        )


@git_router.get("/{repo_name}/stash")
async def list_stashes_endpoint(
    repo_name: str,
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List all stashes."""
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        stashes = await gcore.list_stashes(repo_name)
        
        return {
            "success": True,
            "data": stashes,
            "count": len(stashes)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list stashes: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list stashes: {str(e)}"
        )


# ==================== FILE ENDPOINTS ====================

@git_router.get("/{repo_name}/files")
async def list_files_endpoint(
    repo_name: str,
    path: str = Query(""),
    branch: str = Query("main"),
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List files in repository at given path."""
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        files = await gcore.list_files(repo_name, path, branch)
        
        return {
            "success": True,
            "data": files,
            "count": len(files)
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list files: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list files: {str(e)}"
        )


@git_router.get("/{repo_name}/files/content")
async def get_file_content_endpoint(
    repo_name: str,
    file_path: str = Query(..., description="File path"),
    branch: str = Query("main"),
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get file content from repository."""
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        content = await gcore.get_file_content(repo_name, file_path, branch)
        
        return {
            "success": True,
            "data": {
                "file_path": file_path,
                "branch": branch,
                "content": content
            }
        }
    except ValueError as e:
        # ✅ FIX: File not found → 404, not 400
        if "not found" in str(e).lower() or "does not exist" in str(e).lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e)
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get file content: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get file content: {str(e)}"
        )


@git_router.get("/{repo_name}/files/diff")
async def get_file_diff_endpoint(
    repo_name: str,
    file_path: str = Query(..., description="File path"),
    branch: str = Query("main"),
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get file diff compared to disk."""
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        diff = await gcore.get_file_diff(repo_name, file_path, branch)
        
        return {
            "success": True,
            "data": diff
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get file diff: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get file diff: {str(e)}"
        )


# ==================== RESET ENDPOINT ====================

@git_router.post("/{repo_name}/reset")
async def reset_endpoint(
    repo_name: str,
    reset_data: ResetRequest,
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Reset current branch to a specific commit."""
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        result = await gcore.reset(repo_name, reset_data.target, reset_data.mode)
        
        return {
            "success": True,
            "message": f"Reset to '{reset_data.target}' successfully",
            "data": result
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reset: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reset: {str(e)}"
        )


# ==================== REFLOG ENDPOINT ====================

@git_router.get("/{repo_name}/reflog")
async def get_reflog_endpoint(
    repo_name: str,
    branch: str = Query("main"),
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get reflog for a branch."""
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        reflog = await gcore.reflog(repo_name, branch)
        
        return {
            "success": True,
            "data": reflog,
            "count": len(reflog)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get reflog: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get reflog: {str(e)}"
        )


# ==================== CHERRY-PICK ENDPOINT ====================

@git_router.post("/{repo_name}/commits/cherry-pick")
async def cherry_pick_endpoint(
    repo_name: str,
    commit_sha: str = Query(..., description="Commit SHA to cherry-pick"),
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Cherry-pick a commit to current branch."""
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        result = await gcore.cherry_pick(repo_name, commit_sha)
        
        return {
            "success": True,
            "message": f"Cherry-picked '{commit_sha[:8]}' successfully",
            "data": result
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cherry-pick: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cherry-pick: {str(e)}"
        )


# ==================== HEALTH ENDPOINT ====================

@git_router.get("/health")
async def git_health_check():
    """Get GitCore health and metrics."""
    try:
        gcore = get_git_core()
        health = await gcore.health_check()
        return {
            "success": True,
            "data": health
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "success": False,
            "status": "unhealthy",
            "error": str(e)
        }


# ==================== FILE UPLOAD ENDPOINTS ====================

@git_router.post("/{repo_name}/files/upload")
async def upload_file(
    repo_name: str,
    file_data: FileUploadRequest,
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Upload a single file to the repository.
    
    Supports:
    - Plain text: encoding="text", content="Hello World"
    - Base64: encoding="base64", content="SGVsbG8gV29ybGQ="
    """
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        
        # Decode content based on encoding
        if file_data.encoding == "base64":
            try:
                content = base64.b64decode(file_data.content)
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid base64 encoding"
                )
        else:
            content = file_data.content.encode('utf-8')
        
        # Add file to repository
        result = await gcore.add_file(
            repo_name=repo_name,
            file_path=file_data.file_path,
            content=content,
            commit_message=file_data.commit_message or f"Add file: {file_data.file_path}"
        )
        
        return {
            "success": True,
            "message": f"File '{file_data.file_path}' uploaded successfully",
            "data": result
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to upload file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {str(e)}"
        )


@git_router.post("/{repo_name}/files/upload-multiple")
async def upload_multiple_files(
    repo_name: str,
    file_data: BulkFileUploadRequest,
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Upload multiple files to the repository.
    
    Example:
    {
        "files": {
            "src/main.py": "print('Hello')",
            "README.md": "# My Project"
        },
        "commit_message": "Add initial files"
    }
    """
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        
        # Decode all files
        decoded_files = {}
        for file_path, content in file_data.files.items():
            if file_data.encoding == "base64":
                try:
                    decoded_files[file_path] = base64.b64decode(content)
                except Exception:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid base64 encoding for file: {file_path}"
                    )
            else:
                decoded_files[file_path] = content.encode('utf-8')
        
        # Add files to repository
        result = await gcore.add_files_bulk(
            repo_name=repo_name,
            files=decoded_files,
            commit_message=file_data.commit_message or "Add multiple files"
        )
        
        return {
            "success": True,
            "message": f"{len(decoded_files)} files uploaded successfully",
            "data": result
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to upload files: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload files: {str(e)}"
        )


@git_router.post("/{repo_name}/files/upload-blob")
async def upload_file_blob(
    repo_name: str,
    file: UploadFile = File(...),
    file_path: str = Form(..., description="File path in repository"),
    commit_message: str = Form("Add file", description="Commit message"),
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Upload a file as a binary blob (multipart/form-data).
    This is ideal for large files.
    """
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        
        # Read file content
        content = await file.read()
        
        # Add file to repository
        result = await gcore.add_file(
            repo_name=repo_name,
            file_path=file_path,
            content=content,
            commit_message=commit_message or f"Add file: {file.filename}"
        )
        
        return {
            "success": True,
            "message": f"File '{file_path}' uploaded successfully",
            "data": {
                "file_path": file_path,
                "original_filename": file.filename,
                "size": len(content),
                "commit": result["commit"]
            }
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to upload file blob: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {str(e)}"
        )

@git_router.delete("/{repo_name}/files")
async def delete_file_endpoint(
    repo_name: str,
    file_data: FileDeleteRequest,
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Delete a file or directory from the repository."""
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        
        # Use the new method that handles both files and directories
        result = await gcore.delete_file_or_dir(
            repo_name=repo_name,
            path=file_data.file_path,
            commit_message=file_data.commit_message or f"Delete: {file_data.file_path}"
        )
        
        return {
            "success": True,
            "message": f"{result['deleted_type'].capitalize()} '{file_data.file_path}' deleted successfully",
            "data": result
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete: {str(e)}"
        )

@git_router.post("/{repo_name}/files/move")
async def move_file_endpoint(
    repo_name: str,
    move_data: FileMoveRequest,
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Move/rename a file in the repository."""
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        
        result = await gcore.move_file(
            repo_name=repo_name,
            source_path=move_data.source_path,
            dest_path=move_data.dest_path,
            commit_message=move_data.commit_message or f"Move: {move_data.source_path} → {move_data.dest_path}"
        )
        
        return {
            "success": True,
            "message": f"File moved successfully",
            "data": result
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to move file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to move file: {str(e)}"
        )

#### REpo manager

@git_router.post("/repositories")
async def create_repository(
    repo_name: str = Query(..., description="Repository name"),
    branch_name: str = Query("main", description="Initial branch name"),
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Create a new Git repository.
    
    This initializes a new repository on disk with the specified branch.
    No database records are created - pure Git only.
    """
    try:
        # Validate user exists
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Validate repository name (basic security)
        if not repo_name or not repo_name.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Repository name cannot be empty"
            )
        
        # Prevent path traversal
        if ".." in repo_name or "/" in repo_name or "\\" in repo_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Repository name cannot contain path traversal characters"
            )
        
        # Check if repository already exists
        gcore = get_git_core()
        repo_path = os.path.join(gcore.main_repo_path, repo_name)
        if os.path.exists(repo_path):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Repository '{repo_name}' already exists"
            )
        
        # Initialize the repository
        result = await gcore.init_git(repo_name, branch_name)
        
        # Create initial commit (optional - creates an empty repo with no commits)
        # Uncomment if you want an initial commit
        # await gcore.create_commit(repo_name, "Initial commit")
        
        logger.info(f"User {cuser['id']} created repository '{repo_name}'")
        
        return {
            "success": True,
            "message": f"Repository '{repo_name}' created successfully",
            "data": {
                "repo_name": repo_name,
                "branch": branch_name,
                "path": repo_path,
                "created_by": cuser["username"]
            }
        }
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Failed to create repository '{repo_name}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create repository: {str(e)}"
        )

# App/core/git_core.py - Add delete method


@git_router.delete("/repositories/{repo_name}")
async def delete_repository(
    repo_name: str,
    force: bool = Query(False, description="Force delete even if not empty"),
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Delete a repository from disk."""
    try:
        # Validate user
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Check if user is admin or owner (you can add your own permission logic)
        # For now, allow any authenticated user
        
        gcore = get_git_core()
        
        # Check if repo exists
        repo_path = os.path.join(gcore.main_repo_path, repo_name)
        if not os.path.exists(repo_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Repository '{repo_name}' not found"
            )
        
        # Delete the repository
        result = await gcore.delete_repo(repo_name, force)
        
        logger.info(f"User {cuser['id']} deleted repository '{repo_name}'")
        
        return {
            "success": True,
            "message": f"Repository '{repo_name}' deleted successfully",
            "data": result
        }
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete repository '{repo_name}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete repository: {str(e)}"
        )

@git_router.post("/{repo_name}/files/upload-staging")
async def upload_staging(
    repo_name: str,
    file: UploadFile = File(...),
    file_path: str = Form(..., description="File path in repository"),
    cuser = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """
    Upload a file to staging area (no commit).
    Use /commits to commit all staged changes.
    """
    try:
        ur = UserRepository(db)
        user = ur.get_by_id(cuser["id"])
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        gcore = get_git_core()
        
        # Check if repo exists
        repo_path = os.path.join(gcore.main_repo_path, repo_name)
        if not os.path.exists(os.path.join(repo_path, ".git")):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Repository '{repo_name}' not found"
            )
        
        # Read file content
        content = await file.read()
        
        # Remove leading slash
        if file_path.startswith('/'):
            file_path = file_path.lstrip('/')
        
        # Security: Prevent path traversal
        if '..' in file_path:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid file path - directory traversal detected"
            )
        
        full_path = os.path.abspath(os.path.join(repo_path, file_path))
        repo_path_abs = os.path.abspath(repo_path)
        
        if not full_path.startswith(repo_path_abs + os.sep):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid file path - must be inside repository"
            )
        
        # Write file (NO COMMIT!)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        async with aiofiles.open(full_path, "wb") as f:
            await f.write(content)
        
        return {
            "success": True,
            "message": f"File '{file_path}' staged. Use /commits to commit.",
            "data": {
                "file_path": file_path,
                "size": len(content),
                "staged": True
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to stage file: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stage file: {str(e)}"
        )
