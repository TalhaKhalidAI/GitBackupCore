# App/core/paramiko_helper.py

import paramiko
import os
import asyncio
import threading
import time
import tempfile
import shutil
import hashlib
import fnmatch
from typing import List, Dict, Optional, Any, Callable, Union
from concurrent.futures import ThreadPoolExecutor
from stat import S_ISDIR, S_ISREG, S_ISLNK
from pathlib import Path
import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

# ============================================================
# CONSTANTS
# ============================================================

MAX_UPLOAD_SIZE = 10 * 1024 * 1024 * 1024  # 10GB
MAX_DOWNLOAD_SIZE = 10 * 1024 * 1024 * 1024  # 10GB
CONNECTION_TIMEOUT = 30
OPERATION_TIMEOUT = 300
MAX_RETRIES = 3
RETRY_DELAY = 2
DEFAULT_CHUNK_SIZE = 65536  # 64KB

# ============================================================
# ENUMS & DATA CLASSES
# ============================================================

class FileType(Enum):
    FILE = "file"
    DIRECTORY = "directory"
    LINK = "link"
    UNKNOWN = "unknown"

@dataclass
class FileInfo:
    """File information from remote server."""
    name: str
    path: str
    type: FileType
    size: int
    mtime: float
    permissions: str
    owner: str = "unknown"
    group: str = "unknown"
    hash: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "type": self.type.value,
            "size": self.size,
            "mtime": self.mtime,
            "permissions": self.permissions,
            "owner": self.owner,
            "group": self.group,
            "hash": self.hash
        }

@dataclass
class TransferProgress:
    """Progress tracking for file transfers."""
    file_path: str
    transferred: int
    total: int
    percent: float
    speed: float  # bytes per second
    elapsed: float
    eta: float
    timestamp: float = field(default_factory=time.time)


# ============================================================
# PRODUCTION PARAMIKO HELPER
# ============================================================

class ParamikoHelper:
    """
    Production-ready Paramiko helper with thread safety.
    
    Features:
    - Multi-session connection management
    - Thread-safe operations
    - Automatic retry on connection failure
    - Progress callbacks for uploads/downloads
    - Recursive directory operations
    - File hashing and validation
    - Comprehensive error handling
    - Async wrappers for FastAPI integration
    """
    
    def __init__(self, max_workers: int = 10):
        """
        Initialize the helper with thread pool.
        
        Args:
            max_workers: Maximum number of concurrent operations
        """
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="ParamikoHelper"
        )
        self._connections: Dict[str, Dict] = {}
        self._lock = threading.RLock()
        self._session_counter = 0
        self._shutting_down = False
        logger.info(f"✅ ParamikoHelper initialized with {max_workers} workers")
    
    # ============================================================
    # CONNECTION MANAGEMENT
    # ============================================================
    
    def connect(
        self,
        session_id: str,
        host: str,
        username: str,
        password: Optional[str] = None,
        key_filename: Optional[str] = None,
        port: int = 22,
        timeout: int = CONNECTION_TIMEOUT,
        **kwargs
    ) -> bool:
        """
        Establish SSH connection to remote server with retry logic.
        
        Args:
            session_id: Unique session identifier
            host: Remote hostname or IP
            username: SSH username
            password: SSH password (optional if key_filename provided)
            key_filename: Path to private key file (optional)
            port: SSH port (default: 22)
            timeout: Connection timeout in seconds
            
        Returns:
            bool: True if connection successful
            
        Raises:
            ValueError: If neither password nor key_filename is provided
            Exception: On connection failure after retries
        """
        if self._shutting_down:
            raise RuntimeError("Helper is shutting down")
        
        # Close existing connection for this session
        with self._lock:
            if session_id in self._connections:
                self.disconnect(session_id)
        
        if not password and not key_filename:
            raise ValueError("Either password or key_filename must be provided")
        
        last_error = None
        
        for attempt in range(MAX_RETRIES):
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                
                connect_kwargs = {
                    'hostname': host,
                    'port': port,
                    'username': username,
                    'timeout': timeout,
                    'allow_agent': False,
                    'look_for_keys': False
                }
                
                if password:
                    connect_kwargs['password'] = password
                elif key_filename:
                    connect_kwargs['key_filename'] = key_filename
                
                ssh.connect(**connect_kwargs)
                sftp = ssh.open_sftp()
                
                with self._lock:
                    self._connections[session_id] = {
                        'ssh': ssh,
                        'sftp': sftp,
                        'host': host,
                        'username': username,
                        'port': port,
                        'connected_at': time.time(),
                        'last_activity': time.time()
                    }
                
                logger.info(f"✅ Connected to {host}:{port} as {username} (session: {session_id})")
                return True
                
            except Exception as e:
                last_error = e
                logger.warning(f"Connection attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (attempt + 1))  # Exponential backoff
        
        logger.error(f"❌ All connection attempts failed for {session_id}")
        raise last_error
    
    def disconnect(self, session_id: str) -> bool:
        """
        Disconnect SSH session.
        
        Args:
            session_id: Session to disconnect
            
        Returns:
            bool: True if disconnected successfully
        """
        with self._lock:
            if session_id not in self._connections:
                return False
            
            conn = self._connections[session_id]
            try:
                if conn.get('sftp'):
                    try:
                        conn['sftp'].close()
                    except Exception:
                        pass
                if conn.get('ssh'):
                    try:
                        conn['ssh'].close()
                    except Exception:
                        pass
                del self._connections[session_id]
                logger.info(f"🔚 Disconnected session: {session_id}")
                return True
            except Exception as e:
                logger.error(f"❌ Error disconnecting {session_id}: {e}")
                return False
    
    def get_connection(self, session_id: str) -> Dict:
        """
        Get connection by session ID (thread-safe).
        
        Args:
            session_id: Session identifier
            
        Returns:
            Dict: Connection details
            
        Raises:
            ValueError: If session not found
        """
        with self._lock:
            if session_id not in self._connections:
                raise ValueError(f"Session '{session_id}' not found")
            return self._connections[session_id]
    
    def get_sftp(self, session_id: str):
        """
        Get SFTP client for session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            SFTPClient: SFTP client
            
        Raises:
            ValueError: If session not found
        """
        conn = self.get_connection(session_id)
        return conn['sftp']
    
    def get_ssh(self, session_id: str):
        """
        Get SSH client for session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            SSHClient: SSH client
            
        Raises:
            ValueError: If session not found
        """
        conn = self.get_connection(session_id)
        return conn['ssh']
    
    def is_connected(self, session_id: str) -> bool:
        """
        Check if session is still connected.
        
        Args:
            session_id: Session identifier
            
        Returns:
            bool: True if connected
        """
        with self._lock:
            if session_id not in self._connections:
                return False
            try:
                conn = self._connections[session_id]
                transport = conn['ssh'].get_transport()
                return transport is not None and transport.is_active()
            except Exception:
                return False
    
    def health_check(self, session_id: str) -> Dict[str, Any]:
        """
        Check connection health.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Dict: Health status information
        """
        try:
            conn = self.get_connection(session_id)
            transport = conn['ssh'].get_transport()
            return {
                "connected": transport is not None and transport.is_active(),
                "session_id": session_id,
                "host": conn.get('host'),
                "username": conn.get('username'),
                "port": conn.get('port'),
                "uptime_seconds": int(time.time() - conn.get('connected_at', 0)),
                "last_activity_seconds": int(time.time() - conn.get('last_activity', 0))
            }
        except Exception as e:
            return {
                "connected": False,
                "session_id": session_id,
                "error": str(e)
            }
    
    # ============================================================
    # PATH VALIDATION
    # ============================================================
    
    def _validate_path(self, remote_path: str) -> None:
        """
        Validate remote path for security.
        
        Args:
            remote_path: Path to validate
            
        Raises:
            ValueError: If path is invalid
        """
        if not remote_path:
            raise ValueError("Path cannot be empty")
        
        # Prevent path traversal
        if '..' in remote_path:
            raise ValueError(f"Invalid path: '{remote_path}' contains '..'")
    
    def _update_activity(self, session_id: str) -> None:
        """Update last activity timestamp for session."""
        with self._lock:
            if session_id in self._connections:
                self._connections[session_id]['last_activity'] = time.time()
    
    # ============================================================
    # FILE EXPLORATION
    # ============================================================
    
    def list_files(self, session_id: str, remote_path: str = ".") -> List[FileInfo]:
        """
        List files in a remote directory.
        
        Args:
            session_id: Session identifier
            remote_path: Remote directory path
            
        Returns:
            List[FileInfo]: List of file information
            
        Raises:
            ValueError: If directory not found
        """
        self._validate_path(remote_path)
        self._update_activity(session_id)
        sftp = self.get_sftp(session_id)
        
        try:
            files = []
            for entry in sftp.listdir_attr(remote_path):
                full_path = f"{remote_path}/{entry.filename}".replace("//", "/")
                
                if S_ISDIR(entry.st_mode):
                    file_type = FileType.DIRECTORY
                elif S_ISLNK(entry.st_mode):
                    file_type = FileType.LINK
                else:
                    file_type = FileType.FILE
                
                perms = self._mode_to_permissions(entry.st_mode)
                
                # Get owner/group (may not be available on all systems)
                try:
                    owner = str(entry.st_uid)
                    group = str(entry.st_gid)
                except AttributeError:
                    owner = "unknown"
                    group = "unknown"
                
                files.append(FileInfo(
                    name=entry.filename,
                    path=full_path,
                    type=file_type,
                    size=entry.st_size,
                    mtime=entry.st_mtime,
                    permissions=perms,
                    owner=owner,
                    group=group
                ))
            
            return files
            
        except FileNotFoundError:
            raise ValueError(f"Directory '{remote_path}' not found")
        except Exception as e:
            logger.error(f"❌ Failed to list files at {remote_path}: {e}")
            raise
    
    def explore_tree(self, session_id: str, remote_path: str = ".") -> Dict[str, Any]:
        """
        Recursively explore directory tree.
        
        Args:
            session_id: Session identifier
            remote_path: Remote directory path
            
        Returns:
            Dict: Nested directory tree structure
        """
        files = self.list_files(session_id, remote_path)
        
        tree = {
            "name": os.path.basename(remote_path) or remote_path,
            "path": remote_path,
            "type": "directory",
            "children": []
        }
        
        for file_info in files:
            if file_info.type == FileType.DIRECTORY:
                child_tree = self.explore_tree(session_id, file_info.path)
                tree["children"].append(child_tree)
            else:
                tree["children"].append({
                    "name": file_info.name,
                    "path": file_info.path,
                    "type": file_info.type.value,
                    "size": file_info.size,
                    "mtime": file_info.mtime,
                    "permissions": file_info.permissions
                })
        
        return tree
    
    def get_file_info(self, session_id: str, remote_path: str) -> FileInfo:
        """
        Get detailed information about a remote file or directory.
        
        Args:
            session_id: Session identifier
            remote_path: Remote file path
            
        Returns:
            FileInfo: File information
            
        Raises:
            ValueError: If path not found
        """
        self._validate_path(remote_path)
        self._update_activity(session_id)
        sftp = self.get_sftp(session_id)
        
        try:
            stat = sftp.stat(remote_path)
            
            if S_ISDIR(stat.st_mode):
                file_type = FileType.DIRECTORY
            elif S_ISLNK(stat.st_mode):
                file_type = FileType.LINK
            else:
                file_type = FileType.FILE
            
            try:
                owner = str(stat.st_uid)
                group = str(stat.st_gid)
            except AttributeError:
                owner = "unknown"
                group = "unknown"
            
            return FileInfo(
                name=os.path.basename(remote_path),
                path=remote_path,
                type=file_type,
                size=stat.st_size,
                mtime=stat.st_mtime,
                permissions=self._mode_to_permissions(stat.st_mode),
                owner=owner,
                group=group
            )
            
        except FileNotFoundError:
            raise ValueError(f"Path '{remote_path}' not found")
        except Exception as e:
            logger.error(f"❌ Failed to get info for {remote_path}: {e}")
            raise
    
    def file_exists(self, session_id: str, remote_path: str) -> bool:
        """
        Check if a file or directory exists on remote.
        
        Args:
            session_id: Session identifier
            remote_path: Remote file path
            
        Returns:
            bool: True if exists
        """
        try:
            sftp = self.get_sftp(session_id)
            sftp.stat(remote_path)
            return True
        except FileNotFoundError:
            return False
        except Exception:
            return False
    
    # ============================================================
    # DIRECTORY OPERATIONS
    # ============================================================
    
    def create_directory(
        self,
        session_id: str,
        remote_path: str,
        mode: int = 0o755
    ) -> bool:
        """
        Create a directory and all parent directories.
        
        Args:
            session_id: Session identifier
            remote_path: Remote directory path
            mode: Directory permissions (default: 0o755)
            
        Returns:
            bool: True if created or already exists
            
        Raises:
            ValueError: If path is invalid
        """
        self._validate_path(remote_path)
        self._update_activity(session_id)
        sftp = self.get_sftp(session_id)
        
        # Check if already exists
        try:
            stat = sftp.stat(remote_path)
            if S_ISDIR(stat.st_mode):
                return True
            raise ValueError(f"Path '{remote_path}' exists but is not a directory")
        except FileNotFoundError:
            pass
        
        # Create parent directories first
        parent = os.path.dirname(remote_path)
        if parent and parent != remote_path:
            self.create_directory(session_id, parent, mode)
        
        # Create the directory
        try:
            sftp.mkdir(remote_path, mode)
            logger.info(f"📁 Created directory: {remote_path}")
            return True
        except Exception as e:
            # Check if directory was created by another process
            try:
                stat = sftp.stat(remote_path)
                if S_ISDIR(stat.st_mode):
                    return True
            except Exception:
                pass
            logger.error(f"❌ Failed to create directory {remote_path}: {e}")
            raise
    
    # ============================================================
    # FILE TRANSFER
    # ============================================================
    
    def upload_file(
        self,
        session_id: str,
        local_path: str,
        remote_path: str,
        progress_callback: Optional[Callable] = None,
        preserve_permissions: bool = True,
        timeout: int = OPERATION_TIMEOUT,
        chunk_size: int = DEFAULT_CHUNK_SIZE
    ) -> Dict[str, Any]:
        """
        Upload a file to remote server.
        
        Args:
            session_id: Session identifier
            local_path: Local file path
            remote_path: Remote file path
            progress_callback: Optional callback for progress updates
            preserve_permissions: Preserve file permissions
            timeout: Operation timeout in seconds
            chunk_size: Chunk size for transfer
            
        Returns:
            Dict: Transfer statistics
            
        Raises:
            ValueError: If file not found or too large
        """
        self._validate_path(remote_path)
        self._update_activity(session_id)
        sftp = self.get_sftp(session_id)
        
        if not os.path.exists(local_path):
            raise ValueError(f"Local file '{local_path}' not found")
        
        if os.path.isdir(local_path):
            raise ValueError(f"'{local_path}' is a directory, not a file")
        
        file_size = os.path.getsize(local_path)
        if file_size > MAX_UPLOAD_SIZE:
            raise ValueError(f"File too large: {file_size} bytes (max: {MAX_UPLOAD_SIZE})")
        
        try:
            remote_dir = os.path.dirname(remote_path)
            if remote_dir:
                self.create_directory(session_id, remote_dir)
            
            start_time = time.time()
            
            def progress_callback_wrapper(transferred, total):
                if progress_callback:
                    elapsed = time.time() - start_time
                    percent = (transferred / total) * 100 if total > 0 else 0
                    speed = transferred / elapsed if elapsed > 0 else 0
                    eta = (total - transferred) / speed if speed > 0 else 0
                    
                    progress_callback(TransferProgress(
                        file_path=remote_path,
                        transferred=transferred,
                        total=total,
                        percent=percent,
                        speed=speed,
                        elapsed=elapsed,
                        eta=eta
                    ))
            
            sftp.put(
                local_path,
                remote_path,
                callback=progress_callback_wrapper if progress_callback else None,
                timeout=timeout
            )
            
            # Preserve permissions
            if preserve_permissions:
                try:
                    st = os.stat(local_path)
                    sftp.chmod(remote_path, st.st_mode)
                except Exception as e:
                    logger.warning(f"Failed to preserve permissions: {e}")
            
            elapsed = time.time() - start_time
            speed = file_size / elapsed if elapsed > 0 else 0
            
            return {
                "success": True,
                "local_path": local_path,
                "remote_path": remote_path,
                "size": file_size,
                "elapsed_seconds": round(elapsed, 2),
                "speed_mbps": round(speed / (1024 * 1024), 2),
                "message": f"Uploaded {file_size} bytes in {elapsed:.2f}s"
            }
            
        except Exception as e:
            logger.error(f"❌ Upload failed: {e}")
            raise
    
    def upload_directory(
        self,
        session_id: str,
        local_dir: str,
        remote_dir: str,
        progress_callback: Optional[Callable] = None,
        exclude_patterns: Optional[List[str]] = None,
        timeout: int = OPERATION_TIMEOUT
    ) -> Dict[str, Any]:
        """
        Recursively upload a directory.
        
        Args:
            session_id: Session identifier
            local_dir: Local directory path
            remote_dir: Remote directory path
            progress_callback: Optional callback for progress updates
            exclude_patterns: List of glob patterns to exclude
            timeout: Operation timeout in seconds
            
        Returns:
            Dict: Upload statistics
        """
        if not os.path.exists(local_dir):
            raise ValueError(f"Local directory '{local_dir}' not found")
        
        if not os.path.isdir(local_dir):
            raise ValueError(f"'{local_dir}' is not a directory")
        
        # Create remote root directory
        self.create_directory(session_id, remote_dir)
        
        stats = {
            "files": 0,
            "directories": 0,
            "size_bytes": 0,
            "failed": 0,
            "failed_files": []
        }
        
        for root, dirs, files in os.walk(local_dir):
            rel_path = os.path.relpath(root, local_dir)
            remote_subdir = os.path.join(remote_dir, rel_path).replace("\\", "/")
            
            # Skip excluded patterns
            if exclude_patterns:
                dirs[:] = [d for d in dirs if not self._matches_pattern(d, exclude_patterns)]
                files = [f for f in files if not self._matches_pattern(f, exclude_patterns)]
            
            # Create subdirectory
            if rel_path != ".":
                self.create_directory(session_id, remote_subdir)
                stats["directories"] += 1
            
            # Upload files
            for file in files:
                local_file = os.path.join(root, file)
                remote_file = os.path.join(remote_subdir, file).replace("\\", "/")
                
                try:
                    self.upload_file(
                        session_id,
                        local_file,
                        remote_file,
                        progress_callback,
                        timeout=timeout
                    )
                    stats["files"] += 1
                    stats["size_bytes"] += os.path.getsize(local_file)
                except Exception as e:
                    stats["failed"] += 1
                    stats["failed_files"].append(local_file)
                    logger.error(f"❌ Failed to upload {local_file}: {e}")
        
        return stats
    
    def download_file(
        self,
        session_id: str,
        remote_path: str,
        local_path: str,
        progress_callback: Optional[Callable] = None,
        timeout: int = OPERATION_TIMEOUT
    ) -> Dict[str, Any]:
        """
        Download a file from remote server.
        
        Args:
            session_id: Session identifier
            remote_path: Remote file path
            local_path: Local file path
            progress_callback: Optional callback for progress updates
            timeout: Operation timeout in seconds
            
        Returns:
            Dict: Transfer statistics
            
        Raises:
            ValueError: If path is a directory or file too large
        """
        self._validate_path(remote_path)
        self._update_activity(session_id)
        sftp = self.get_sftp(session_id)
        
        try:
            file_info = self.get_file_info(session_id, remote_path)
            if file_info.type == FileType.DIRECTORY:
                raise ValueError(f"'{remote_path}' is a directory, not a file")
            
            if file_info.size > MAX_DOWNLOAD_SIZE:
                raise ValueError(f"File too large: {file_info.size} bytes (max: {MAX_DOWNLOAD_SIZE})")
            
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            
            start_time = time.time()
            
            def progress_callback_wrapper(transferred, total):
                if progress_callback:
                    elapsed = time.time() - start_time
                    percent = (transferred / total) * 100 if total > 0 else 0
                    speed = transferred / elapsed if elapsed > 0 else 0
                    eta = (total - transferred) / speed if speed > 0 else 0
                    
                    progress_callback(TransferProgress(
                        file_path=remote_path,
                        transferred=transferred,
                        total=total,
                        percent=percent,
                        speed=speed,
                        elapsed=elapsed,
                        eta=eta
                    ))
            
            sftp.get(
                remote_path,
                local_path,
                callback=progress_callback_wrapper if progress_callback else None,
                timeout=timeout
            )
            
            elapsed = time.time() - start_time
            speed = file_info.size / elapsed if elapsed > 0 else 0
            
            return {
                "success": True,
                "remote_path": remote_path,
                "local_path": local_path,
                "size": file_info.size,
                "elapsed_seconds": round(elapsed, 2),
                "speed_mbps": round(speed / (1024 * 1024), 2),
                "message": f"Downloaded {file_info.size} bytes in {elapsed:.2f}s"
            }
            
        except Exception as e:
            logger.error(f"❌ Download failed: {e}")
            raise
    
    def download_directory(
        self,
        session_id: str,
        remote_dir: str,
        local_dir: str,
        progress_callback: Optional[Callable] = None,
        timeout: int = OPERATION_TIMEOUT
    ) -> Dict[str, Any]:
        """
        Recursively download a directory.
        
        Args:
            session_id: Session identifier
            remote_dir: Remote directory path
            local_dir: Local directory path
            progress_callback: Optional callback for progress updates
            timeout: Operation timeout in seconds
            
        Returns:
            Dict: Download statistics
        """
        os.makedirs(local_dir, exist_ok=True)
        
        stats = {
            "files": 0,
            "directories": 0,
            "size_bytes": 0,
            "failed": 0,
            "failed_files": []
        }
        
        # Walk remote directory
        tree = self.explore_tree(session_id, remote_dir)
        
        def process_tree(node, current_local):
            if node["type"] == "directory":
                os.makedirs(current_local, exist_ok=True)
                stats["directories"] += 1
                
                for child in node.get("children", []):
                    child_local = os.path.join(current_local, child["name"])
                    process_tree(child, child_local)
            else:
                try:
                    self.download_file(
                        session_id,
                        node["path"],
                        current_local,
                        progress_callback,
                        timeout=timeout
                    )
                    stats["files"] += 1
                    stats["size_bytes"] += node.get("size", 0)
                except Exception as e:
                    stats["failed"] += 1
                    stats["failed_files"].append(node["path"])
                    logger.error(f"❌ Failed to download {node['path']}: {e}")
        
        process_tree(tree, local_dir)
        return stats
    
    # ============================================================
    # FILE OPERATIONS
    # ============================================================
    
    def delete_file(self, session_id: str, remote_path: str) -> bool:
        """
        Delete a file.
        
        Args:
            session_id: Session identifier
            remote_path: Remote file path
            
        Returns:
            bool: True if deleted
            
        Raises:
            ValueError: If path is a directory
        """
        self._validate_path(remote_path)
        self._update_activity(session_id)
        sftp = self.get_sftp(session_id)
        
        try:
            file_info = self.get_file_info(session_id, remote_path)
            if file_info.type == FileType.DIRECTORY:
                raise ValueError(f"'{remote_path}' is a directory, use delete_directory() instead")
            
            sftp.remove(remote_path)
            logger.info(f"🗑️ Deleted file: {remote_path}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to delete {remote_path}: {e}")
            raise
    
    def delete_directory(
        self,
        session_id: str,
        remote_path: str,
        recursive: bool = True
    ) -> bool:
        """
        Delete a directory.
        
        Args:
            session_id: Session identifier
            remote_path: Remote directory path
            recursive: Delete recursively
            
        Returns:
            bool: True if deleted
            
        Raises:
            ValueError: If path is not a directory
        """
        self._validate_path(remote_path)
        self._update_activity(session_id)
        sftp = self.get_sftp(session_id)
        
        try:
            file_info = self.get_file_info(session_id, remote_path)
            if file_info.type != FileType.DIRECTORY:
                raise ValueError(f"'{remote_path}' is not a directory")
            
            if recursive:
                for entry in sftp.listdir(remote_path):
                    entry_path = f"{remote_path}/{entry}"
                    entry_info = self.get_file_info(session_id, entry_path)
                    
                    if entry_info.type == FileType.DIRECTORY:
                        self.delete_directory(session_id, entry_path, recursive=True)
                    else:
                        sftp.remove(entry_path)
            
            sftp.rmdir(remote_path)
            logger.info(f"🗑️ Deleted directory: {remote_path}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to delete directory {remote_path}: {e}")
            raise
    
    def move_file(
        self,
        session_id: str,
        source_path: str,
        dest_path: str
    ) -> bool:
        """
        Move/rename a file or directory.
        
        Args:
            session_id: Session identifier
            source_path: Source path
            dest_path: Destination path
            
        Returns:
            bool: True if moved
        """
        self._validate_path(source_path)
        self._validate_path(dest_path)
        self._update_activity(session_id)
        sftp = self.get_sftp(session_id)
        
        try:
            # Ensure destination directory exists
            dest_dir = os.path.dirname(dest_path)
            if dest_dir:
                self.create_directory(session_id, dest_dir)
            
            sftp.rename(source_path, dest_path)
            logger.info(f"📦 Moved {source_path} → {dest_path}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to move {source_path} → {dest_path}: {e}")
            raise
    
    def copy_file(
        self,
        session_id: str,
        source_path: str,
        dest_path: str,
        timeout: int = OPERATION_TIMEOUT
    ) -> bool:
        """
        Copy a file (download + upload).
        
        Args:
            session_id: Session identifier
            source_path: Source path
            dest_path: Destination path
            timeout: Operation timeout in seconds
            
        Returns:
            bool: True if copied
        """
        with tempfile.NamedTemporaryFile(delete=True) as temp_file:
            self.download_file(session_id, source_path, temp_file.name, timeout=timeout)
            self.upload_file(session_id, temp_file.name, dest_path, timeout=timeout)
        
        logger.info(f"📋 Copied {source_path} → {dest_path}")
        return True
    
    # ============================================================
    # FILE HASHING
    # ============================================================
    
    def get_file_hash(
        self,
        session_id: str,
        remote_path: str,
        algorithm: str = "md5"
    ) -> str:
        """
        Get hash of a remote file.
        
        Args:
            session_id: Session identifier
            remote_path: Remote file path
            algorithm: Hash algorithm (md5, sha1, sha256)
            
        Returns:
            str: File hash in hex
        """
        with tempfile.NamedTemporaryFile(delete=True) as temp_file:
            self.download_file(session_id, remote_path, temp_file.name)
            
            hasher = hashlib.new(algorithm)
            with open(temp_file.name, 'rb') as f:
                for chunk in iter(lambda: f.read(65536), b''):
                    hasher.update(chunk)
            
            return hasher.hexdigest()
    
    # ============================================================
    # COMMAND EXECUTION
    # ============================================================
    
    def exec_command(
        self,
        session_id: str,
        command: str,
        timeout: int = OPERATION_TIMEOUT
    ) -> Dict[str, str]:
        """
        Execute a shell command on the remote server.
        
        Args:
            session_id: Session identifier
            command: Command to execute
            timeout: Command timeout in seconds
            
        Returns:
            Dict: Command output (stdout, stderr)
        """
        self._update_activity(session_id)
        ssh = self.get_ssh(session_id)
        
        try:
            stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
            
            return {
                'stdout': stdout.read().decode('utf-8', errors='replace'),
                'stderr': stderr.read().decode('utf-8', errors='replace'),
                'exit_code': stdout.channel.recv_exit_status() if hasattr(stdout, 'channel') else 0
            }
        except Exception as e:
            logger.error(f"❌ Command execution failed: {e}")
            raise
    
    # ============================================================
    # UTILITY METHODS
    # ============================================================
    
    def _mode_to_permissions(self, mode: int) -> str:
        """Convert st_mode to string permissions."""
        perms = []
        # User
        perms.append('r' if mode & 0o400 else '-')
        perms.append('w' if mode & 0o200 else '-')
        perms.append('x' if mode & 0o100 else '-')
        # Group
        perms.append('r' if mode & 0o040 else '-')
        perms.append('w' if mode & 0o020 else '-')
        perms.append('x' if mode & 0o010 else '-')
        # Others
        perms.append('r' if mode & 0o004 else '-')
        perms.append('w' if mode & 0o002 else '-')
        perms.append('x' if mode & 0o001 else '-')
        return ''.join(perms)
    
    def _matches_pattern(self, name: str, patterns: List[str]) -> bool:
        """Check if name matches any pattern."""
        for pattern in patterns:
            if fnmatch.fnmatch(name, pattern):
                return True
        return False
    
    # ============================================================
    # ASYNC WRAPPERS (for FastAPI integration)
    # ============================================================
    
    async def connect_async(
        self,
        session_id: str,
        host: str,
        username: str,
        **kwargs
    ) -> bool:
        """Async wrapper for connect."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            self.connect,
            session_id, host, username, **kwargs
        )
    
    async def list_files_async(
        self,
        session_id: str,
        remote_path: str = "."
    ) -> List[Dict]:
        """Async wrapper for list_files."""
        loop = asyncio.get_running_loop()
        files = await loop.run_in_executor(
            self._executor,
            self.list_files,
            session_id, remote_path
        )
        return [f.to_dict() for f in files]
    
    async def explore_tree_async(
        self,
        session_id: str,
        remote_path: str = "."
    ) -> Dict:
        """Async wrapper for explore_tree."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            self.explore_tree,
            session_id, remote_path
        )
    
    async def upload_file_async(
        self,
        session_id: str,
        local_path: str,
        remote_path: str,
        progress_callback: Optional[Callable] = None
    ) -> Dict:
        """Async wrapper for upload_file."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            self.upload_file,
            session_id, local_path, remote_path, progress_callback
        )
    
    async def download_file_async(
        self,
        session_id: str,
        remote_path: str,
        local_path: str,
        progress_callback: Optional[Callable] = None
    ) -> Dict:
        """Async wrapper for download_file."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            self.download_file,
            session_id, remote_path, local_path, progress_callback
        )
    
    async def delete_file_async(
        self,
        session_id: str,
        remote_path: str
    ) -> bool:
        """Async wrapper for delete_file."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            self.delete_file,
            session_id, remote_path
        )
    
    async def delete_directory_async(
        self,
        session_id: str,
        remote_path: str,
        recursive: bool = True
    ) -> bool:
        """Async wrapper for delete_directory."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            self.delete_directory,
            session_id, remote_path, recursive
        )
    
    async def move_file_async(
        self,
        session_id: str,
        source_path: str,
        dest_path: str
    ) -> bool:
        """Async wrapper for move_file."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            self.move_file,
            session_id, source_path, dest_path
        )
    
    async def exec_command_async(
        self,
        session_id: str,
        command: str
    ) -> Dict:
        """Async wrapper for exec_command."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            self.exec_command,
            session_id, command
        )
    
    # ============================================================
    # CLEANUP
    # ============================================================
    
    def close(self):
        """Close all connections and cleanup."""
        self._shutting_down = True
        
        for session_id in list(self._connections.keys()):
            self.disconnect(session_id)
        
        self._executor.shutdown(wait=True)
        logger.info("🔚 ParamikoHelper closed")