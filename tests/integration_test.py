"""
Integration tests for GitCore — covers the three highest-churn paths:
  1. comparison() / git_status()
  2. checkout() disk sync
  3. merge_branches() 3-way merge
"""
import asyncio
import os
import shutil
import logging

from App.core.git_core import GitCore

logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(name)s - %(message)s")
logger = logging.getLogger(__name__)

PASS = "✅"
FAIL = "❌"


def _write(path: str, content: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _read(path: str) -> str:
    with open(path) as f:
        return f.read()


async def run_integration_tests():
    # Fresh GitCore each run to avoid repo cache poisoning
    git = GitCore()
    repo_name = "it_gitcore"
    repo_path = os.path.join(git.main_repo_path, repo_name)

    # --- clean slate ---
    if os.path.exists(repo_path):
        shutil.rmtree(repo_path)

    errors = []

    async def check(label: str, condition: bool, detail: str = ""):
        if condition:
            logger.info(f"{PASS} {label}")
        else:
            logger.error(f"{FAIL} {label}  detail={detail}")
            errors.append(label)

    try:
        # ── Phase 1: Init & first commit ──────────────────────────────────────
        logger.info("\n── Phase 1: Init & first commit ──")
        await git.init_git(repo_name)

        _write(os.path.join(repo_path, "readme.txt"), "Hello world")
        _write(os.path.join(repo_path, "src/main.py"), "print('v1')")

        c1 = await git.create_commit(repo_name, "Initial commit")
        await check("Initial commit succeeds", c1["success"])
        await check("Commit SHA 8 chars", len(c1["commit"]) == 8)

        # ── Phase 2: comparison() detects changes ────────────────────────────
        logger.info("\n── Phase 2: comparison() ──")
        # init_git sets HEAD → refs/heads/main, so we should be on main
        status_before = await git.git_status(repo_name)
        await check("On main branch after init",
                    status_before["branch"] == "main",
                    f"branch={status_before['branch']}")

        # Modify one file, add a new one
        _write(os.path.join(repo_path, "readme.txt"), "Hello world — v2")
        _write(os.path.join(repo_path, "src/util.py"), "# utility")

        status = await git.git_status(repo_name)
        changes = status["changes"]
        await check("comparison: 1 modified",
                    "readme.txt" in changes["modified"],
                    f"modified={changes['modified']}")
        await check("comparison: 1 added",
                    "src/util.py" in changes["added"],
                    f"added={changes['added']}")
        await check("comparison: 0 deleted",
                    len(changes["deleted"]) == 0,
                    f"deleted={changes['deleted']}")

        c2 = await git.create_commit(repo_name, "Update readme, add util")
        await check("Second commit succeeds", c2["success"])

        # ── Phase 3: branching ────────────────────────────────────────────────
        logger.info("\n── Phase 3: Branching ──")
        br = await git.create_branch(repo_name, "feature", branch_from="main")
        await check("Branch created", br["success"])

        # Switch back to main (create_branch moves HEAD to feature)
        await git.checkout(repo_name, "main")

        # ── Phase 4: checkout() disk sync ────────────────────────────────────
        logger.info("\n── Phase 4: checkout() disk sync ──")
        # Add a main-only file and commit
        _write(os.path.join(repo_path, "main_only.txt"), "only on main")
        c3 = await git.create_commit(repo_name, "Main-only file")
        await check("Main-only commit", c3["success"])

        # Switch to feature — main_only.txt should disappear
        co_feat = await git.checkout(repo_name, "feature")
        await check("Checkout feature", co_feat["success"])
        await check("main_only.txt absent on feature",
                    not os.path.exists(os.path.join(repo_path, "main_only.txt")))
        await check("src/util.py present on feature",
                    os.path.exists(os.path.join(repo_path, "src/util.py")))

        # ── Phase 5: compare_branches() ──────────────────────────────────────
        logger.info("\n── Phase 5: compare_branches() ──")
        # Make and commit a feature-only change FIRST, then compare
        _write(os.path.join(repo_path, "feature_only.txt"), "feature work")
        feat_c = await git.create_commit(repo_name, "Feature work")
        await check("Feature commit advances feature branch", feat_c["success"])

        # Compare main→feature: feature has feature_only added, main_only deleted
        diff = await git.compare_branches(repo_name, "main", "feature")
        logger.info(f"  compare added={diff['added']}, deleted={diff['deleted']}")
        await check("compare: feature_only.txt added",
                    "feature_only.txt" in diff["added"],
                    f"added={diff['added']}")
        await check("compare: main_only.txt deleted (not in feature)",
                    "main_only.txt" in diff["deleted"],
                    f"deleted={diff['deleted']}")

        # ── Phase 6: merge_branches() 3-way merge ────────────────────────────
        logger.info("\n── Phase 6: merge_branches() ──")
        await git.checkout(repo_name, "main")

        merge = await git.merge_branches(repo_name, "feature", "main")
        await check("Merge succeeds",
                    merge.get("status") == "MERGED",
                    str(merge))

        # Do a fresh checkout so disk reflects merge commit
        await git.checkout(repo_name, "main")
        await check("feature_only.txt on disk after merge",
                    os.path.exists(os.path.join(repo_path, "feature_only.txt")))
        await check("main_only.txt on disk after merge",
                    os.path.exists(os.path.join(repo_path, "main_only.txt")))

        # ── Phase 7: stash ────────────────────────────────────────────────────
        logger.info("\n── Phase 7: Stash ──")
        _write(os.path.join(repo_path, "wip.txt"), "work in progress")
        stash = await git.stash_push(repo_name, "WIP stash")
        await check("stash_push succeeds", stash["success"])
        await check("WIP file removed after stash",
                    not os.path.exists(os.path.join(repo_path, "wip.txt")))

        pop = await git.stash_pop(repo_name)
        await check("stash_pop succeeds", pop["success"])
        await check("WIP file restored after pop",
                    os.path.exists(os.path.join(repo_path, "wip.txt")))

        # Double-stash guard (inside lock — no TOCTOU)
        await git.create_commit(repo_name, "Commit wip before second stash test")
        _write(os.path.join(repo_path, "wip2.txt"), "second wip")
        await git.stash_push(repo_name, "first stash")
        try:
            await git.stash_push(repo_name, "second stash — should raise")
            await check("Double-stash raises ValueError", False, "No exception raised")
        except ValueError:
            await check("Double-stash raises ValueError", True)

        # ── Phase 8: health_check metrics ────────────────────────────────────
        logger.info("\n── Phase 8: Health check ──")
        health = await git.health_check()
        await check("Metrics: commits >= 4",
                    health["metrics"]["commits"] >= 4,
                    str(health["metrics"]))
        await check("Metrics: status_checks >= 1",
                    health["metrics"]["status_checks"] >= 1,
                    str(health["metrics"]))

    finally:
        git.close()

    # ── Summary ──────────────────────────────────────────────────────────────
    logger.info("\n" + "═" * 50)
    if errors:
        logger.error(f"FAILED — {len(errors)} assertion(s): {errors}")
        raise SystemExit(1)
    else:
        logger.info("🏆  ALL INTEGRATION TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(run_integration_tests())
