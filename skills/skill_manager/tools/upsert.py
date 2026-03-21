"""
tools/upsert.py — Applica una patch a una skill dopo approvazione umana.

Input (user_code.py): JSON string
  {
    "skill_id": "python_exec",
    "version_new": "1.1.0",
    "rationale": "Spiega perché",
    "git_commit_message": "AI-evolution v1.1.0 - reason",
    "changes": [
      {
        "file": "system_prompt.md",
        "after": "<nuovo contenuto completo del file>"
      }
    ]
  }

Flusso:
  1. Controlla rate limit (max 3 upsert/skill/giorno)
  2. Scrive file pending_approvals/<id>.json
  3. Aspetta <id>.approved (poll 5s, max 5 min)
  4. Se approvato: applica changes + git commit + log evolution
  5. Se rifiutato o timeout: ritorna senza modificare
"""
import datetime, json, os, secrets, sys, time
from pathlib import Path

REPO_ROOT    = Path(os.getenv("SKILL_ROOT", Path(__file__).parent.parent.parent.parent))
SKILLS_DIR   = REPO_ROOT / "skills"
PENDING_DIR  = REPO_ROOT / "pending_approvals"
LOGS_DIR     = REPO_ROOT / "logs"
APPROVAL_TIMEOUT = int(os.getenv("APPROVAL_TIMEOUT_SECONDS", "300"))  # 5 min default
MAX_UPSERTS_PER_DAY = 3


def _check_rate_limit(skill_id: str) -> bool:
    """True se possiamo fare l'upsert (non superato il limite giornaliero)."""
    evo_log = LOGS_DIR / "evolution.log"
    if not evo_log.exists():
        return True
    today = datetime.date.today().isoformat()
    count = sum(
        1 for line in evo_log.read_text().splitlines()
        if today in line and f"| {skill_id} |" in line and "| upsert |" in line
    )
    return count < MAX_UPSERTS_PER_DAY


def _write_evolution_log(skill_id: str, score_before: float, score_after: float,
                          action: str, git_sha: str):
    LOGS_DIR.mkdir(exist_ok=True)
    line = (f"{datetime.datetime.now(datetime.UTC).isoformat()} | {skill_id} | "
            f"{score_before} | {score_after} | {action} | {git_sha}\n")
    with open(LOGS_DIR / "evolution.log", "a") as f:
        f.write(line)


def _request_approval(approval_id: str, payload: dict) -> Path:
    PENDING_DIR.mkdir(exist_ok=True)
    pending_file = PENDING_DIR / f"{approval_id}.json"
    pending_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return pending_file


def _wait_for_approval(approval_id: str, timeout: int) -> str:
    """Poll pending_approvals/<id>.approved o .rejected. Ritorna 'approved'/'rejected'/'timeout'."""
    approved_file = PENDING_DIR / f"{approval_id}.approved"
    rejected_file = PENDING_DIR / f"{approval_id}.rejected"
    deadline = time.time() + timeout

    while time.time() < deadline:
        if approved_file.exists():
            return "approved"
        if rejected_file.exists():
            return "rejected"
        time.sleep(5)

    return "timeout"


def _apply_changes(skill_id: str, changes: list[dict]) -> list[str]:
    """Applica le changes alla skill. Ritorna lista di file modificati."""
    skill_root = SKILLS_DIR / skill_id
    modified = []
    for change in changes:
        rel_path = change.get("file", "")
        new_content = change.get("after", "")
        if not rel_path or not new_content:
            continue
        target = skill_root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_content, encoding="utf-8")
        modified.append(rel_path)
    return modified


def _git_commit(skill_id: str, version: str, message: str) -> str:
    """Esegue git add + commit. Ritorna SHA o errore."""
    import subprocess
    result = subprocess.run(
        ["git", "add", f"skills/{skill_id}"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    if result.returncode != 0:
        return f"git add error: {result.stderr}"

    # Controlla se c'è qualcosa da committare
    status = subprocess.run(
        ["git", "status", "--porcelain", f"skills/{skill_id}"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    if not status.stdout.strip():
        return "nothing-to-commit"

    commit = subprocess.run(
        ["git", "commit",
         "--author=skill-os-agent <agent@skill-os.local>",
         f"--message={message}"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    if commit.returncode != 0:
        return f"git commit error: {commit.stderr}"

    sha_result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    return sha_result.stdout.strip()


def main():
    sandbox_dir = os.getenv("SKILL_SANDBOX_DIR", ".")
    code_file = Path(sandbox_dir) / "user_code.py"

    try:
        raw = code_file.read_text(encoding="utf-8").strip()
        params = json.loads(raw)
    except Exception as e:
        print(json.dumps({"status": "error", "error": f"Input non valido: {e}"}))
        sys.exit(1)

    skill_id = params.get("skill_id")
    version_new = params.get("version_new", "0.0.1")
    rationale = params.get("rationale", "No rationale provided")
    git_message = params.get("git_commit_message", f"AI-evolution v{version_new} - {rationale[:60]}")
    changes = params.get("changes", [])

    if not skill_id:
        print(json.dumps({"status": "error", "error": "skill_id mancante"})); sys.exit(1)
    if not changes:
        print(json.dumps({"status": "error", "error": "changes vuoto"})); sys.exit(1)

    # --- Rate limit ---
    if not _check_rate_limit(skill_id):
        print(json.dumps({
            "status": "blocked",
            "reason": f"Rate limit: max {MAX_UPSERTS_PER_DAY} upsert/giorno per '{skill_id}'"
        }))
        sys.exit(0)

    # --- Crea approval request ---
    approval_id = secrets.token_hex(6)

    approval_payload = {
        "approval_id": approval_id,
        "skill_id": skill_id,
        "version_new": version_new,
        "rationale": rationale,
        "git_commit_message": git_message,
        "changes_summary": [c.get("file") for c in changes],
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
    }

    _request_approval(approval_id, approval_payload)

    print(json.dumps({
        "status": "pending_approval",
        "approval_id": approval_id,
        "message": (
            f"Upsert in attesa di approvazione.\n"
            f"Per approvare (MCP): approve_pending('{approval_id}', approve=True)\n"
            f"Per approvare (shell): touch pending_approvals/{approval_id}.approved\n"
            f"Per rifiutare: touch pending_approvals/{approval_id}.rejected\n"
            f"Timeout: {APPROVAL_TIMEOUT}s"
        ),
    }), flush=True)

    # --- Aspetta approvazione ---
    decision = _wait_for_approval(approval_id, APPROVAL_TIMEOUT)

    if decision != "approved":
        print(json.dumps({
            "status": "cancelled",
            "decision": decision,
            "approval_id": approval_id,
        }))
        sys.exit(0)

    # --- Applica changes ---
    modified_files = _apply_changes(skill_id, changes)

    # Aggiorna versione nel manifest se specificata
    manifest_path = SKILLS_DIR / skill_id / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
            manifest["version"] = version_new
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
            if "manifest.json" not in modified_files:
                modified_files.append("manifest.json")
        except Exception:
            pass

    # --- Git commit ---
    sha = _git_commit(skill_id, version_new, git_message)

    # --- Evolution log ---
    _write_evolution_log(skill_id, 0.0, 0.0, "upsert", sha)

    print(json.dumps({
        "status": "ok",
        "skill_id": skill_id,
        "version_new": version_new,
        "modified_files": modified_files,
        "git_sha": sha,
        "git_commit_message": git_message,
        "approval_id": approval_id,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
