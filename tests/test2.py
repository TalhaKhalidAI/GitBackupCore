# tests/test2.py
import sys
import os
import asyncio
import shutil
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from App.core.git_core import GitCore

async def test_checkout_sync():
    print("🚀 Starting Checkout & Disk Sync Test...")
    test_root = os.path.abspath("./test_repos_checkout")
    if os.path.exists(test_root): shutil.rmtree(test_root)
    os.makedirs(test_root, exist_ok=True)
    
    git = GitCore()
    git.main_repo_path = test_root
    repo_name = "checkout_test"
    
    try:
        # 1. Setup Main Branch
        print("\n--- Phase 1: Setup Main ---")
        await git.init_git(repo_name, "main")
        repo_path = os.path.join(test_root, repo_name)
        
        with open(os.path.join(repo_path, "main_only.txt"), "w") as f:
            f.write("This file only exists on main")
            
        await git.create_commit(repo_name, "Commit on main")
        print("✅ Created main_only.txt")
        
        # 2. Create and Switch to Branch V2
        print("\n--- Phase 2: Switch to Branch V2 ---")
        await git.create_branch(repo_name, "v2", "main")
        await git.checkout(repo_name, "v2")
        
        # Modify disk on V2
        if os.path.exists(os.path.join(repo_path, "main_only.txt")):
            os.remove(os.path.join(repo_path, "main_only.txt"))
            
        with open(os.path.join(repo_path, "v2_only.txt"), "w") as f:
            f.write("This file only exists on V2")
            
        await git.create_commit(repo_name, "Commit on v2")
        print("✅ Deleted main_only.txt, Created v2_only.txt")
        
        # 3. The Time Travel Test: Switch back to Main
        print("\n--- Phase 3: Switch BACK to Main ---")
        print("Status before checkout:", os.listdir(repo_path))
        
        await git.checkout(repo_name, "main")
        
        files_now = os.listdir(repo_path)
        print("Status after checkout:", files_now)
        
        has_main = "main_only.txt" in files_now
        has_v2 = "v2_only.txt" in files_now
        
        if has_main and not has_v2:
            print("✨ SUCCESS: Disk synchronized perfectly!")
            print("   - main_only.txt was RESTORED")
            print("   - v2_only.txt was REMOVED")
        else:
            print("❌ FAILURE: Disk sync failed.")
            print(f"   - Main file present: {has_main}")
            print(f"   - V2 file present: {has_v2}")
            
        # 4. Switch to V2 again
        print("\n--- Phase 4: Switch back to V2 ---")
        await git.checkout(repo_name, "v2")
        files_v2 = os.listdir(repo_path)
        print("Status after second checkout:", files_v2)
        
        if "v2_only.txt" in files_v2 and "main_only.txt" not in files_v2:
            print("✨ SUCCESS: Returned to V2 state.")
            
        print("\n✅ Checkout & Disk Sync Test Completed!")
        
    except Exception as e:
        print(f"\n❌ Test Failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        git.close()

if __name__ == "__main__":
    asyncio.run(test_checkout_sync())