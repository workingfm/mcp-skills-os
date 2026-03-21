"""
git_helper.py — Wrapper thin attorno a git per l'auto-evoluzione.

Convenzione dei commit:
  AI-evolution vX.Y - [reason]          ← upsert automatico
  AI-rollback skill_id → SHA - [reason] ← rollback
"""
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("skill-os.git")

REPO_ROOT = Path(__file__).parent.parent.resolve()


def _run_git(*args: str) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git", *args], cwd=str(REPO_ROOT),
        capture_output=True, text=True,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def commit_skill_update(skill_id: str, version: str, reason: str) -> dict:
    """Stage + commit della cartella skill_id. Ritorna {"ok", "sha", "message", "error"}."""
    skill_path = f"skills/{skill_id}"
    message = f"AI-evolution v{version} - {reason}"

    rc, _, stderr = _run_git("add", skill_path)
    if rc != 0:
        return {"ok": False, "sha": "", "message": "", "error": stderr}

    _, status, _ = _run_git("status", "--porcelain", skill_path)
    if not status:
        return {"ok": True, "sha": "", "message": "nothing to commit", "error": ""}

    rc, _, stderr = _run_git(
        "commit",
        "--author=skill-os-agent <agent@skill-os.local>",
        f"--message={message}",
    )
    if rc != 0:
        return {"ok": False, "sha": "", "message": "", "error": stderr}

    _, sha, _ = _run_git("rev-parse", "--short", "HEAD")
    logger.info(f"[git] {sha}: {message}")
    return {"ok": True, "sha": sha, "message": message, "error": ""}


def rollback_skill(skill_id: str, commits_back: int = 1) -> dict:
    """Riporta skill_id allo stato del commit precedente."""
    skill_path = f"skills/{skill_id}"
    rc, sha_log, stderr = _run_git(
        "log", "--format=%H", f"-{commits_back + 1}", "--", skill_path
    )
    if rc != 0 or not sha_log:
        return {"ok": False, "restored_sha": "", "error": stderr or "No history"}

    target_sha = sha_log.split("\n")[-1]
    rc, _, stderr = _run_git("checkout", target_sha, "--", skill_path)
    if rc != 0:
        return {"ok": False, "restored_sha": "", "error": stderr}

    _run_git("add", skill_path)
    _run_git("commit", f"--message=AI-rollback {skill_id} → {target_sha[:7]}")
    logger.info(f"[git] rollback {skill_id} → {target_sha[:7]}")
    return {"ok": True, "restored_sha": target_sha[:7], "error": ""}


def get_skill_history(skill_id: str, limit: int = 10) -> list[dict]:
    """Ultimi N commit che toccano una skill."""
    _, log_output, _ = _run_git(
        "log", f"--max-count={limit}", "--format=%H|%as|%s",
        "--", f"skills/{skill_id}",
    )
    if not log_output:
        return []
    results = []
    for line in log_output.split("\n"):
        if "|" in line:
            sha, date, subject = line.split("|", 2)
            results.append({"sha": sha[:7], "date": date, "message": subject})
    return results
