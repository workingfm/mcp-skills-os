"""
skill-os v1.2 — MCP Skill Registry AUTO-EVOLUTIVO
Entry point: FastMCP server (stdio → Claude Code)

Il ragionamento LLM passa interamente attraverso MCP sampling,
utilizzando l'abbonamento Pro dell'utente. Zero API key necessarie.

Tool MCP esposti:
  list_skills()                         → discovery skill
  get_prompt(skill_id)                  → lazy-load prompt
  execute(tool_ref, code, input_data)   → esecuzione sandboxed + LLM enrichment
  approve_pending(approval_id, approve) → approvazione umana upsert
"""
import asyncio
import datetime
import json
import logging
import os
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastmcp import FastMCP, Context
from registry import SkillRegistry
from executor import Executor
from safety import SafetyViolation, check_execution, validate_manifest

# ------------------------------------------------------------------ #
#  Logging su stderr (non disturba il canale stdio MCP)               #
# ------------------------------------------------------------------ #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("skill-os")

# ------------------------------------------------------------------ #
#  Componenti core                                                     #
# ------------------------------------------------------------------ #
REPO_ROOT      = Path(__file__).parent.parent
SKILLS_DIR     = REPO_ROOT / "skills"
LOGS_DIR       = REPO_ROOT / "logs"
PENDING_DIR    = REPO_ROOT / "pending_approvals"

LOGS_DIR.mkdir(exist_ok=True)
PENDING_DIR.mkdir(exist_ok=True)

registry = SkillRegistry(skills_dir=SKILLS_DIR)
executor = Executor()

# ------------------------------------------------------------------ #
#  MCP Server                                                          #
# ------------------------------------------------------------------ #
mcp = FastMCP(
    "skill-os",
    instructions=(
        "Sei connesso a skill-os v1.2 — MCP Skill Registry auto-evolutivo.\n\n"
        "Workflow standard (3 chiamate):\n"
        "  1. list_skills()                    → scopri le skill disponibili\n"
        "  2. get_prompt('skill_id')           → carica il system prompt (lazy)\n"
        "  3. execute('skill_id:tool_id', ...) → esegui il tool in sandbox\n\n"
        "Per il ciclo di auto-evoluzione:\n"
        "  execute('skill_manager:eval_skill', code='{\"skill_id\":\"X\"}')\n"
        "  execute('orchestrator:run_cycle')    → analizza e propone miglioramenti\n"
        "  approve_pending(approval_id, approve=True) → approva l'upsert\n\n"
        "Il ragionamento LLM (critique, proposte) usa MCP sampling → abbonamento Pro.\n"
        "Non serve ANTHROPIC_API_KEY.\n\n"
        "Formato tool_ref: 'skill_id:tool_id' (es. 'python_exec:run_code')"
    ),
)


@mcp.tool()
def list_skills() -> dict:
    """Ritorna il catalogo completo di tutte le skill con tool, descrizioni e flag safety."""
    return registry.list_skills()


@mcp.tool()
def get_prompt(skill_id: str) -> str:
    """
    Carica il system prompt di una skill (lazy loading).
    Iniettare nel contesto prima di usare i tool della skill.
    """
    try:
        return registry.get_prompt(skill_id)
    except (FileNotFoundError, KeyError) as e:
        return f"[ERRORE] {e}"


@mcp.tool()
async def execute(tool_ref: str, code: str = "", input_data: str = "",
                  ctx: Context = None) -> dict:
    """
    Esegue un tool e ritorna l'output.
    Per eval_skill e run_cycle, arricchisce automaticamente i risultati
    con ragionamento LLM via MCP sampling (abbonamento Pro).

    Args:
        tool_ref:   'skill_id:tool_id' (es. 'python_exec:run_code')
        code:       Codice Python o payload JSON da passare al tool
        input_data: Dati supplementari (testo o JSON)
    """
    if ":" not in tool_ref:
        return {"status": "error", "stdout": "", "exit_code": 1,
                "stderr": f"tool_ref non valido: '{tool_ref}'. Atteso: 'skill_id:tool_id'"}

    skill_id, tool_id = tool_ref.split(":", 1)

    try:
        tool = registry.get_tool(skill_id, tool_id)
    except KeyError as e:
        return {"status": "error", "stdout": "", "exit_code": 1, "stderr": str(e)}

    try:
        needs_approval = check_execution(tool)
    except SafetyViolation as e:
        return {"status": "blocked", "stdout": "", "exit_code": 1, "stderr": f"[SAFETY] {e}"}

    if needs_approval:
        logger.info(f"[execute] {tool_ref} richiede approvazione umana")

    logger.info(f"[execute] {tool_ref} | code_len={len(code)}")
    result = await executor.run(skill_id, tool_id, tool, code, input_data)
    logger.info(f"[execute] {tool_ref} → {result['status']} (exit {result['exit_code']})")

    # ── LLM enrichment via MCP sampling ──────────────────────────
    if result["status"] == "ok" and ctx is not None:
        try:
            parsed = json.loads(result.get("stdout", ""))
            result = await _enrich_with_llm(parsed, tool_ref, ctx, result)
        except (json.JSONDecodeError, Exception):
            pass  # Non e JSON o enrichment fallito, ritorna risultato raw

    # Audit log
    _audit_log(tool_ref, result["status"])
    return result


async def _enrich_with_llm(parsed: dict, tool_ref: str, ctx: Context,
                           original_result: dict) -> dict:
    """Arricchisce i risultati di eval e orchestrator con ragionamento LLM
    via MCP sampling. Usa l'abbonamento Pro, zero API key."""

    # ── Enrichment per eval_skill: critique LLM ──────────────────
    if parsed.get("needs_llm_critique") and parsed.get("test_results"):
        try:
            critique_prompt = (
                f"Sei un esperto di valutazione software.\n"
                f"Skill: {parsed.get('skill_id', '?')}\n"
                f"Test results:\n{json.dumps(parsed['test_results'], indent=2, ensure_ascii=False)}\n\n"
                f"Analizza i risultati e rispondi SOLO con JSON valido:\n"
                f'{{"score":<0-10 float>,"critique":{{"strengths":[...],"weaknesses":[...],'
                f'"suggested_improvements":[...]}}}}'
            )
            response = await ctx.sample(critique_prompt)
            text = response.text if hasattr(response, "text") else str(response)
            text = text.strip().replace("```json", "").replace("```", "").strip()
            llm_critique = json.loads(text)

            parsed["score"] = llm_critique.get("score", parsed["score"])
            parsed["critique"] = llm_critique.get("critique", parsed["critique"])
            parsed["recommendation"] = (
                "ok" if parsed["score"] >= 8.5
                else ("rebuild" if parsed["score"] < 5.0 else "improve")
            )
            parsed["llm_enriched"] = True
            logger.info(f"[sampling] critique LLM generata per {parsed.get('skill_id')}")

            original_result["stdout"] = json.dumps(parsed, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[sampling] critique fallita, uso euristico: {e}")

    # ── Enrichment per run_cycle: generazione proposta ────────────
    if parsed.get("needs_proposal") and parsed.get("target_skill"):
        try:
            target = parsed["target_skill"]
            eval_result = parsed.get("eval_result", {})
            current_prompt = parsed.get("current_system_prompt", "")

            proposal_prompt = (
                f"Sei un esperto di prompt engineering e miglioramento software.\n"
                f"Skill: {target}\n"
                f"Score attuale: {eval_result.get('score')}/10\n"
                f"Critique: {json.dumps(eval_result.get('critique', {}), ensure_ascii=False)}\n"
                f"System prompt attuale (primi 2000 chars):\n{current_prompt}\n\n"
                f"Genera una proposta di miglioramento per il system_prompt.md.\n"
                f"Rispondi SOLO con JSON valido:\n"
                f'{{"rationale":"<spiega cosa migliori>",'
                f'"new_system_prompt":"<testo completo del nuovo system_prompt.md>",'
                f'"git_commit_message":"AI-evolution vX.Y - <reason breve>"}}'
            )
            response = await ctx.sample(proposal_prompt)
            text = response.text if hasattr(response, "text") else str(response)
            text = text.strip().replace("```json", "").replace("```", "").strip()
            proposal = json.loads(text)

            # Scrivi la proposta come pending approval
            approval_id = _write_proposal_pending(target, eval_result, proposal)

            parsed["action_taken"] = "proposal_created"
            parsed["needs_proposal"] = False
            parsed["approval_id"] = approval_id
            parsed["proposal_rationale"] = proposal.get("rationale", "")
            parsed["llm_enriched"] = True
            parsed["summary"] = (
                f"Score {eval_result.get('score')} < 8.5. "
                f"Proposta creata (ID: {approval_id}). "
                f"Approva con: approve_pending('{approval_id}', approve=True)"
            )
            logger.info(f"[sampling] proposta generata per {target}, approval_id={approval_id}")

            original_result["stdout"] = json.dumps(parsed, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[sampling] generazione proposta fallita: {e}")

    return original_result


def _write_proposal_pending(skill_id: str, eval_result: dict, proposal: dict) -> str:
    """Scrive la proposta come file pending approval."""
    PENDING_DIR.mkdir(exist_ok=True)
    approval_id = secrets.token_hex(6)

    manifest_path = SKILLS_DIR / skill_id / "manifest.json"
    current_version = "1.0.0"
    if manifest_path.exists():
        try:
            current_version = json.loads(manifest_path.read_text()).get("version", "1.0.0")
        except Exception:
            pass
    parts = current_version.split(".")
    version_new = f"{parts[0]}.{int(parts[1]) + 1 if len(parts) > 1 else 1}.0"

    payload = {
        "approval_id": approval_id,
        "skill_id": skill_id,
        "version_new": version_new,
        "rationale": proposal.get("rationale", "Auto-generated improvement"),
        "git_commit_message": proposal.get("git_commit_message", f"AI-evolution v{version_new}"),
        "eval_score_before": eval_result.get("score"),
        "changes_summary": ["system_prompt.md"],
        "source": "orchestrator_mcp_sampling",
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        "changes": [{
            "file": "system_prompt.md",
            "after": proposal.get("new_system_prompt", ""),
        }],
    }
    (PENDING_DIR / f"{approval_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2)
    )
    return approval_id


@mcp.tool()
def approve_pending(approval_id: str, approve: bool = True) -> dict:
    """
    Approva o rifiuta un upsert in attesa di conferma umana.

    Args:
        approval_id: ID del file di approvazione (senza estensione)
        approve:     True = approva, False = rifiuta
    """
    pending_file = PENDING_DIR / f"{approval_id}.json"
    if not pending_file.exists():
        return {"ok": False, "error": f"Approval ID '{approval_id}' non trovato"}

    decision = "approved" if approve else "rejected"
    decision_file = PENDING_DIR / f"{approval_id}.{decision}"
    decision_file.write_text(decision)

    logger.info(f"[approval] {approval_id} → {decision}")
    return {"ok": True, "approval_id": approval_id, "decision": decision}


@mcp.tool()
def list_pending_approvals() -> list:
    """Elenca tutti gli upsert in attesa di approvazione umana."""
    pending = []
    for f in PENDING_DIR.glob("*.json"):
        approval_id = f.stem
        approved = (PENDING_DIR / f"{approval_id}.approved").exists()
        rejected = (PENDING_DIR / f"{approval_id}.rejected").exists()
        status = "approved" if approved else "rejected" if rejected else "pending"
        try:
            data = json.loads(f.read_text())
        except Exception:
            data = {}
        pending.append({"id": approval_id, "status": status, **data})
    return pending


# ------------------------------------------------------------------ #
#  Audit log                                                           #
# ------------------------------------------------------------------ #
def _audit_log(tool_ref: str, status: str):
    line = f"{datetime.datetime.now(datetime.UTC).isoformat()} | {tool_ref} | {status}\n"
    with open(LOGS_DIR / "usage.log", "a") as f:
        f.write(line)


# ------------------------------------------------------------------ #
#  Background Orchestrator Loop                                        #
# ------------------------------------------------------------------ #
ORCHESTRATOR_INTERVAL_SECONDS = int(os.getenv("ORCHESTRATOR_INTERVAL", "1800"))  # 30 min
ORCHESTRATOR_ENABLED = os.getenv("ORCHESTRATOR_ENABLED", "false").lower() == "true"


async def _orchestrator_loop():
    """
    Background task: chiama orchestrator:run_cycle ogni N secondi.
    Il subprocess fa eval + monitoring. Se serve una proposta LLM,
    il risultato viene arricchito al prossimo execute() chiamato dall'utente.
    Attiva con env ORCHESTRATOR_ENABLED=true.
    """
    logger.info(
        f"[orchestrator] loop avviato (ogni {ORCHESTRATOR_INTERVAL_SECONDS}s). "
        f"Stato: {'ATTIVO' if ORCHESTRATOR_ENABLED else 'STANDBY (set ORCHESTRATOR_ENABLED=true)'}"
    )
    await asyncio.sleep(60)

    while True:
        if ORCHESTRATOR_ENABLED:
            try:
                tool = registry.get_tool("orchestrator", "run_cycle")
                result = await executor.run(
                    "orchestrator", "run_cycle", tool, code="", input_data=""
                )
                stdout = result.get("stdout", "")
                logger.info(
                    f"[orchestrator] ciclo completato: {result['status']}\n"
                    f"{stdout[:500]}"
                )

                # Se il ciclo segnala needs_proposal, logga per il prossimo
                # execute() manuale (il background loop non ha ctx per sampling)
                try:
                    cycle_data = json.loads(stdout)
                    if cycle_data.get("needs_proposal"):
                        logger.info(
                            f"[orchestrator] skill '{cycle_data.get('target_skill')}' "
                            f"necessita proposta LLM. Esegui manualmente: "
                            f"execute('orchestrator:run_cycle') per generarla via sampling."
                        )
                except (json.JSONDecodeError, Exception):
                    pass

            except KeyError:
                logger.debug("[orchestrator] skill 'orchestrator' non trovata, skip.")
            except Exception as e:
                logger.error(f"[orchestrator] errore nel ciclo: {e}")
        else:
            logger.debug("[orchestrator] standby.")

        await asyncio.sleep(ORCHESTRATOR_INTERVAL_SECONDS)


# ------------------------------------------------------------------ #
#  Run                                                                 #
# ------------------------------------------------------------------ #
@mcp.on_startup()
async def on_startup():
    """Avvia il background orchestrator loop al boot del server MCP."""
    asyncio.create_task(_orchestrator_loop())
    logger.info("[startup] orchestrator loop schedulato")


if __name__ == "__main__":
    logger.info("skill-os v1.2 — avvio (stdio, Claude Code transport)")
    logger.info(f"skills_dir = {SKILLS_DIR}")
    mcp.run()
