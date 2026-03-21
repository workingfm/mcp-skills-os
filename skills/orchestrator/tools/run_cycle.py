"""
tools/run_cycle.py — Il ciclo di auto-evoluzione dell'orchestratore.

Eseguito ogni 30 minuti dal background loop di main.py.
Non richiede input (code="").

Flusso:
  1. Analizza /logs/usage.log → trova skill target
  2. Lancia eval_skill via subprocess
  3. Se score < 8.5 → ritorna dati eval con needs_proposal=True
  4. La generazione della proposta LLM avviene in main.py via MCP sampling
  5. Logga tutto in /logs/orchestrator.log

NOTA: Nessuna chiamata API diretta. Il ragionamento LLM passa
      attraverso MCP sampling (abbonamento Pro) in main.py.
"""
import datetime, json, os, subprocess, sys, tempfile
from pathlib import Path

REPO_ROOT    = Path(os.getenv("SKILL_ROOT", Path(__file__).parent.parent.parent.parent))
SKILLS_DIR   = REPO_ROOT / "skills"
LOGS_DIR     = REPO_ROOT / "logs"

SCORE_THRESHOLD    = 8.5
MAX_UPSERTS_PER_DAY = 3
EXCLUDE_SKILLS = {"orchestrator", "skill_manager"}


# ------------------------------------------------------------------ #
#  Analisi dei log                                                     #
# ------------------------------------------------------------------ #

def _parse_usage_log(hours: int = 24) -> dict[str, dict]:
    """Ritorna {skill_id: {calls: N, errors: N}} per le ultime N ore."""
    usage_log = LOGS_DIR / "usage.log"
    if not usage_log.exists():
        return {}

    cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=hours)
    stats: dict[str, dict] = {}

    for line in usage_log.read_text().splitlines():
        try:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3:
                continue
            ts = datetime.datetime.fromisoformat(parts[0])
            if ts < cutoff:
                continue
            tool_ref = parts[1]
            status   = parts[2]
            skill_id = tool_ref.split(":")[0] if ":" in tool_ref else tool_ref
            if skill_id in EXCLUDE_SKILLS:
                continue
            if skill_id not in stats:
                stats[skill_id] = {"calls": 0, "errors": 0}
            stats[skill_id]["calls"] += 1
            if status == "error":
                stats[skill_id]["errors"] += 1
        except Exception:
            continue
    return stats


def _check_rate_limit(skill_id: str) -> bool:
    evo_log = LOGS_DIR / "evolution.log"
    if not evo_log.exists():
        return True
    today = datetime.date.today().isoformat()
    count = sum(
        1 for line in evo_log.read_text().splitlines()
        if today in line and f"| {skill_id} |" in line
    )
    return count < MAX_UPSERTS_PER_DAY


def _choose_target(stats: dict[str, dict]) -> tuple[str, str] | tuple[None, None]:
    """Ritorna (skill_id, reason) per il target migliore da esaminare."""
    if not stats:
        available = [d.name for d in SKILLS_DIR.iterdir()
                     if d.is_dir() and d.name not in EXCLUDE_SKILLS
                     and (d / "manifest.json").exists()]
        if available:
            return available[0], "Nessun dato di uso, ispezione preventiva"
        return None, None

    most_errors = max(stats, key=lambda k: stats[k]["errors"], default=None)
    if most_errors and stats[most_errors]["errors"] > 0:
        return most_errors, f"Tasso errori: {stats[most_errors]['errors']}/{stats[most_errors]['calls']} calls"

    most_used = max(stats, key=lambda k: stats[k]["calls"], default=None)
    if most_used:
        return most_used, f"Skill più usata ({stats[most_used]['calls']} calls)"

    return None, None


# ------------------------------------------------------------------ #
#  Eval via subprocess                                                 #
# ------------------------------------------------------------------ #

def _run_eval(skill_id: str) -> dict:
    eval_script = SKILLS_DIR / "skill_manager" / "tools" / "eval.py"
    if not eval_script.exists():
        return {"error": "eval.py non trovato", "score": -1}

    with tempfile.TemporaryDirectory() as tmpdir:
        (Path(tmpdir) / "user_code.py").write_text(json.dumps({"skill_id": skill_id}))
        (Path(tmpdir) / "input.txt").write_text("")
        env = os.environ.copy()
        env["SKILL_SANDBOX_DIR"] = tmpdir
        env["SKILL_ROOT"] = str(REPO_ROOT)
        try:
            r = subprocess.run(
                [sys.executable, str(eval_script)],
                cwd=str(REPO_ROOT), capture_output=True,
                text=True, timeout=60, env=env,
            )
            if r.returncode != 0:
                return {"error": r.stderr[:300], "score": -1}
            return json.loads(r.stdout.strip())
        except subprocess.TimeoutExpired:
            return {"error": "eval timeout", "score": -1}
        except json.JSONDecodeError as e:
            return {"error": f"JSON parse error: {e}", "score": -1}


def _log_orchestrator(entry: dict):
    LOGS_DIR.mkdir(exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with open(LOGS_DIR / "orchestrator.log", "a") as f:
        f.write(line)


# ------------------------------------------------------------------ #
#  Main                                                                #
# ------------------------------------------------------------------ #

def main():
    now = datetime.datetime.now(datetime.UTC).isoformat()
    result = {"cycle_timestamp": now, "target_skill": None,
              "reason_for_target": None, "eval_score": None,
              "action_taken": "nothing", "approval_id": None,
              "needs_proposal": False, "summary": ""}

    # 1. Analizza usage
    stats = _parse_usage_log(hours=24)

    # 2. Scegli target
    target, reason = _choose_target(stats)
    if not target:
        result["summary"] = "Nessuna skill da esaminare."
        _log_orchestrator(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    result["target_skill"]      = target
    result["reason_for_target"] = reason

    # 3. Rate limit
    if not _check_rate_limit(target):
        result["action_taken"] = "skipped_rate_limit"
        result["summary"] = f"Rate limit raggiunto per '{target}' ({MAX_UPSERTS_PER_DAY}/giorno)."
        _log_orchestrator(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # 4. Eval
    eval_result = _run_eval(target)
    score = eval_result.get("score", -1)
    result["eval_score"] = score

    if score < 0:
        result["action_taken"] = "nothing"
        result["summary"] = f"Eval fallita: {eval_result.get('error', '?')}"
        _log_orchestrator(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if score >= SCORE_THRESHOLD:
        result["action_taken"] = "skipped_ok"
        result["summary"] = f"Score {score} >= {SCORE_THRESHOLD}. '{target}' è in buone condizioni."
        _log_orchestrator(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # 5. Segnala che serve una proposta LLM (generata da main.py via MCP sampling)
    #    Includi i dati eval per il contesto
    result["action_taken"] = "needs_proposal"
    result["needs_proposal"] = True
    result["eval_result"] = eval_result

    # Leggi il system prompt corrente per il contesto
    prompt_path = SKILLS_DIR / target / "system_prompt.md"
    if prompt_path.exists():
        result["current_system_prompt"] = prompt_path.read_text(encoding="utf-8")[:2000]

    result["summary"] = (
        f"Score {score} < {SCORE_THRESHOLD}. "
        f"Proposta di miglioramento richiesta via MCP sampling."
    )
    _log_orchestrator(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
