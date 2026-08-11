from pydantic import BaseModel, Field
from typing import Optional, List,Dict
from enum import Enum

# ==================== EXISTING MODELS ====================

class MakeRepo(BaseModel):
    repository_name: str = Field(..., description="Repository name")
    branch_name: str = Field(..., description="Branch name")

# ==================== NEW MODELS ====================

class BranchCreate(BaseModel):
    branch_name: str = Field(..., min_length=1, max_length=255, description="Branch name")
    branch_from: str = Field("main", description="Source branch to create from")

class BranchDelete(BaseModel):
    branch_name: str = Field(..., description="Branch name to delete")
    force: bool = Field(False, description="Force delete even if current branch")

class CommitCreate(BaseModel):
    message: str = Field("Auto backup", description="Commit message")
    backup_type: str = Field("manual", description="Backup type: manual, scheduled, automatic")

class CheckoutRequest(BaseModel):
    target: str = Field(..., description="Branch name or commit SHA")
    force: bool = Field(False, description="Force checkout")

class MergeRequest(BaseModel):
    source_branch: str = Field(..., description="Source branch to merge from")
    target_branch: str = Field(..., description="Target branch to merge into")

class TagCreate(BaseModel):
    tag_name: str = Field(..., min_length=1, max_length=255, description="Tag name")
    target: str = Field("HEAD", description="Target commit or branch")

class TagDelete(BaseModel):
    tag_name: str = Field(..., description="Tag name to delete")

class ResetRequest(BaseModel):
    target: str = Field(..., description="Target commit SHA or branch")
    mode: str = Field("soft", description="Reset mode: soft, mixed, hard")

class StashCreate(BaseModel):
    message: str = Field("Stashed changes", description="Stash message")

class CompareRequest(BaseModel):
    source_branch: str = Field(..., description="Source branch")
    target_branch: str = Field(..., description="Target branch")

class FileListRequest(BaseModel):
    path: str = Field("", description="Path to list")
    branch: str = Field("main", description="Branch name")

class FileContentRequest(BaseModel):
    file_path: str = Field(..., description="File path")
    branch: str = Field("main", description="Branch name")

class RepoUpdateRequest(BaseModel):
    new_name: Optional[str] = Field(None, description="New repository name")
    is_public: Optional[bool] = Field(None, description="Make repository public")

# ==================== RESPONSE MODELS ====================

class BranchResponse(BaseModel):
    name: str
    commit: str

class CommitResponse(BaseModel):
    sha: str
    author: str
    message: str
    time: str
    timestamp: Optional[int] = None

class FileResponse(BaseModel):
    name: str
    type: str  # "file" or "directory"
    size: int

class RepositoryInfoResponse(BaseModel):
    name: str
    path: str
    branch: str
    latest_commit: Optional[dict] = None
    size_mb: float

class StashResponse(BaseModel):
    index: int
    sha: str
    message: str
    author: str
    time: str


class FileUploadRequest(BaseModel):
    file_path: str = Field(..., description="File path in repository")
    content: str = Field(..., description="File content (base64 or plain text)")
    encoding: str = Field("text", description="Encoding: 'text' or 'base64'")
    commit_message: Optional[str] = Field("Add file", description="Commit message")


class BulkFileUploadRequest(BaseModel):
    files: Dict[str, str] = Field(..., description="Dict of {file_path: content}")
    commit_message: Optional[str] = Field("Add multiple files", description="Commit message")
    encoding: str = Field("text", description="Encoding: 'text' or 'base64'")


class FileDeleteRequest(BaseModel):
    file_path: str = Field(..., description="File path to delete")
    commit_message: Optional[str] = Field("Delete file", description="Commit message")


class FileMoveRequest(BaseModel):
    source_path: str = Field(..., description="Source file path")
    dest_path: str = Field(..., description="Destination file path")
    commit_message: Optional[str] = Field("Move file", description="Commit message")


class FileResponse(BaseModel):
    file_path: str
    size: int
    content_type: Optional[str] = None