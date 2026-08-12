import os
import difflib
import asyncio
import time
import aiofiles
import mimetypes
import shutil
import fnmatch
from typing import List, Optional, Tuple, Any, Dict
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from dulwich.objects import Blob, Commit, Tree
from dulwich.repo import Repo
from dulwich.diff_tree import tree_changes
from App.core.LoggingInit import get_core_logger
from App.core.settings import settings
from pathlib import Path

logger = get_core_logger(__name__)

# Constants for production safety
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
CHUNK_SIZE = 64 * 1024  # 64KB
DEFAULT_IGNORE = [
    ".git",
    "__pycache__",
    "*.pyc",
    ".env",
    "node_modules",
    "venv",
    ".vscode",
]


class GitCore:
    def __init__(self, max_repos: int = 100):
        try:
            self.main_repo_path = settings.REPO_PATH
            self._start_time = time.time()

            if not os.path.exists(self.main_repo_path):
                os.makedirs(self.main_repo_path, exist_ok=True)

            # Configuration
            self.config = {
                "max_repos": max_repos,
                "max_file_size": 50 * 1024 * 1024,  # 50MB
                "chunk_size": 64 * 1024,
                "cache_limit": 100000,
                "author": b"GitCore <gitcore@local>",
                "timeouts": {"walk": 30.0, "git_ops": 20.0, "commit": 60.0},
            }

            # Multi-repo management
            self.repos: OrderedDict[str, Repo] = OrderedDict()
            self.locks: Dict[str, asyncio.Lock] = {}
            self._manager_lock = asyncio.Lock()
            self.last_repo_name: Optional[str] = None

            # Metadata cache with LRU eviction
            self._metadata_cache: OrderedDict[str, Tuple[int, int, bytes]] = (
                OrderedDict()
            )

            # Metrics
            self.metrics = {
                "commits": 0,
                "status_checks": 0,
                "cache_hits": 0,
                "cache_misses": 0,
                "errors": 0,
            }

            # ✅ FIXED: ThreadPool with proper naming
            self.executor = ThreadPoolExecutor(
                max_workers=min(32, (os.cpu_count() or 1) * 4),
                thread_name_prefix="GitCore"
            )

            logger.info(
                f"GitCore Enterprise 2.0 initialized (Start Time: {time.ctime(self._start_time)})"
            )
        except Exception as e:
            logger.error(f"Failed to initialize GitCore: {e}")
            raise RuntimeError(f"Critical initialization failure: {e}")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @property
    def repo(self) -> Optional[Repo]:
        """Compatibility property for legacy tests."""
        if not self.last_repo_name:
            return None
        return self.repos.get(self.last_repo_name)

    def _get_lock(self, repo_name: str) -> asyncio.Lock:
        if repo_name not in self.locks:
            self.locks[repo_name] = asyncio.Lock()
        return self.locks[repo_name]

    # ✅ FIXED: Double-check locking to avoid race conditions
    async def get_repo(self, repo_name: str) -> Repo:
        """Get or initialize a repository handle with LRU eviction."""
        # Fast path: check without lock
        if repo_name in self.repos:
            async with self._manager_lock:
                self.repos.move_to_end(repo_name)
                return self.repos[repo_name]

        repo_path = os.path.join(self.main_repo_path, repo_name)
        if not os.path.exists(os.path.join(repo_path, ".git")):
            raise FileNotFoundError(f"Repository {repo_name} not initialized")

        # Slow path: lock and double-check
        async with self._manager_lock:
            # Double-check after acquiring lock
            if repo_name in self.repos:
                self.repos.move_to_end(repo_name)
                return self.repos[repo_name]

            # Evict LRU if full
            if len(self.repos) >= self.config["max_repos"]:
                oldest_name, oldest_repo = self.repos.popitem(last=False)
                oldest_repo.close()
                logger.debug(f"Evicted {oldest_name} from repo cache")

            repo = Repo(repo_path)
            self.repos[repo_name] = repo
            self.last_repo_name = repo_name
            return repo

    # ✅ FIXED: Using self.executor instead of None
    async def init_git(self, repo_name: str, branch_name: str = "main"):
        """Initialize or open a Git repository."""
        repo_path = os.path.abspath(os.path.join(self.main_repo_path, repo_name))
        os.makedirs(repo_path, exist_ok=True)

        async with self._get_lock(repo_name):
            def _init_sync():
                git_path = os.path.join(repo_path, ".git")
                if not os.path.exists(git_path):
                    return Repo.init(path=repo_path, mkdir=False)
                return Repo(repo_path)

            loop = asyncio.get_running_loop()
            # ✅ FIXED: Use self.executor
            repo = await loop.run_in_executor(self.executor, _init_sync)

            async with self._manager_lock:
                self.repos[repo_name] = repo
                self.last_repo_name = repo_name

            # Setup initial branch
            branch_ref = f"refs/heads/{branch_name}".encode()

            def _setup_branch():
                if branch_ref not in repo.refs:
                    try:
                        head = repo.head()
                        repo.refs[branch_ref] = head
                    except KeyError:
                        pass  # New repo, no commits yet
                repo.refs.set_symbolic_ref(b"HEAD", branch_ref)

            # ✅ FIXED: Use self.executor
            await loop.run_in_executor(self.executor, _setup_branch)
            logger.info(f"✅ Repository '{repo_name}' ready at {repo_path}")
            return {"success": True, "repo_path": repo_path}

    # ✅ FIXED: Using self.executor instead of None
    async def create_branch(
        self, repo_name: str, branch_name: str, branch_from: str = "main"
    ):
        """Create a new branch from an existing branch."""
        repo = await self.get_repo(repo_name)
        async with self._get_lock(repo_name):
            new_ref = f"refs/heads/{branch_name}".encode()
            source_ref = f"refs/heads/{branch_from}".encode()

            if new_ref in repo.refs:
                raise ValueError(f"Branch '{branch_name}' already exists")

            if source_ref not in repo.refs:
                raise ValueError(f"Source branch '{branch_from}' not found")

            def _git_operations():
                current_commit_sha = repo.refs[source_ref]
                repo.refs[new_ref] = current_commit_sha
                repo.refs.set_symbolic_ref(b"HEAD", new_ref)
                return current_commit_sha

            loop = asyncio.get_running_loop()
            # ✅ FIXED: Use self.executor
            current_commit_sha = await loop.run_in_executor(self.executor, _git_operations)
            logger.info(f"✅ Created branch '{branch_name}' in '{repo_name}'")
            return {
                "success": True,
                "branch": branch_name,
                "commit": current_commit_sha.hex()[:8],
            }

    # ✅ FIXED: Using self.executor instead of None
    async def delete_branch(
        self, repo_name: str, branch_name: str, force: bool = False
    ):
        """Delete a branch from a specific repository."""
        repo = await self.get_repo(repo_name)
        async with self._get_lock(repo_name):
            branch_ref = f"refs/heads/{branch_name}".encode()

            if branch_ref not in repo.refs:
                raise ValueError(f"Branch '{branch_name}' not found")

            # Check if trying to delete current branch
            current_head = repo.refs.follow(b"HEAD")[0][0]
            if current_head == branch_ref and not force:
                raise ValueError(f"Cannot delete current branch '{branch_name}'")

            def _delete():
                del repo.refs[branch_ref]
                return True

            loop = asyncio.get_running_loop()
            # ✅ FIXED: Use self.executor
            await loop.run_in_executor(self.executor, _delete)
            logger.info(f"✅ Deleted branch '{branch_name}' in '{repo_name}'")
            return {"success": True, "branch": branch_name}

    async def _load_gitignore(self, repo_path: str) -> List[str]:
        """Load .gitignore patterns from disk."""
        patterns = list(DEFAULT_IGNORE)
        gitignore_path = os.path.join(repo_path, ".gitignore")
        if os.path.exists(gitignore_path):
            try:
                async with aiofiles.open(gitignore_path, "r") as f:
                    content = await f.read()
                    patterns.extend(
                        [
                            p.strip()
                            for p in content.splitlines()
                            if p.strip() and not p.startswith("#")
                        ]
                    )
            except Exception as e:
                logger.warning(f"Failed to load .gitignore from {repo_path}: {e}")
        return patterns

    def _should_ignore(self, name: str, patterns: List[str]) -> bool:
        """Check if a file or directory should be ignored based on patterns."""
        for pattern in patterns:
            if fnmatch.fnmatch(name, pattern):
                return True
        return False

    # ✅ Already using self.executor (correct)
    async def dir_walk(self, dir_path: str) -> dict:
        """Recursively walk directory with offloading and .gitignore support."""
        loop = asyncio.get_running_loop()
        patterns = await self._load_gitignore(dir_path)

        def _walk():
            tree = {}
            for root, dirs, files in os.walk(dir_path):
                # Filter directories in-place
                dirs[:] = [d for d in dirs if not self._should_ignore(d, patterns)]

                rel_path = os.path.relpath(root, dir_path)
                if rel_path == ".":
                    rel_path = ""

                current_level = tree
                if rel_path:
                    parts = rel_path.split(os.sep)
                    for part in parts:
                        if part not in current_level:
                            current_level[part] = {}
                        current_level = current_level[part]

                for file in files:
                    if self._should_ignore(file, patterns):
                        continue

                    file_full_path = os.path.join(root, file)
                    try:
                        file_stat = os.stat(file_full_path)
                        mimetype, _ = mimetypes.guess_type(file_full_path)

                        current_level[file] = {
                            "mimetype": mimetype or "application/octet-stream",
                            "size": file_stat.st_size,
                            "full_path": file_full_path,
                            "name": file,
                            "type": "file",
                            "mtime": file_stat.st_mtime_ns,
                        }
                    except (FileNotFoundError, PermissionError):
                        continue
            return tree

        return await loop.run_in_executor(self.executor, _walk)

    # ✅ Already using self.executor (correct)
    async def traverse_tree(
        self,
        data: dict,
        repo: Repo,
        current_tree: Tree = None,
        path: str = "",
        base_tree: Optional[Tree] = None,
    ) -> Tree:
        """Traverse and create Git objects with Metadata Caching and safety guards."""
        if current_tree is None:
            current_tree = Tree()

        loop = asyncio.get_running_loop()

        for key, value in data.items():
            encoded_key = key.encode()

            if "type" in value and value.get("type") == "file":
                file_path = value.get("full_path")
                file_size = value.get("size", 0)
                file_mtime = value.get("mtime", 0)

                # 1. METADATA CACHE OPTIMIZATION (Fastest)
                if file_path in self._metadata_cache:
                    cached_mtime, cached_size, cached_sha = self._metadata_cache[
                        file_path
                    ]
                    if cached_mtime == file_mtime and cached_size == file_size:
                        self.metrics["cache_hits"] += 1
                        current_tree.add(encoded_key, 0o100644, cached_sha)
                        # Refresh LRU position
                        self._metadata_cache.move_to_end(file_path)
                        continue

                self.metrics["cache_misses"] += 1

                # 2. BASE TREE STAT OPTIMIZATION (Secondary)
                if base_tree and encoded_key in base_tree:
                    mode, sha = base_tree[encoded_key]
                    if mode == 0o100644:
                        try:
                            if file_size == repo[sha].raw_length():
                                current_tree.add(encoded_key, 0o100644, sha)
                                self._update_metadata_cache(
                                    file_path, file_mtime, file_size, sha
                                )
                                continue
                        except KeyError:
                            pass

                def _process_file():
                    if file_size > self.config["max_file_size"]:
                        logger.warning(f"Skipping oversized file: {file_path}")
                        return None

                    with open(file_path, "rb") as f:
                        content = f.read()
                    blob = Blob.from_string(content)

                    if blob.id not in repo.object_store:
                        repo.object_store.add_object(blob)
                    return blob.id

                blob_id = await loop.run_in_executor(self.executor, _process_file)
                if blob_id:
                    current_tree.add(encoded_key, 0o100644, blob_id)
                    self._update_metadata_cache(
                        file_path, file_mtime, file_size, blob_id
                    )

            elif isinstance(value, dict) and not value:
                empty_tree = Tree()
                if empty_tree.id not in repo.object_store:
                    repo.object_store.add_object(empty_tree)
                current_tree.add(encoded_key, 0o40000, empty_tree.id)

            elif isinstance(value, dict):
                base_sub_tree = None
                if base_tree and encoded_key in base_tree:
                    mode, sha = base_tree[encoded_key]
                    if mode == 0o40000:
                        base_sub_tree = repo[sha]

                sub_tree = await self.traverse_tree(
                    value, repo, Tree(), os.path.join(path, key), base_sub_tree
                )
                if sub_tree.id not in repo.object_store:
                    repo.object_store.add_object(sub_tree)
                current_tree.add(encoded_key, 0o40000, sub_tree.id)

        return current_tree

    # ✅ Already using self.executor (correct)
    async def make_tree(
        self,
        repo: Repo,
        file_json: dict,
        current_tree: Tree = None,
        base_tree: Optional[Tree] = None,
    ) -> Tree:
        """
        Create a Git tree from the nested dict structure.
        Returns the root Tree object.
        """
        try:
            root_tree = await self.traverse_tree(
                file_json, repo, current_tree, base_tree=base_tree
            )
            return root_tree
        except Exception as e:
            logger.error(f"Failed to build git tree: {e}")
            raise RuntimeError(f"Tree construction failed: {e}")

    def _update_metadata_cache(self, path: str, mtime: int, size: int, sha: bytes):
        """Update metadata cache with LRU eviction."""
        if path in self._metadata_cache:
            self._metadata_cache.move_to_end(path)
        self._metadata_cache[path] = (mtime, size, sha)
        if len(self._metadata_cache) > self.config["cache_limit"]:
            self._metadata_cache.popitem(last=False)

    async def _create_virtual_tree_unlocked(
        self, repo: Repo, repo_name: str, base_tree: Optional[Tree] = None, dir_tree: Optional[dict] = None
    ) -> Tree:
        """Internal unlocked version of create_virtual_tree to avoid deadlocks."""
        if dir_tree is None:
            repo_path = os.path.join(self.main_repo_path, repo_name)
            dir_tree = await self.dir_walk(repo_path)
            
        git_tree = await self.make_tree(repo, dir_tree, base_tree=base_tree)
        repo.object_store.add_object(git_tree)
        return git_tree

    async def create_virtual_tree(
        self, repo_name: str, base_tree: Optional[Tree] = None
    ) -> Tree:
        """Create a virtual tree with optimized lock scope."""
        repo = await self.get_repo(repo_name)

        async def _git_ops():
            async with self._get_lock(repo_name):
                return await self._create_virtual_tree_unlocked(
                    repo, repo_name, base_tree=base_tree
                )

        return await asyncio.wait_for(
            _git_ops(), timeout=self.config["timeouts"]["walk"]
        )

    # ✅ FIXED: Using self.executor instead of None
    async def comparison(self, repo_name: str, branch_name: str = "main") -> dict:
        """Compare virtual tree with actual Git branch."""
        repo = await self.get_repo(repo_name)
        repo_path = os.path.join(self.main_repo_path, repo_name)

        # 1. Capture dir_tree FIRST so it's available in the outer scope
        dir_tree = await self.dir_walk(repo_path)

        async def _run():
            async with self._get_lock(repo_name):
                branch_ref = f"refs/heads/{branch_name}".encode()
                base_tree = None

                if branch_ref in repo.refs:
                    commit = repo[repo.refs[branch_ref]]
                    base_tree = repo[commit.tree]

                virtual_tree = await self.make_tree(repo, dir_tree, base_tree=base_tree)
                repo.object_store.add_object(virtual_tree)

                if not base_tree:
                    # INITIAL STATE: Recursively find all files in dir_tree
                    def _collect_all(d, prefix=""):
                        files = []
                        for k, v in d.items():
                            if isinstance(v, dict) and v.get("type") == "file":
                                files.append(os.path.join(prefix, k))
                            elif isinstance(v, dict):
                                files.extend(_collect_all(v, os.path.join(prefix, k)))
                        return files

                    return {
                        "added": _collect_all(dir_tree),
                        "modified": [],
                        "deleted": [],
                        "unchanged": [],
                    }

                def _compare():
                    return tree_changes(repo, base_tree.id, virtual_tree.id)

                loop = asyncio.get_running_loop()
                # ✅ FIXED: Use self.executor
                changes = await loop.run_in_executor(self.executor, _compare)

                result = {"added": [], "modified": [], "deleted": [], "unchanged": []}
                for change in changes:
                    new_path = change.new.path if getattr(change, "new", None) else None
                    old_path = change.old.path if getattr(change, "old", None) else None
                    path = (new_path or old_path).decode()
                    if change.type == b"add":
                        result["added"].append(path)
                    elif change.type == b"delete":
                        result["deleted"].append(path)
                    elif change.type == b"modify":
                        result["modified"].append(path)
                return result

        self.metrics["status_checks"] += 1
        return await asyncio.wait_for(_run(), timeout=self.config["timeouts"]["git_ops"])

    async def git_status(self, repo_name: str):
        """Show git status for a specific repository."""
        repo = await self.get_repo(repo_name)
        try:
            current_head = repo.refs.get_symrefs().get(b"HEAD")
            branch = (
                current_head.decode().replace("refs/heads/", "")
                if current_head
                else "DETACHED"
            )
        except Exception:
            branch = "DETACHED"

        diffs = await self.comparison(repo_name, branch)
        logger.info(
            f"Status for {repo_name} on {branch}: {len(diffs['added'])} added, {len(diffs['modified'])} modified"
        )
        return {"branch": branch, "changes": diffs}

    # ✅ FIXED: Using self.executor instead of None
    async def compare_branches(self, repo_name: str, source_branch: str, target_branch: str) -> dict:
        """Compare two branches directly (Target vs Source)."""
        repo = await self.get_repo(repo_name)
        
        async def _run():
            async with self._get_lock(repo_name):
                source_ref = f"refs/heads/{source_branch}".encode()
                target_ref = f"refs/heads/{target_branch}".encode()
                
                if source_ref not in repo.refs or target_ref not in repo.refs:
                    raise ValueError(f"One or both branches ({source_branch}, {target_branch}) do not exist")
                
                source_tree = repo[repo[repo.refs[source_ref]].tree]
                target_tree = repo[repo[repo.refs[target_ref]].tree]
                
                def _compare():
                    return tree_changes(repo, source_tree.id, target_tree.id)
                
                loop = asyncio.get_running_loop()
                # ✅ FIXED: Use self.executor
                changes = await loop.run_in_executor(self.executor, _compare)
                
                result = {"added": [], "modified": [], "deleted": [], "unchanged": []}
                for change in changes:
                    new_path = change.new.path if getattr(change, "new", None) else None
                    old_path = change.old.path if getattr(change, "old", None) else None
                    path = (new_path or old_path).decode()
                    if change.type == b"add":
                        result["added"].append(path)
                    elif change.type == b"delete":
                        result["deleted"].append(path)
                    elif change.type == b"modify":
                        result["modified"].append(path)
                return result

        self.metrics["status_checks"] += 1
        return await asyncio.wait_for(_run(), timeout=self.config["timeouts"]["git_ops"])

    def _perform_3way_merge(self, repo: Repo, base_tree_id: bytes, source_tree_id: bytes, target_tree_id: bytes) -> dict:
        """Core 3-way merge logic (Synchronous, run in executor)."""
        # 1. Analyze Changes
        source_changes = {c.new.path or c.old.path: c for c in tree_changes(repo, base_tree_id, source_tree_id)}
        target_changes = {c.new.path or c.old.path: c for c in tree_changes(repo, base_tree_id, target_tree_id)}
        
        # 2. Detect Conflicts
        conflicts = []
        for path in source_changes:
            if path in target_changes:
                conflicts.append(path.decode())
        
        if conflicts:
            return {"success": False, "status": "CONFLICT", "conflicting_files": conflicts}
        
        # 3. Build Merged Tree
        base_tree = repo[base_tree_id]
        merged_tree = Tree()
        
        # Build path map for easy merging
        final_entries = {entry.path: entry for entry in base_tree.items()}
        
        for path, change in source_changes.items():
            if change.type == b"delete":
                final_entries.pop(path, None)
            else:
                final_entries[path] = change.new
                
        for path, change in target_changes.items():
            if change.type == b"delete":
                final_entries.pop(path, None)
            else:
                final_entries[path] = change.new
        
        # Add to Tree object
        for path, entry in final_entries.items():
            merged_tree.add(path, entry.mode, entry.sha)
        
        repo.object_store.add_object(merged_tree)
        return {"success": True, "tree_id": merged_tree.id}

    # ✅ Already using self.executor (correct)
    async def merge_branches(self, repo_name: str, source_branch: str, target_branch: str):
        """Perform a 3-way merge between two branches."""
        repo = await self.get_repo(repo_name)
        async with self._get_lock(repo_name):
            source_commit = repo[repo.refs[f"refs/heads/{source_branch}".encode()]]
            target_commit = repo[repo.refs[f"refs/heads/{target_branch}".encode()]]
            
            from dulwich.graph import find_merge_base
            bases = find_merge_base(repo, [source_commit.id, target_commit.id])
            if not bases:
                raise RuntimeError("No common ancestor")
            
            base_commit = repo[bases[0]]
            
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(
                self.executor, 
                self._perform_3way_merge, 
                repo, base_commit.tree, source_commit.tree, target_commit.tree
            )
            
            if not res["success"]:
                return res
            
            # Create Merge Commit
            def _commit():
                commit = Commit()
                commit.tree = res["tree_id"]
                commit.parents = [target_commit.id, source_commit.id]
                commit.author = commit.committer = self.config["author"]
                commit.author_time = commit.commit_time = int(time.time())
                commit.author_timezone = commit.commit_timezone = 0
                commit.message = f"Merge branch '{source_branch}' into '{target_branch}'".encode()
                repo.object_store.add_object(commit)
                repo.refs[f"refs/heads/{target_branch}".encode()] = commit.id
                return commit.id.hex()[:8]

            loop = asyncio.get_running_loop()
            sha = await loop.run_in_executor(self.executor, _commit)
            return {"success": True, "status": "MERGED", "commit": sha}

    # ✅ Already using self.executor (correct)
    async def get_log(self, repo_name: str, branch: str = "main", limit: int = 10) -> List[dict]:
        """Get commit history for a specific branch."""
        repo = await self.get_repo(repo_name)
        async with self._get_lock(repo_name):
            try:
                branch_ref = f"refs/heads/{branch}".encode()
                
                # ✅ FIXED: Raise error if branch doesn't exist
                if branch_ref not in repo.refs:
                    raise ValueError(f"Branch '{branch}' does not exist")
                
                walker = repo.get_walker(include=[repo.refs[branch_ref]], max_entries=limit)
                
                def _process_log():
                    history = []
                    for entry in walker:
                        commit = entry.commit
                        history.append({
                            "sha": commit.id.hex(),
                            "author": commit.author.decode(),
                            "message": commit.message.decode().strip(),
                            "time": time.ctime(commit.author_time),
                            "timestamp": commit.author_time
                        })
                    return history

                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(self.executor, _process_log)
            except ValueError:
                raise
            except Exception as e:
                logger.error(f"Failed to fetch log: {e}")
                return []

    # ✅ Already using self.executor (correct)
    async def get_commit_show(self, repo_name: str, sha_hex: str) -> dict:
        """Show details and changes for a specific commit."""
        repo = await self.get_repo(repo_name)
        async with self._get_lock(repo_name):
            try:
                sha = bytes.fromhex(sha_hex)
                commit = repo[sha]
                parent_sha = commit.parents[0] if commit.parents else None
                
                changes = []
                if parent_sha:
                    parent_tree = repo[repo[parent_sha].tree].id
                    diffs = tree_changes(repo, parent_tree, commit.tree)
                    for c in diffs:
                        # ✅ FIX: Safely handle path (could be bytes or string)
                        if c.new:
                            path = c.new.path
                        elif c.old:
                            path = c.old.path
                        else:
                            path = b""
                        
                        # ✅ Convert bytes to string if needed
                        if isinstance(path, bytes):
                            path = path.decode('utf-8', errors='replace')
                        else:
                            path = str(path)
                        
                        # ✅ Convert type safely
                        if isinstance(c.type, bytes):
                            change_type = c.type.decode('utf-8', errors='replace')
                        else:
                            change_type = str(c.type)
                        
                        changes.append({
                            "path": path,
                            "type": change_type
                        })
                else:
                    # Initial commit: all files are "add"
                    def _get_files(tree_id, prefix=""):
                        files = []
                        tree = repo[tree_id]
                        for entry in tree.items():
                            # ✅ Convert entry path safely
                            if isinstance(entry.path, bytes):
                                name = entry.path.decode('utf-8', errors='replace')
                            else:
                                name = str(entry.path)
                            
                            path = os.path.join(prefix, name) if prefix else name
                            
                            if entry.mode == 0o40000:
                                files.extend(_get_files(entry.sha, path))
                            else:
                                files.append({"path": path, "type": "add"})
                        return files
                    changes = _get_files(commit.tree)

                return {
                    "sha": commit.id.hex(),
                    "author": commit.author.decode('utf-8', errors='replace') if isinstance(commit.author, bytes) else str(commit.author),
                    "message": commit.message.decode('utf-8', errors='replace').strip() if isinstance(commit.message, bytes) else str(commit.message).strip(),
                    "time": time.ctime(commit.author_time),
                    "changes": changes
                }
            except Exception as e:
                logger.error(f"Failed to show commit {sha_hex}: {e}")
                raise ValueError(f"Invalid commit or error: {e}")

    # ✅ Already using self.executor (correct)
    async def create_tag(self, repo_name: str, tag_name: str, target: str = "HEAD"):
        """Create a lightweight tag."""
        repo = await self.get_repo(repo_name)
        async with self._get_lock(repo_name):
            try:
                # Resolve target
                if target == "HEAD":
                    try:
                        _, target_sha = repo.refs.follow(b"HEAD")
                    except KeyError:
                        raise ValueError("HEAD is unborn or invalid")
                else:
                    try:
                        target_sha = bytes.fromhex(target)
                    except ValueError:
                        # Maybe it's a branch name
                        ref = f"refs/heads/{target}".encode()
                        if ref in repo.refs:
                            target_sha = repo.refs[ref]
                        else:
                            raise ValueError(f"Invalid target {target}")
                
                tag_ref = f"refs/tags/{tag_name}".encode()
                repo.refs[tag_ref] = target_sha
                logger.info(f"✅ Created tag '{tag_name}' at {target_sha.hex()[:8]}")
                return {"success": True, "tag": tag_name, "sha": target_sha.hex()[:8]}
            except Exception as e:
                logger.error(f"Failed to create tag: {e}")
                raise

    # ✅ Already using self.executor (correct)
    async def list_tags(self, repo_name: str) -> List[dict]:
        """List all tags in a repository efficiently."""
        repo = await self.get_repo(repo_name)
        async with self._get_lock(repo_name):
            tags = []
            # Access underlying dict-like interface without full copy
            for ref_name in repo.refs.keys():
                if ref_name.startswith(b"refs/tags/"):
                    sha = repo.refs[ref_name]
                    tags.append({
                        "name": ref_name.decode().replace("refs/tags/", ""),
                        "sha": sha.hex()
                    })
            return tags

    # ✅ Already using self.executor (correct)
    async def reset(self, repo_name: str, target: str, mode: str = "soft"):
        """Reset current branch to a specific commit."""
        repo = await self.get_repo(repo_name)
        async with self._get_lock(repo_name):
            try:
                # 1. Resolve target SHA
                try:
                    target_sha = bytes.fromhex(target)
                except ValueError:
                    # Check if it's a branch
                    ref = f"refs/heads/{target}".encode()
                    if ref in repo.refs:
                        target_sha = repo.refs[ref]
                    else:
                        raise ValueError(f"Invalid target {target}")
                
                _ = repo[target_sha]  # Verify existence
                
                # 2. Update Branch Ref
                current_head = repo.refs.get_symrefs().get(b"HEAD")
                if not current_head:
                    raise RuntimeError("Detached HEAD")
                
                repo.refs[current_head] = target_sha
                logger.info(f"✅ Reset {current_head.decode()} to {target_sha.hex()[:8]}")
                
            except Exception as e:
                logger.error(f"Reset failed: {e}")
                raise

        if mode == "hard":
            return await self.checkout(repo_name, target_sha.hex())
        return {"success": True, "mode": mode, "target": target_sha.hex()[:8]}

    # ✅ Already using self.executor (correct)
    async def stash_push(self, repo_name: str, message: str = "Stashed changes"):
        """
        Save current dirty state to the stash.
        NOTE: This implementation currently supports a single stash slot. 
        Pushing a new stash will fail if one already exists.
        """
        repo = await self.get_repo(repo_name)
        repo_path = os.path.join(self.main_repo_path, repo_name)
        
        # 1. Capture disk state OUTSIDE lock (snapshot before acquiring)
        dir_tree = await self.dir_walk(repo_path)
        
        async with self._get_lock(repo_name):
            # Guard inside the lock to eliminate TOCTOU race
            if b"refs/stash" in repo.refs:
                raise ValueError("A stash already exists. Pop or drop it first.")
            try:
                current_head_ref = repo.refs.follow(b"HEAD")[0][0]
                parent_sha = repo.refs[current_head_ref]
                base_tree = repo[repo[parent_sha].tree]
                
                # 2. Create tree (Inside lock but uses previously captured disk state)
                virtual_tree = await self._create_virtual_tree_unlocked(
                    repo, repo_name, base_tree=base_tree, dir_tree=dir_tree
                )
                
                def _create_stash():
                    commit = Commit()
                    commit.tree = virtual_tree.id
                    commit.parents = [parent_sha]
                    commit.author = commit.committer = self.config["author"]
                    commit.author_time = commit.commit_time = int(time.time())
                    commit.author_timezone = commit.commit_timezone = 0
                    commit.message = message.encode()
                    repo.object_store.add_object(commit)
                    repo.refs[b"refs/stash"] = commit.id
                    return commit.id.hex()[:8]

                loop = asyncio.get_running_loop()
                stash_sha = await loop.run_in_executor(self.executor, _create_stash)
            except Exception as e:
                logger.error(f"Stash failed: {e}")
                raise

        # 3. Clean disk (Checkout HEAD)
        await self.checkout(repo_name, "HEAD")
        return {"success": True, "stash_sha": stash_sha}

    # ✅ Already using self.executor (correct)
    async def stash_pop(self, repo_name: str):
        """Restore the most recent stashed state."""
        repo = await self.get_repo(repo_name)
        async with self._get_lock(repo_name):
            stash_ref = b"refs/stash"
            if stash_ref not in repo.refs:
                raise ValueError("No stashed changes found")
            
            stash_sha = repo.refs[stash_ref]
            # Delete stash ref
            del repo.refs[stash_ref]
            
        # Use checkout logic to apply stash to disk
        return await self.checkout(repo_name, stash_sha.hex())

    # ✅ Already using self.executor (correct)
    async def revert(self, repo_name: str, commit_sha: str):
        """Undo a specific commit by creating a new inverse commit."""
        repo = await self.get_repo(repo_name)
        async with self._get_lock(repo_name):
            sha = bytes.fromhex(commit_sha)
            commit_to_revert = repo[sha]
            if not commit_to_revert.parents:
                raise ValueError("Cannot revert initial commit")
            
            parent_sha = commit_to_revert.parents[0]
            current_head = repo.refs.follow(b"HEAD")[0][0]
            head_commit = repo[repo.refs[current_head]]
            
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(
                self.executor, 
                self._perform_3way_merge, 
                repo, commit_to_revert.tree, repo[parent_sha].tree, head_commit.tree
            )
            if not res["success"]:
                return res
            
            def _commit():
                commit = Commit()
                commit.tree = res["tree_id"]
                commit.parents = [head_commit.id]
                commit.author = commit.committer = self.config["author"]
                commit.author_time = commit.commit_time = int(time.time())
                commit.author_timezone = commit.commit_timezone = 0
                commit.message = f"Revert '{commit_sha[:8]}'".encode()
                repo.object_store.add_object(commit)
                repo.refs[current_head] = commit.id
                return commit.id.hex()[:8]
                
            sha_res = await loop.run_in_executor(self.executor, _commit)
            return {"success": True, "status": "REVERTED", "commit": sha_res}

    # ✅ Already using self.executor (correct)
    async def cherry_pick(self, repo_name: str, commit_sha: str):
        """Apply a specific commit to the current branch."""
        repo = await self.get_repo(repo_name)
        async with self._get_lock(repo_name):
            sha = bytes.fromhex(commit_sha)
            source_commit = repo[sha]
            if not source_commit.parents:
                raise ValueError("Cannot cherry-pick initial commit")
            
            parent_sha = source_commit.parents[0]
            current_head = repo.refs.follow(b"HEAD")[0][0]
            head_commit = repo[repo.refs[current_head]]
            
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(
                self.executor,
                self._perform_3way_merge,
                repo, repo[parent_sha].tree, source_commit.tree, head_commit.tree
            )
            if not res["success"]:
                return res
            
            def _commit():
                commit = Commit()
                commit.tree = res["tree_id"]
                commit.parents = [head_commit.id]
                commit.author = commit.committer = self.config["author"]
                commit.author_time = commit.commit_time = int(time.time())
                commit.author_timezone = commit.commit_timezone = 0
                commit.message = f"Cherry-pick '{commit_sha[:8]}': {source_commit.message.decode()}".encode()
                repo.object_store.add_object(commit)
                repo.refs[current_head] = commit.id
                return commit.id.hex()[:8]
                
            sha_res = await loop.run_in_executor(self.executor, _commit)
            return {"success": True, "status": "CHERRY_PICKED", "commit": sha_res}

    # ✅ Already using self.executor (correct)
    async def reflog(self, repo_name: str, branch: str = "main") -> List[dict]:
        """Get the reflog for a specific branch."""
        repo = await self.get_repo(repo_name)
        async with self._get_lock(repo_name):
            try:
                from dulwich.reflog import read_reflog
                repo_path = os.path.join(self.main_repo_path, repo_name)
                reflog_path = os.path.join(repo_path, ".git", "logs", "refs", "heads", branch)
                
                if not os.path.exists(reflog_path):
                    return []
                
                def _read():
                    log = []
                    with open(reflog_path, "rb") as f:
                        for entry in read_reflog(f):
                            log.append({
                                "old_sha": entry.old_sha.hex(),
                                "new_sha": entry.new_sha.hex(),
                                "message": entry.message.decode(),
                                "time": time.ctime(entry.time)
                            })
                    return log

                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(self.executor, _read)
            except Exception as e:
                logger.error(f"Reflog failed: {e}")
                return []

    # ✅ Already using self.executor (correct)
    async def create_commit(self, repo_name: str, message: str = "Auto commit"):
        """Create a commit with pre-flight disk check and deadlock-free locking."""
        repo = await self.get_repo(repo_name)

        # Pre-flight: Disk space check
        usage = shutil.disk_usage(repo.path)
        if usage.free < 100 * 1024 * 1024:
            self.metrics["errors"] += 1
            raise RuntimeError(f"Insufficient disk space for commit in {repo_name}")

        async def _run():
            async with self._get_lock(repo_name):
                # Prefer the symbolic ref (e.g. refs/heads/main) so the
                # commit updates the branch pointer, not HEAD directly.
                # Fall back to follow()[0][0] only when truly detached.
                sym = repo.refs.get_symrefs().get(b"HEAD")
                current_head = sym if sym else repo.refs.follow(b"HEAD")[0][0]
                base_tree = None

                try:
                    parent_sha = repo.refs[current_head]
                    has_parent = True
                    base_tree = repo[repo[parent_sha].tree]
                except KeyError:
                    has_parent = False

                # Call UNLOCKED version to avoid re-entry deadlock
                virtual_tree = await self._create_virtual_tree_unlocked(
                    repo, repo_name, base_tree=base_tree
                )

                def _commit_sync():
                    commit = Commit()
                    commit.tree = virtual_tree.id
                    commit.parents = [parent_sha] if has_parent else []
                    commit.author = commit.committer = self.config["author"]
                    commit.author_time = commit.commit_time = int(time.time())
                    commit.author_timezone = commit.commit_timezone = 0
                    commit.message = message.encode()

                    repo.object_store.add_object(commit)
                    repo.refs[current_head] = commit.id
                    return commit.id.hex()[:8]

                loop = asyncio.get_running_loop()
                commit_sha = await loop.run_in_executor(self.executor, _commit_sync)
                self.metrics["commits"] += 1
                return {"success": True, "commit": commit_sha}

        return await asyncio.wait_for(_run(), timeout=self.config["timeouts"]["commit"])

    # ✅ Already using self.executor (correct)
    async def checkout(self, repo_name: str, target: str, force: bool = False):
        """Switch to a branch or commit and synchronize the disk state."""
        repo = await self.get_repo(repo_name)
        repo_path = os.path.join(self.main_repo_path, repo_name)
        
        async with self._get_lock(repo_name):
            try:
                # A: Resolve Target
                if target == "HEAD":
                    try:
                        _, target_sha = repo.refs.follow(b"HEAD")
                    except KeyError:
                        raise ValueError("HEAD is unborn")
                    is_branch = False
                else:
                    ref = f"refs/heads/{target}".encode()
                    if ref in repo.refs:
                        target_sha = repo.refs[ref]
                        is_branch = True
                    else:
                        try:
                            target_sha = bytes.fromhex(target)
                            _ = repo[target_sha]
                            is_branch = False
                        except (ValueError, KeyError):
                            raise ValueError(f"Target '{target}' is not a valid branch or commit SHA")

                target_commit = repo[target_sha]
                target_tree_id = target_commit.tree
                
                # B: Update Refs
                if is_branch:
                    repo.refs.set_symbolic_ref(b"HEAD", f"refs/heads/{target}".encode())
                elif target != "HEAD":
                    repo.refs[b"HEAD"] = target_sha

                # C: Synchronize Disk
                target_tree = repo[target_tree_id]
                dir_tree = await self.dir_walk(repo_path)
                
                def _flatten(tree, prefix=""):
                    flat = {}
                    for entry in tree.items():
                        path = os.path.join(prefix, entry.path.decode()) if prefix else entry.path.decode()
                        if entry.mode == 0o40000:
                            flat.update(_flatten(repo[entry.sha], path))
                        else:
                            flat[path] = entry.sha
                    return flat
                
                target_files = _flatten(target_tree)
                
                def _get_disk_files(d, prefix=""):
                    files = []
                    for k, v in d.items():
                        path = os.path.join(prefix, k) if prefix else k
                        if isinstance(v, dict) and v.get("type") == "file":
                            files.append(path)
                        elif isinstance(v, dict):
                            files.extend(_get_disk_files(v, path))
                    return files
                
                disk_files = _get_disk_files(dir_tree)
                
                def _sync_io():
                    # Delete extra
                    for f in disk_files:
                        if f not in target_files:
                            full_f = os.path.join(repo_path, f)
                            try:
                                if os.path.isfile(full_f):
                                    os.remove(full_f)
                            except Exception:
                                pass
                    
                    # Write target
                    for rel_path, sha in target_files.items():
                        full_path = os.path.join(repo_path, rel_path)
                        os.makedirs(os.path.dirname(full_path), exist_ok=True)
                        with open(full_path, "wb") as f:
                            f.write(repo[sha].data)
                    
                    # Cleanup dirs
                    for root, dirs, files in os.walk(repo_path, topdown=False):
                        for d in dirs:
                            if d == ".git":
                                continue
                            p = os.path.join(root, d)
                            if os.path.exists(p) and not os.listdir(p):
                                try:
                                    os.rmdir(p)
                                except Exception:
                                    pass

                loop = asyncio.get_running_loop()
                await loop.run_in_executor(self.executor, _sync_io)
                self._metadata_cache.clear()
                return {"success": True, "target": target, "sha": target_sha.hex()[:8]}

            except Exception as e:
                logger.error(f"Checkout failed: {e}")
                raise

    async def health_check(self) -> Dict[str, Any]:
        """Return service health and performance metrics."""
        return {
            "status": "healthy",
            "uptime_seconds": int(time.time() - self._start_time),
            "repos_cached": len(self.repos),
            "metadata_cache_size": len(self._metadata_cache),
            "metrics": dict(self.metrics),
            "config_limits": {
                "max_file_size": self.config["max_file_size"],
                "cache_limit": self.config["cache_limit"],
            },
        }

    async def get_file_diff(self, repo_name: str, file_path: str, branch: str = "main"):
        """Get line-by-line diff for a file compared to disk."""
        repo = await self.get_repo(repo_name)
        full_path = os.path.join(repo.path, file_path)
        
        git_content = []
        async with self._get_lock(repo_name):
            try:
                branch_ref = f"refs/heads/{branch}".encode()
                commit = repo[repo.refs[branch_ref]]
                tree = repo[commit.tree]
                mode, sha = tree.lookup_path(repo.get_object, file_path.encode())
                git_content = repo[sha].data.decode().splitlines()
            except (KeyError, FileNotFoundError):
                pass
            except Exception as e:
                logger.error(f"Diff lookup failed: {e}")

        # File I/O outside the lock
        if not os.path.exists(full_path):
            disk_content = []
        else:
            async with aiofiles.open(full_path, "r", errors="replace") as f:
                disk_content = (await f.read()).splitlines()

        diff = list(difflib.unified_diff(git_content, disk_content, fromfile="git", tofile="disk"))
        return {"file": file_path, "diff": diff}

    def close(self):
        """Cleanup resources."""
        for repo in self.repos.values():
            repo.close()
        self.executor.shutdown(wait=True)
        logger.info("GitCore resources cleaned up")

    async def list_repositories(self) -> List[Dict[str, Any]]:
        """List all repositories on disk with metadata."""
        repos = []
        for name in os.listdir(self.main_repo_path):
            repo_path = os.path.join(self.main_repo_path, name)
            if os.path.isdir(repo_path) and os.path.exists(os.path.join(repo_path, ".git")):
                try:
                    repo = await self.get_repo(name)
                    head = repo.refs.get_symrefs().get(b"HEAD")
                    branch = head.decode().replace("refs/heads/", "") if head else "DETACHED"
                    repos.append({
                        "name": name,
                        "branch": branch,
                        "path": repo_path,
                        "exists": True
                    })
                except Exception:
                    repos.append({"name": name, "path": repo_path, "exists": False})
        return repos

    async def get_repository_info(self, repo_name: str) -> Dict[str, Any]:
        """Get detailed repository information."""
        repo = await self.get_repo(repo_name)
        repo_path = os.path.join(self.main_repo_path, repo_name)
        
        head = repo.refs.get_symrefs().get(b"HEAD")
        branch = head.decode().replace("refs/heads/", "") if head else "DETACHED"
        
        # Get latest commit
        try:
            commit_sha = repo.refs[f"refs/heads/{branch}".encode()]
            commit = repo[commit_sha]
            latest_commit = {
                "sha": commit.id.hex(),
                "message": commit.message.decode().strip(),
                "author": commit.author.decode(),
                "time": time.ctime(commit.author_time)
            }
        except:
            latest_commit = None
        
        return {
            "name": repo_name,
            "path": repo_path,
            "branch": branch,
            "latest_commit": latest_commit,
            "size_mb": self._get_repo_size(repo_path)
        }

    def _get_repo_size(self, repo_path: str) -> float:
        """Calculate repository size in MB."""
        total = sum(f.stat().st_size for f in Path(repo_path).rglob("*") if f.is_file())
        return round(total / (1024 * 1024), 2)

    async def delete_tag(self, repo_name: str, tag_name: str) -> Dict[str, Any]:
        """Delete a tag from repository."""
        repo = await self.get_repo(repo_name)
        async with self._get_lock(repo_name):
            tag_ref = f"refs/tags/{tag_name}".encode()
            if tag_ref not in repo.refs:
                raise ValueError(f"Tag '{tag_name}' not found")
            del repo.refs[tag_ref]
            return {"success": True, "tag": tag_name}
        
    async def list_stashes(self, repo_name: str) -> List[Dict[str, Any]]:
        """List all stashes in repository."""
        repo = await self.get_repo(repo_name)
        stashes = []
        
        # Check main stash ref
        if b"refs/stash" in repo.refs:
            sha = repo.refs[b"refs/stash"]
            commit = repo[sha]
            stashes.append({
                "index": 0,
                "sha": sha.hex(),
                "message": commit.message.decode().strip(),
                "author": commit.author.decode(),
                "time": time.ctime(commit.author_time)
            })
        return stashes
    
    async def list_files(self, repo_name: str, path: str = "", branch: str = "main") -> List[Dict[str, Any]]:
        repo = await self.get_repo(repo_name)
        async with self._get_lock(repo_name):
            branch_ref = f"refs/heads/{branch}".encode()
            if branch_ref not in repo.refs:
                raise ValueError(f"Branch '{branch}' does not exist")
            
            commit = repo[repo.refs[branch_ref]]
            tree = repo[commit.tree]
            
            files = []
            if path:
                # ✅ FIX: Strip leading slash
                if path.startswith('/'):
                    path = path.lstrip('/')
                
                try:
                    mode, sha = tree.lookup_path(repo.get_object, path.encode())
                    if mode == 0o40000:  # Directory
                        tree = repo[sha]
                    else:
                        return [{"name": path, "type": "file", "size": repo[sha].raw_length()}]
                except KeyError:
                    raise ValueError(f"Path '{path}' not found in branch '{branch}'")
            
            for entry in tree.items():
                name = entry.path.decode()
                is_dir = entry.mode == 0o40000
                files.append({
                    "name": name,
                    "type": "directory" if is_dir else "file",
                    "size": 0 if is_dir else repo[entry.sha].raw_length()
                })
            return files

    async def get_file_content(self, repo_name: str, file_path: str, branch: str = "main") -> Optional[str]:
        """Get file content from repository."""
        repo = await self.get_repo(repo_name)
        async with self._get_lock(repo_name):
            branch_ref = f"refs/heads/{branch}".encode()
            
            if branch_ref not in repo.refs:
                raise ValueError(f"Branch '{branch}' does not exist")
            
            commit = repo[repo.refs[branch_ref]]
            tree = repo[commit.tree]
            
            # ✅ Strip leading slash
            if file_path.startswith('/'):
                file_path = file_path.lstrip('/')
            
            try:
                mode, sha = tree.lookup_path(repo.get_object, file_path.encode())
                if mode == 0o40000:
                    raise ValueError(f"{file_path} is a directory")
                content = repo[sha].data
                return content.decode('utf-8', errors='replace')
            except KeyError:
                raise ValueError(f"File '{file_path}' not found in branch '{branch}'")
    # ==================== FILE UPLOAD METHODS ====================

    async def add_file(self, repo_name: str, file_path: str, content: bytes, commit_message: str = "Add file") -> Dict[str, Any]:
        """
        Add a new file or update an existing file in the repository.
        This writes to disk and creates a commit.
        """
        repo = await self.get_repo(repo_name)
        repo_path = os.path.join(self.main_repo_path, repo_name)
        
        # ✅ FIXED: Remove leading slash to prevent absolute path issue
        if file_path.startswith('/'):
            file_path = file_path.lstrip('/')
        
        # Security: Prevent path traversal (..)
        if '..' in file_path:
            raise ValueError("Invalid file path - directory traversal detected")
        
        # Build full path
        full_path = os.path.abspath(os.path.join(repo_path, file_path))
        repo_path_abs = os.path.abspath(repo_path)
        
        # Security: Ensure file is inside repo
        if not full_path.startswith(repo_path_abs + os.sep):
            raise ValueError(f"Invalid file path - must be inside repository: {file_path}")
        
        # Create directory if needed
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        # Write file
        async with aiofiles.open(full_path, "wb") as f:
            await f.write(content)
        
        # Create commit
        result = await self.create_commit(repo_name, commit_message)
        
        return {
            "success": True,
            "file_path": file_path,
            "commit": result["commit"]
        }

    async def add_files_bulk(self, repo_name: str, files: Dict[str, bytes], commit_message: str = "Add multiple files") -> Dict[str, Any]:
        repo = await self.get_repo(repo_name)
        repo_path = os.path.join(self.main_repo_path, repo_name)
        repo_path_abs = os.path.abspath(repo_path)
        
        added_files = []
        
        for file_path, content in files.items():
            # ✅ FIX: Strip leading slash
            if file_path.startswith('/'):
                file_path = file_path.lstrip('/')
            
            # ✅ FIX: Check for path traversal
            if '..' in file_path:
                raise ValueError(f"Invalid file path: {file_path} - directory traversal detected")
            
            full_path = os.path.abspath(os.path.join(repo_path, file_path))
            
            if not full_path.startswith(repo_path_abs + os.sep):

                raise ValueError(f"Invalid file path: {file_path} - must be inside repository")
            
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            
            async with aiofiles.open(full_path, "wb") as f:
                await f.write(content)
            
            added_files.append(file_path)
        
        result = await self.create_commit(repo_name, commit_message)
        
        return {
            "success": True,
            "added_files": added_files,
            "count": len(added_files),
            "commit": result["commit"]
        }

    async def delete_file(self, repo_name: str, file_path: str, commit_message: str = "Delete file") -> Dict[str, Any]:
        repo = await self.get_repo(repo_name)
        repo_path = os.path.join(self.main_repo_path, repo_name)
        repo_path_abs = os.path.abspath(repo_path)
        
        # ✅ FIX: Strip leading slash
        if file_path.startswith('/'):
            file_path = file_path.lstrip('/')
        
        # ✅ FIX: Check for path traversal
        if '..' in file_path:
            raise ValueError("Invalid file path - directory traversal detected")
        
        full_path = os.path.abspath(os.path.join(repo_path, file_path))
        
        if not full_path.startswith(repo_path_abs + os.sep):
            raise ValueError(f"Invalid file path - must be inside repository")
        
        if not os.path.exists(full_path):
            raise ValueError(f"File '{file_path}' does not exist")
        
        os.remove(full_path)
        
        # Clean up empty directories...
        dir_path = os.path.dirname(full_path)
        while dir_path != repo_path:
            try:
                if not os.listdir(dir_path):
                    os.rmdir(dir_path)
                else:
                    break
            except (OSError, PermissionError):
                break
            dir_path = os.path.dirname(dir_path)
        
        result = await self.create_commit(repo_name, commit_message)
        
        return {
            "success": True,
            "file_path": file_path,
            "commit": result["commit"]
        }

    async def move_file(self, repo_name: str, source_path: str, dest_path: str, commit_message: str = "Move file") -> Dict[str, Any]:
        repo = await self.get_repo(repo_name)
        repo_path = os.path.join(self.main_repo_path, repo_name)
        repo_path_abs = os.path.abspath(repo_path)
        
        # ✅ FIX: Strip leading slash
        if source_path.startswith('/'):
            source_path = source_path.lstrip('/')
        if dest_path.startswith('/'):
            dest_path = dest_path.lstrip('/')
        
        # ✅ FIX: Check for path traversal
        if '..' in source_path or '..' in dest_path:
            raise ValueError("Invalid path - directory traversal detected")
        
        full_source = os.path.abspath(os.path.join(repo_path, source_path))
        full_dest = os.path.abspath(os.path.join(repo_path, dest_path))
        
        if not full_source.startswith(repo_path_abs + os.sep):
            raise ValueError("Invalid source path - must be inside repository")
        if not full_dest.startswith(repo_path_abs + os.sep):
            raise ValueError("Invalid destination path - must be inside repository")
        
        if not os.path.exists(full_source):
            raise ValueError(f"Source file '{source_path}' does not exist")
        if os.path.exists(full_dest):
            raise ValueError(f"Destination file '{dest_path}' already exists")
        
        os.makedirs(os.path.dirname(full_dest), exist_ok=True)
        shutil.move(full_source, full_dest)
        
        # Clean up empty source directories...
        dir_path = os.path.dirname(full_source)
        while dir_path != repo_path:
            try:
                if not os.listdir(dir_path):
                    os.rmdir(dir_path)
                else:
                    break
            except (OSError, PermissionError):
                break
            dir_path = os.path.dirname(dir_path)
        
        result = await self.create_commit(repo_name, commit_message)
        
        return {
            "success": True,
            "source": source_path,
            "destination": dest_path,
            "commit": result["commit"]
        }

    async def delete_repo(self, repo_name: str, force: bool = False) -> Dict[str, Any]:
        """Delete a repository from disk."""
        repo_path = os.path.join(self.main_repo_path, repo_name)
        
        if not os.path.exists(repo_path):
            raise ValueError(f"Repository '{repo_name}' does not exist")
        
        # Check if it's a git repo
        if not os.path.exists(os.path.join(repo_path, ".git")):
            raise ValueError(f"'{repo_name}' is not a Git repository")
        
        # Close any open repo handles
        if repo_name in self.repos:
            self.repos[repo_name].close()
            del self.repos[repo_name]
        
        # Remove from locks
        if repo_name in self.locks:
            del self.locks[repo_name]
        
        # Delete the directory
        shutil.rmtree(repo_path)
        
        logger.info(f"✅ Deleted repository '{repo_name}'")
        return {
            "success": True,
            "repo_name": repo_name,
            "path": repo_path
        }

    async def list_branches(self, repo_name: str) -> Dict[str, Any]:
        """List all branches in a repository using pure Git."""
        repo = await self.get_repo(repo_name)
        
        branches = []
        current_branch = None
        
        # Get current branch
        try:
            head = repo.refs.get_symrefs().get(b"HEAD")
            if head:
                current_branch = head.decode().replace("refs/heads/", "")
        except Exception:
            pass
        
        # List all branches
        for ref in repo.refs.keys():
            if ref.startswith(b"refs/heads/"):
                bname = ref.decode().replace("refs/heads/", "")
                try:
                    sha = repo.refs[ref].hex()[:8]
                except Exception:
                    sha = "unknown"
                
                branches.append({
                    "name": bname,
                    "commit": sha,
                    "is_current": bname == current_branch
                })
        
        # Sort: current first, then alphabetically
        branches.sort(key=lambda x: (not x["is_current"], x["name"]))
        
        return {
            "success": True,
            "repo_name": repo_name,
            "current_branch": current_branch,
            "branches": branches,
            "count": len(branches)
        }

    async def delete_directory(self, repo_name: str, dir_path: str, commit_message: str = "Delete directory") -> Dict[str, Any]:
        """
        Delete a directory and all its contents recursively.
        """
        repo = await self.get_repo(repo_name)
        repo_path = os.path.join(self.main_repo_path, repo_name)
        repo_path_abs = os.path.abspath(repo_path)
        
        # Strip leading slash
        if dir_path.startswith('/'):
            dir_path = dir_path.lstrip('/')
        
        # Prevent path traversal
        if '..' in dir_path:
            raise ValueError("Invalid path - directory traversal detected")
        
        full_path = os.path.abspath(os.path.join(repo_path, dir_path))
        
        if not full_path.startswith(repo_path_abs + os.sep):
            raise ValueError(f"Invalid path - must be inside repository")
        
        if not os.path.exists(full_path):
            raise ValueError(f"Path '{dir_path}' does not exist")
        
        if not os.path.isdir(full_path):
            raise ValueError(f"'{dir_path}' is not a directory")
        
        # Delete directory recursively
        shutil.rmtree(full_path)
        
        # Create commit
        result = await self.create_commit(repo_name, commit_message)
        
        return {
            "success": True,
            "dir_path": dir_path,
            "commit": result["commit"]
        }


    async def delete_file_or_dir(self, repo_name: str, path: str, commit_message: str = "Delete") -> Dict[str, Any]:
        """
        Delete a file or directory (auto-detects).
        """
        repo = await self.get_repo(repo_name)
        repo_path = os.path.join(self.main_repo_path, repo_name)
        repo_path_abs = os.path.abspath(repo_path)
        
        # Strip leading slash
        if path.startswith('/'):
            path = path.lstrip('/')
        
        # Prevent path traversal
        if '..' in path:
            raise ValueError("Invalid path - directory traversal detected")
        
        full_path = os.path.abspath(os.path.join(repo_path, path))
        
        if not full_path.startswith(repo_path_abs + os.sep):
            raise ValueError(f"Invalid path - must be inside repository")
        
        if not os.path.exists(full_path):
            raise ValueError(f"Path '{path}' does not exist")
        
        # Delete based on type
        if os.path.isdir(full_path):
            shutil.rmtree(full_path)
            deleted_type = "directory"
        else:
            os.remove(full_path)
            deleted_type = "file"
        
        # Clean up empty directories
        if deleted_type == "file":
            dir_path = os.path.dirname(full_path)
            while dir_path != repo_path:
                try:
                    if not os.listdir(dir_path):
                        os.rmdir(dir_path)
                    else:
                        break
                except (OSError, PermissionError):
                    break
                dir_path = os.path.dirname(dir_path)
        
        # Create commit
        result = await self.create_commit(repo_name, commit_message)
        
        return {
            "success": True,
            "path": path,
            "deleted_type": deleted_type,
            "commit": result["commit"]
        }
    
    async def path_to_git_tree(
        self,
        repo_name: str,
        path: str,
        max_size: int = 10 * 1024 * 1024 * 1024  # 10GB default
    ) -> Tree:
        """
        Convert ANY file path to a Git Tree object (recursively).
        
        Args:
            repo_name: Name of the repository
            path: File or directory path to convert
            max_size: Maximum total size to process (default: 10GB)
        
        Returns:
            dulwich.objects.Tree: Git Tree object
        
        Raises:
            ValueError: If path invalid, repo doesn't exist, or size too large
            PermissionError: If can't access the path
        """
        
        # 1. Validate input
        if not path:
            raise ValueError("Path cannot be empty")
        
        if not os.path.exists(path):
            raise ValueError(f"Path '{path}' does not exist")
        
        # Prevent directory traversal
        if '..' in path:
            raise ValueError("Invalid path - directory traversal detected")
        
        # 2. Check repo exists
        repo_path = os.path.join(self.main_repo_path, repo_name)
        if not os.path.exists(os.path.join(repo_path, ".git")):
            raise ValueError(f"Repository '{repo_name}' does not exist")
        
        # 3. Check size limit (for directories)
        if os.path.isdir(path):
            total_size = self._get_directory_size(path)
            if total_size > max_size:
                raise ValueError(
                    f"Directory too large: {total_size / (1024**3):.2f} GB "
                    f"(max: {max_size / (1024**3):.2f} GB)"
                )
        
        # 4. Get repository
        repo = await self.get_repo(repo_name)
        
        try:
            # 5. Create virtual tree with lock
            async with self._get_lock(repo_name):
                virtual_tree = await self.dir_walk(path)
                git_tree = await self.make_tree(repo, virtual_tree)
                repo.object_store.add_object(git_tree)
                return git_tree
                
        except PermissionError as e:
            logger.error(f"Permission denied: {path} - {e}")
            raise ValueError(f"Cannot access path: {path}")
        except Exception as e:
            logger.error(f"Failed to convert path to Git tree: {e}")
            raise


    def _get_directory_size(self, path: str) -> int:
        """Calculate total size of a directory (recursive)."""
        total = 0
        try:
            for root, dirs, files in os.walk(path):
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        total += os.path.getsize(file_path)
                    except (OSError, FileNotFoundError):
                        pass
        except (OSError, PermissionError):
            pass
        return total
