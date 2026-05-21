"""
ssh_server_prod.py
Production-ready SSH Git server with async/sync bridging, concurrent write safety,
graceful shutdown, and .gitignore support. Built on asyncssh + dulwich.
"""

import asyncio
import asyncssh
import fcntl
import fnmatch
import logging
import os
import signal
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Set, Tuple, List
from concurrent.futures import ThreadPoolExecutor
from dulwich.ignore import IgnoreFilterManager
from dulwich.protocol import Protocol
from dulwich.server import (
    UploadPackHandler,
    ReceivePackHandler,
)
from dulwich.repo import Repo
from dulwich.objects import Tree, Blob

logger = logging.getLogger(__name__)

# ============================================================
# Configuration
# ============================================================
class Config:
    REPO_BASE_PATH = Path("/data/git-repos")
    SSH_PORT = 2222
    SSH_HOST = "0.0.0.0"
    MAX_CONNECTIONS = 100
    COMMAND_TIMEOUT = 120  # seconds
    RATE_LIMIT_SECONDS = 60
    RATE_LIMIT_COMMANDS = 30
    PIPE_BUFFER_SIZE = 256 * 1024  # 256KB for Linux pipe buffer
    HOST_KEY_ALGORITHM = "ssh-ed25519"
    HOST_KEY_BITS = 256


# ============================================================
# Gitignore Support
# ============================================================
class GitignoreManager:
    """Manages .gitignore patterns for repositories using dulwich's ignore module."""

    def __init__(self, repo_manager: 'RepoManager'):
        self.repo_manager = repo_manager
        self._ignore_cache: Dict[str, 'IgnoreFilterManager'] = {}
        self._cache_lock = asyncio.Lock()

    def _load_ignore_manager(self, repo_name: str) -> Optional['IgnoreFilterManager']:
        """Synchronously load ignore filter manager for a repo (runs in executor)."""
        try:
            
            repo = self.repo_manager.get_repo(repo_name)
            if not repo:
                return None

            repo_path = Path(repo.path)
            ignore_manager = IgnoreFilterManager.from_repo(str(repo_path))
            return ignore_manager
        except Exception as e:
            logger.warning(f"Failed to load gitignore for {repo_name}: {e}")
            return None

    async def get_ignore_manager(self, repo_name: str) -> Optional['IgnoreFilterManager']:
        """Get cached or freshly loaded ignore filter manager."""
        async with self._cache_lock:
            if repo_name in self._ignore_cache:
                return self._ignore_cache[repo_name]

            # Load in executor to avoid blocking event loop
            loop = asyncio.get_running_loop()
            ignore_manager = await loop.run_in_executor(
                None, self._load_ignore_manager, repo_name
            )

            if ignore_manager:
                self._ignore_cache[repo_name] = ignore_manager

            return ignore_manager

    async def is_ignored(self, repo_name: str, path: str) -> bool:
        """Check if a path is ignored by .gitignore rules."""
        ignore_manager = await self.get_ignore_manager(repo_name)
        if not ignore_manager:
            return False

        # Run the potentially expensive ignore check in executor
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, ignore_manager.is_ignored, path
        )

    async def invalidate_cache(self, repo_name: str) -> None:
        """Invalidate cache for a repo (call after pushes)."""
        async with self._cache_lock:
            self._ignore_cache.pop(repo_name, None)

    def _sync_invalidate_cache(self, repo_name: str) -> None:
        """Synchronous cache invalidation for use in callbacks."""
        # Fire-and-forget async invalidate
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(self.invalidate_cache(repo_name))
        except RuntimeError:
            pass  # No running loop, ignore


# ============================================================
# Authentication
# ============================================================
class GitSSHAuthServer(asyncssh.SSHServer):
    """SSH authentication using public keys with hot-reload support."""

    def __init__(self, authorized_keys_path: Optional[str] = None):
        self._authorized_keys_path = authorized_keys_path
        self._authorized_keys: Set[str] = set()
        self._keys_mtime: float = 0.0
        self._rate_limits: Dict[str, list] = {}
        self._rate_limit_lock = asyncio.Lock()
        self._keys_lock = asyncio.Lock()

        # Initial load
        self._sync_load_keys()

    def _sync_load_keys(self) -> None:
        """Synchronous key loading (called from __init__)."""
        if not self._authorized_keys_path or not os.path.exists(self._authorized_keys_path):
            logger.warning(f"Authorized keys file not found: {self._authorized_keys_path}")
            return

        keys = set()
        try:
            with open(self._authorized_keys_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    try:
                        key = asyncssh.import_public_key(line)
                        keys.add(key.export_public_key('openssh').decode().strip())
                    except Exception as e:
                        logger.debug(f"Skipping malformed key line: {e}")

            self._authorized_keys = keys
            self._keys_mtime = os.path.getmtime(self._authorized_keys_path)
            logger.info(f"Loaded {len(keys)} authorized keys")
        except Exception as e:
            logger.error(f"Failed to load authorized keys: {e}")

    async def _check_reload_keys(self) -> None:
        """Hot-reload keys if file changed."""
        if not self._authorized_keys_path:
            return

        async with self._keys_lock:
            try:
                current_mtime = os.path.getmtime(self._authorized_keys_path)
                if current_mtime > self._keys_mtime:
                    logger.info("Reloading authorized keys...")
                    self._sync_load_keys()
            except OSError:
                pass

    async def check_rate_limit(self, username: str) -> bool:
        """Check if user exceeded rate limit."""
        async with self._rate_limit_lock:
            now = time.time()
            if username not in self._rate_limits:
                self._rate_limits[username] = []

            # Prune old entries
            self._rate_limits[username] = [
                t for t in self._rate_limits[username]
                if now - t < Config.RATE_LIMIT_SECONDS
            ]

            if len(self._rate_limits[username]) >= Config.RATE_LIMIT_COMMANDS:
                return False

            self._rate_limits[username].append(now)
            return True

    async def check_publickey_auth(self, username: str, key) -> bool:
        """Authenticate user by matching public key against authorized list."""
        # Check rate limit first
        if not await self.check_rate_limit(username):
            logger.warning(f"Rate limit exceeded for {username}")
            return False

        # Hot-reload keys if needed
        await self._check_reload_keys()

        try:
            key_str = key.export_public_key('openssh').decode().strip()
            async with self._keys_lock:
                if key_str in self._authorized_keys:
                    logger.info(f"✅ Authenticated user: {username}")
                    return True
        except Exception as e:
            logger.error(f"Auth error processing key: {e}")

        logger.warning(f"❌ Auth failed for user: {username}")
        return False

    def connection_made(self, conn):
        self.conn = conn
        peername = conn.get_extra_info('peername')
        logger.info(f"SSH connection from {peername}")

    def connection_lost(self, exc):
        if exc:
            logger.error(f"SSH connection error: {exc}")
        else:
            logger.info("SSH connection closed cleanly")


# ============================================================
# Repository Management with Write Locking
# ============================================================
class RepoManager:
    """Thread-safe repository manager with per-repo write locks."""

    def __init__(self, repo_base_path: Path):
        self.repo_base_path = repo_base_path
        self._repo_locks: Dict[str, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=min(32, (os.cpu_count() or 1) * 4),
            thread_name_prefix="git_ssh_"
        )

    def _sanitize_repo_name(self, repo_name: str) -> Optional[str]:
        """Sanitize and validate repository name."""
        repo_name = repo_name.strip().strip('"').lstrip('/')

        if '..' in repo_name or repo_name.startswith('/'):
            logger.warning(f"Invalid repo name (path traversal): {repo_name}")
            return None

        if not repo_name.endswith('.git'):
            repo_name += '.git'

        return repo_name

    def _get_repo_path(self, repo_name: str) -> Path:
        """Get absolute path for repository."""
        return self.repo_base_path / repo_name

    def repo_exists(self, repo_name: str) -> bool:
        """Check if repository exists."""
        sanitized = self._sanitize_repo_name(repo_name)
        if not sanitized:
            return False
        return self._get_repo_path(sanitized).exists()

    def get_repo(self, repo_name: str) -> Optional[Repo]:
        """Open existing repository. Returns None if not found."""
        sanitized = self._sanitize_repo_name(repo_name)
        if not sanitized:
            return None

        repo_path = self._get_repo_path(sanitized)
        if not repo_path.exists():
            return None

        try:
            return Repo(str(repo_path))
        except Exception as e:
            logger.error(f"Failed to open repo {repo_name}: {e}")
            return None

    def create_repo(self, repo_name: str) -> Optional[Repo]:
        """Create new bare repository. Returns existing if already present."""
        sanitized = self._sanitize_repo_name(repo_name)
        if not sanitized:
            return None

        repo_path = self._get_repo_path(sanitized)

        if repo_path.exists():
            logger.info(f"Repository already exists: {repo_path}")
            try:
                return Repo(str(repo_path))
            except Exception as e:
                logger.error(f"Failed to open existing repo: {e}")
                return None

        try:
            logger.info(f"Creating new bare repository: {repo_path}")
            repo_path.mkdir(parents=True, exist_ok=True)
            return Repo.init_bare(str(repo_path))
        except Exception as e:
            logger.error(f"Failed to create repo: {e}")
            return None

    async def get_repo_lock(self, repo_name: str) -> asyncio.Lock:
        """Get or create per-repo lock."""
        sanitized = self._sanitize_repo_name(repo_name)
        if not sanitized:
            raise ValueError(f"Invalid repo name: {repo_name}")

        async with self._locks_lock:
            if sanitized not in self._repo_locks:
                self._repo_locks[sanitized] = asyncio.Lock()
            return self._repo_locks[sanitized]

    def close(self):
        """Cleanup resources."""
        self._executor.shutdown(wait=True)


# ============================================================
# Pipe Buffer Management
# ============================================================
def set_pipe_size(fd: int, size: int = Config.PIPE_BUFFER_SIZE) -> None:
    """Increase OS pipe buffer size to prevent deadlocks."""
    try:
        # Linux-specific: F_SETPIPE_SZ
        fcntl.fcntl(fd, fcntl.F_SETPIPE_SZ, size)
    except (OSError, AttributeError):
        # Not supported on this platform, ignore
        pass


# ============================================================
# File Listing with Gitignore Support (Blocking IO in Executor)
# ============================================================
class RepoFileLister:
    """Lists repository files respecting .gitignore, with all blocking work offloaded to executor."""

    def __init__(self, repo_manager: RepoManager, ignore_manager: GitignoreManager):
        self.repo_manager = repo_manager
        self.ignore_manager = ignore_manager

    def _sync_list_tree_entries(self, repo_name: str, ref: str = b"HEAD") -> List[Tuple[str, int, bytes]]:
        """Synchronous tree traversal - runs in thread pool."""
        repo = self.repo_manager.get_repo(repo_name)
        if not repo:
            return []

        results = []
        try:
            # Resolve ref to tree
            if ref == b"HEAD":
                ref = repo.refs[b"HEAD"]

            commit = repo[ref]
            tree = repo[commit.tree]

            # BFS traversal
            stack = [(b"", tree)]
            while stack:
                prefix, current_tree = stack.pop()

                for name, mode, sha in current_tree.iteritems():
                    full_path = (prefix + b"/" + name) if prefix else name
                    full_path_str = full_path.decode('utf-8', errors='replace')

                    if mode == 0o040000:  # Directory
                        subtree = repo[sha]
                        stack.append((full_path, subtree))
                    else:
                        results.append((full_path_str, mode, sha))

        except Exception as e:
            logger.error(f"Error listing tree for {repo_name}: {e}")

        return results

    def _sync_read_blob_content(self, repo_name: str, sha: bytes) -> Optional[bytes]:
        """Synchronous blob read - runs in thread pool."""
        repo = self.repo_manager.get_repo(repo_name)
        if not repo:
            return None

        try:
            blob = repo[sha]
            if isinstance(blob, Blob):
                return blob.as_raw_string()
            return None
        except Exception as e:
            logger.error(f"Error reading blob in {repo_name}: {e}")
            return None

    async def list_branch_files(self, repo_name: str, ref: str = b"HEAD", 
                                 respect_gitignore: bool = True) -> List[Tuple[str, int, bytes]]:
        """Async wrapper: list files in a branch, optionally filtering by .gitignore."""
        loop = asyncio.get_running_loop()

        # Run blocking tree traversal in executor
        entries = await loop.run_in_executor(
            None, self._sync_list_tree_entries, repo_name, ref
        )

        if not respect_gitignore:
            return entries

        # Filter by gitignore (also runs blocking checks in executor)
        filtered = []
        for path_str, mode, sha in entries:
            is_ignored = await self.ignore_manager.is_ignored(repo_name, path_str)
            if not is_ignored:
                filtered.append((path_str, mode, sha))

        return filtered

    async def get_file_content(self, repo_name: str, sha: bytes) -> Optional[bytes]:
        """Async wrapper: read blob content via executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._sync_read_blob_content, repo_name, sha
        )


# ============================================================
# Diff Utilities (Pure CPU Work - Synchronous)
# ============================================================
def diff_committed_vs_working(repo_name: str, repo_manager: RepoManager) -> Dict[str, any]:
    """Pure synchronous CPU work: diff committed state vs working tree.

    This is NOT async - it performs pure computation with zero IO waits.
    Call via loop.run_in_executor() from async code.
    """
    repo = repo_manager.get_repo(repo_name)
    if not repo:
        return {"error": "Repository not found"}

    try:
        from dulwich.porcelain import status

        # status() does blocking IO internally - this entire function should run in executor
        repo_status = status(repo)

        return {
            "staged": {
                "add": [p.decode('utf-8', errors='replace') for p in repo_status.staged['add']],
                "delete": [p.decode('utf-8', errors='replace') for p in repo_status.staged['delete']],
                "modify": [p.decode('utf-8', errors='replace') for p in repo_status.staged['modify']],
            },
            "unstaged": [p.decode('utf-8', errors='replace') for p in repo_status.unstaged],
            "untracked": [p.decode('utf-8', errors='replace') for p in repo_status.untracked],
        }
    except Exception as e:
        logger.error(f"Diff error for {repo_name}: {e}")
        return {"error": str(e)}


# ============================================================
# Git Protocol Handlers (Threaded OS-Pipe Bridge)
# ============================================================
class GitProtocolHandler:
    """Handles Git protocol by bridging asyncssh to synchronous Dulwich via OS pipes."""

    def __init__(self, repo_manager: RepoManager, ignore_manager: GitignoreManager):
        self.repo_manager = repo_manager
        self.ignore_manager = ignore_manager

    async def _pump_async_to_sync(self, async_reader, sync_fd, stop_event: threading.Event):
        """Read from asyncssh client, write to synchronous OS pipe."""
        try:
            with os.fdopen(sync_fd, 'wb', closefd=True) as f:
                while not stop_event.is_set():
                    try:
                        data = await asyncio.wait_for(
                            async_reader.read(65536),
                            timeout=1.0
                        )
                        if not data:
                            break
                        await asyncio.to_thread(f.write, data)
                        await asyncio.to_thread(f.flush)
                    except asyncio.TimeoutError:
                        continue
        except Exception as e:
            logger.debug(f"Async->Sync pump closed: {e}")

    async def _pump_sync_to_async(self, sync_fd, async_writer, stop_event: threading.Event):
        """Read from synchronous OS pipe, write to asyncssh client."""
        try:
            with os.fdopen(sync_fd, 'rb', closefd=True) as f:
                while not stop_event.is_set():
                    try:
                        data = await asyncio.wait_for(
                            asyncio.to_thread(f.read, 65536),
                            timeout=1.0
                        )
                        if not data:
                            break
                        async_writer.write(data)
                        await async_writer.drain()
                    except asyncio.TimeoutError:
                        continue
        except Exception as e:
            logger.debug(f"Sync->Async pump closed: {e}")
        finally:
            if hasattr(async_writer, 'close'):
                async_writer.close()

    def _run_dulwich_thread(self, handler_class, repo_path: str, 
                            r_fd: int, w_fd: int, service_name: str,
                            stop_event: threading.Event):
        """Runs the fully synchronous Dulwich handler inside a background thread."""
        try:
            repo = Repo(repo_path)

            with os.fdopen(r_fd, 'rb', closefd=True) as f_in, \
                 os.fdopen(w_fd, 'wb', closefd=True) as f_out:

                # Write Git service header
                header = f"001e# service={service_name}\n0000".encode()
                f_out.write(header)
                f_out.flush()

                # Bind Protocol to file descriptors
                protocol = Protocol(f_in.read, f_out.write)
                handler = handler_class(protocol, repo, None)
                handler.handle()

        except Exception as e:
            logger.error(f"Dulwich Thread Error: {e}")
        finally:
            stop_event.set()

    async def handle_git_command(self, handler_class, service_name: str, 
                                  repo_name: str, reader, writer,
                                  is_write: bool = False) -> bool:
        """
        Main orchestrator for bridging the asyncssh session to Dulwich.

        Args:
            handler_class: UploadPackHandler or ReceivePackHandler
            service_name: 'git-upload-pack' or 'git-receive-pack'
            repo_name: Repository name from SSH command
            reader: asyncssh stream reader
            writer: asyncssh stream writer
            is_write: True for receive-pack (requires write lock)
        """
        # Get or create repo lock
        repo_lock = await self.repo_manager.get_repo_lock(repo_name)

        # For write operations, acquire exclusive lock
        if is_write:
            async with repo_lock:
                result = await self._handle_git_command_unlocked(
                    handler_class, service_name, repo_name, reader, writer
                )
                # Invalidate gitignore cache after writes
                await self.ignore_manager.invalidate_cache(repo_name)
                return result
        else:
            # Read operations can proceed concurrently
            return await self._handle_git_command_unlocked(
                handler_class, service_name, repo_name, reader, writer
            )

    async def _handle_git_command_unlocked(self, handler_class, service_name: str,
                                            repo_name: str, reader, writer) -> bool:
        """Internal handler without lock management."""
        # Open existing repo (do NOT auto-create for reads)
        repo = self.repo_manager.get_repo(repo_name)
        if not repo:
            writer.write(b"ERR Repository not found or invalid path\n")
            await writer.drain()
            return False

        # Create OS-level pipes with increased buffer size
        r_in, w_in = os.pipe()   # Client -> Dulwich
        r_out, w_out = os.pipe() # Dulwich -> Client

        # Increase pipe buffer sizes to reduce deadlock risk
        set_pipe_size(w_in)
        set_pipe_size(r_out)

        # Stop event for coordinated shutdown
        stop_event = threading.Event()

        # Spawn Dulwich in a background thread
        thread = threading.Thread(
            target=self._run_dulwich_thread,
            args=(handler_class, repo.path, r_in, w_out, service_name, stop_event),
            daemon=False,  # Non-daemon for clean shutdown
            name=f"dulwich-{service_name}-{repo_name}"
        )
        thread.start()

        # Run I/O pump tasks concurrently
        task_in = asyncio.create_task(
            self._pump_async_to_sync(reader, w_in, stop_event),
            name=f"pump-in-{repo_name}"
        )
        task_out = asyncio.create_task(
            self._pump_sync_to_async(r_out, writer, stop_event),
            name=f"pump-out-{repo_name}"
        )

        try:
            # Wait for completion with timeout
            await asyncio.wait_for(
                asyncio.gather(task_in, task_out, return_exceptions=True),
                timeout=Config.COMMAND_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.error(f"Command timeout for {repo_name}")
            writer.write(b"ERR Command timed out\n")
            await writer.drain()
            return False
        finally:
            # Signal stop
            stop_event.set()

            # Cancel remaining tasks
            for task in [task_in, task_out]:
                if not task.done():
                    task.cancel()

            # Wait for thread with timeout
            thread.join(timeout=5.0)
            if thread.is_alive():
                logger.warning(f"Dulwich thread did not terminate cleanly")

        logger.info(f"✅ {service_name} completed for {repo_name}")
        return True


# ============================================================
# SSH Session Handler
# ============================================================
class GitSSHSession(asyncssh.SSHServerSession):
    """Handles each SSH session."""

    def __init__(self, repo_manager: RepoManager, ignore_manager: GitignoreManager):
        self.handler = GitProtocolHandler(repo_manager, ignore_manager)
        self._command = None
        self._reader = None
        self._writer = None
        self._chan = None

    def connection_made(self, chan):
        self._chan = chan
        self._reader = chan.get_reader()
        self._writer = chan.get_writer()

    def shell_requested(self):
        """Shell access rejected."""
        return False

    def exec_requested(self, command: str):
        """Command execution requested."""
        self._command = command.strip()
        logger.info(f"Exec requested: {self._command}")

        parts = self._command.split(maxsplit=1)
        if not parts:
            self._writer.write(b"ERR Unknown command\n")
            return False

        cmd = parts[0]
        repo_name = parts[1] if len(parts) > 1 else ""

        if cmd == 'git-upload-pack':
            asyncio.create_task(
                self._run_handler(UploadPackHandler, cmd, repo_name, is_write=False)
            )
        elif cmd == 'git-receive-pack':
            asyncio.create_task(
                self._run_handler(ReceivePackHandler, cmd, repo_name, is_write=True)
            )
        else:
            self._writer.write(f"ERR Unknown command: {cmd}\n".encode())
            return False

        return True

    async def _run_handler(self, handler_class, service_name, repo_name, is_write: bool):
        try:
            success = await self.handler.handle_git_command(
                handler_class, service_name, repo_name,
                self._reader, self._writer, is_write=is_write
            )
            if not success:
                self._chan.exit(1)
            else:
                self._chan.exit(0)
        except Exception as e:
            logger.error(f"Handler error: {e}")
            self._writer.write(f"ERR Internal error: {e}\n".encode())
            await self._writer.drain()
            self._chan.exit(1)


# ============================================================
# Server Lifecycle Management
# ============================================================
class GitSSHServer:
    """Production SSH server with graceful shutdown."""

    def __init__(self):
        self._server = None
        self._repo_manager: Optional[RepoManager] = None
        self._ignore_manager: Optional[GitignoreManager] = None
        self._shutdown_event = asyncio.Event()
        self._sessions: Set[GitSSHSession] = set()
        self._sessions_lock = asyncio.Lock()

    async def start(
        self,
        host: str = Config.SSH_HOST,
        port: int = Config.SSH_PORT,
        host_key_path: str = "ssh_host_key",
        authorized_keys_path: str = "authorized_keys",
        repo_base_path: Optional[str] = None,
    ) -> None:
        """Start the production SSH server."""

        repo_path = Path(repo_base_path) if repo_base_path else Config.REPO_BASE_PATH
        repo_path.mkdir(parents=True, exist_ok=True)

        self._repo_manager = RepoManager(repo_path)
        self._ignore_manager = GitignoreManager(self._repo_manager)

        # Generate or load host key
        await self._ensure_host_key(host_key_path)

        # Setup signal handlers for graceful shutdown
        self._setup_signal_handlers()

        # Create server
        def session_factory():
            session = GitSSHSession(self._repo_manager, self._ignore_manager)
            asyncio.create_task(self._track_session(session))
            return session

        try:
            self._server = await asyncssh.create_server(
                lambda: GitSSHAuthServer(authorized_keys_path),
                host,
                port,
                server_host_keys=[host_key_path],
                session_factory=session_factory,
                max_open_connections=Config.MAX_CONNECTIONS,
                keepalive_interval=30,
                keepalive_count_max=3,
            )

            logger.info(f"🚀 Git SSH Server running on {host}:{port}")
            logger.info(f"   Repository base: {repo_path}")
            logger.info(f"   Host key: {host_key_path}")

        except Exception as e:
            logger.error(f"Failed to start SSH server: {e}")
            raise

    async def _track_session(self, session: GitSSHSession):
        """Track active sessions for graceful shutdown."""
        async with self._sessions_lock:
            self._sessions.add(session)

    async def _ensure_host_key(self, host_key_path: str) -> None:
        """Generate Ed25519 host key if not exists."""
        if not os.path.exists(host_key_path):
            logger.info(f"Generating {Config.HOST_KEY_ALGORITHM} host key: {host_key_path}")
            private_key = asyncssh.generate_private_key(
                Config.HOST_KEY_ALGORITHM,
                comment="git-ssh-server"
            )
            asyncssh.write_private_key(private_key, host_key_path)

            # Also write public key for convenience
            pub_path = f"{host_key_path}.pub"
            with open(pub_path, 'w') as f:
                f.write(private_key.export_public_key('openssh').decode())
            logger.info(f"Host public key written to: {pub_path}")

    def _setup_signal_handlers(self):
        """Setup graceful shutdown on SIGTERM/SIGINT.

        FIX: Use asyncio.get_running_loop() instead of deprecated get_event_loop().
        This method is called from within start() which is async, so a loop is guaranteed running.
        """
        loop = asyncio.get_running_loop()  # FIX #1: Was get_event_loop()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("🛑 Shutting down Git SSH Server...")
        self._shutdown_event.set()

        if self._server:
            self._server.close()
            await self._server.wait_closed()

        # Close repo manager
        if self._repo_manager:
            self._repo_manager.close()

        logger.info("✅ Server shutdown complete")

    async def serve_forever(self):
        """Run until shutdown signal."""
        await self._shutdown_event.wait()


# ============================================================
# Convenience Functions
# ============================================================
async def start_ssh_server(
    host: str = Config.SSH_HOST,
    port: int = Config.SSH_PORT,
    host_key_path: str = "ssh_host_key",
    authorized_keys_path: str = "authorized_keys",
    repo_base_path: str = None,
) -> GitSSHServer:
    """Start server and return handle for management."""
    server = GitSSHServer()
    await server.start(
        host=host,
        port=port,
        host_key_path=host_key_path,
        authorized_keys_path=authorized_keys_path,
        repo_base_path=repo_base_path,
    )
    return server


# ============================================================
# Entry Point
# ============================================================
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    async def main():
        server = await start_ssh_server()
        try:
            await server.serve_forever()
        except KeyboardInterrupt:
            await server.shutdown()

    asyncio.run(main())