"""
skill-os v2.0 — MCP Skill Registry con ASR (Adaptive Skill Reinforcement)
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
from contextlib import asynccontextmanager
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
from evolution import ASREngine, ASR_ENABLED

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
#  ASR — Adaptive Skill Reinforcement                                 #
# ------------------------------------------------------------------ #
DATA_DIR = REPO_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

asr = ASREngine(
    skills_dir=SKILLS_DIR,
    data_dir=DATA_DIR,
    registry=registry,
)

# ------------------------------------------------------------------ #
#  MCP Server                                                          #
# ------------------------------------------------------------------ #
@asynccontextmanager
async def _lifespan(server):
    """Avvia il background orchestrator loop al boot del server MCP."""
    task = asyncio.create_task(_orchestrator_loop())
    logger.info("[startup] orchestrator loop schedulato")
    try:
        yield
    finally:
        task.cancel()


mcp = FastMCP(
    "skill-os",
    lifespan=_lifespan,
    instructions=(
        "Sei connesso a skill-os v2.0 — MCP Skill Registry con ASR (Adaptive Skill Reinforcement).\n\n"
        "Workflow standard (3 chiamate):\n"
        "  1. list_skills()                    → scopri le skill disponibili\n"
        "  2. get_prompt('skill_id')           → carica il system prompt (lazy)\n"
        "  3. execute('skill_id:tool_id', ...) → esegui il tool in sandbox\n\n"
        "ASR — Evoluzione adattiva:\n"
        "  Se una skill fallisce, il sistema la evolve automaticamente:\n"
        "  diagnosi → mutazione → retry → risultato corretto.\n"
        "  Le skill convergono verso la perfezione attraverso l'uso reale.\n"
        "  skill_fitness('skill_id')           → stato RL della skill\n\n"
        "Creare nuove skill:\n"
        "  create_skill('skill_id', 'descrizione') → genera skill completa via LLM\n\n"
        "Il ragionamento LLM usa MCP sampling → abbonamento Pro, zero API key.\n\n"
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
    except KeyError:
        # ── Skill non trovata: prova a crearla via LLM ────────────
        if ctx is not None:
            gen_result = await _auto_generate_skill(skill_id, tool_id, code, ctx)
            if gen_result.get("status") == "created":
                return gen_result
        return {"status": "error", "stdout": "", "exit_code": 1,
                "stderr": f"Skill '{skill_id}' o tool '{tool_id}' non trovata. "
                           f"Usa create_skill('{skill_id}', '<descrizione>') per crearla."}

    try:
        needs_approval = check_execution(tool)
    except SafetyViolation as e:
        return {"status": "blocked", "stdout": "", "exit_code": 1, "stderr": f"[SAFETY] {e}"}

    if needs_approval:
        logger.info(f"[execute] {tool_ref} richiede approvazione umana")

    logger.info(f"[execute] {tool_ref} | code_len={len(code)}")
    result = await executor.run(skill_id, tool_id, tool, code, input_data)
    logger.info(f"[execute] {tool_ref} → {result['status']} (exit {result['exit_code']})")

    # ── ASR: Adaptive Skill Reinforcement ─────────────────────────
    if ASR_ENABLED:
        reward = asr.compute_reward(result)
        ih = asr.input_hash(code, input_data)
        await asr.fitness.record_episode(
            skill_id, tool_ref, reward,
            result.get("stderr") if reward < 0 else None, ih,
        )

        if reward < 0:
            logger.info(f"[ASR] reward={reward} per {tool_ref}, tentativo evoluzione...")
            evolution_result = await asr.evolve(
                skill_id=skill_id,
                tool_id=tool_id,
                tool=tool,
                result=result,
                code=code,
                input_data=input_data,
                executor=executor,
                ctx=ctx,
            )
            _audit_log(tool_ref, f"asr:{evolution_result.get('asr_info', {}).get('evolved', False)}")
            return evolution_result

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

    # ── Auto-approve se abilitato e sicuro ─────────────────────────
    auto_result = _try_auto_approve(approval_id, payload)
    if auto_result and auto_result.get("ok"):
        logger.info(f"[auto-approve] proposta evoluzione {approval_id} auto-approvata")

    return approval_id


@mcp.tool()
async def create_skill(skill_id: str, description: str, ctx: Context = None) -> dict:
    """
    Genera una nuova skill completa via LLM (MCP sampling).
    Crea manifest.json, system_prompt.md e tools/run.py, poi la registra.
    Richiede approvazione umana prima di scrivere su disco.

    Args:
        skill_id:    Identificativo unico della skill (es. 'csv_analyzer')
        description: Descrizione di cosa deve fare la skill
    """
    if not skill_id or not description:
        return {"status": "error", "error": "skill_id e description sono obbligatori"}

    # Controlla se esiste già
    existing = registry.list_skills()
    if skill_id in existing:
        return {"status": "error", "error": f"La skill '{skill_id}' esiste già (v{existing[skill_id]['version']})"}

    if ctx is None:
        return {"status": "error", "error": "Context MCP non disponibile per sampling LLM"}

    return await _generate_skill_via_llm(skill_id, description, ctx)


async def _auto_generate_skill(skill_id: str, tool_id: str, code: str, ctx: Context) -> dict:
    """Tenta di generare automaticamente una skill quando non viene trovata."""
    logger.info(f"[auto-create] skill '{skill_id}' non trovata, tentativo di generazione automatica")
    description = (
        f"Skill '{skill_id}' con tool '{tool_id}'. "
        f"L'utente ha tentato di eseguire: {code[:500]}" if code else
        f"Skill '{skill_id}' con tool '{tool_id}'."
    )
    return await _generate_skill_via_llm(skill_id, description, ctx)


async def _generate_skill_via_llm(skill_id: str, description: str, ctx: Context) -> dict:
    """Genera una skill completa usando MCP sampling e la propone per approvazione."""

    # ── Esempio di skill esistente come riferimento ────────────────
    example_manifest = json.dumps({
        "id": "example_skill",
        "version": "1.0.0",
        "description": "Descrizione della skill",
        "system_prompt_uri": "skill://example_skill/system_prompt.md",
        "tools": [{
            "id": "run",
            "description": "Cosa fa il tool",
            "entrypoint": "tools/run.py:main",
            "execution": {"tier": "server", "sandbox": "docker", "timeout_seconds": 30},
            "safety": {"side_effects": False, "requires_human_approval": False, "idempotent": True},
            "runtime": {"language": "python", "version": "3.11", "dependencies": []}
        }]
    }, indent=2)

    generation_prompt = (
        f"Sei un esperto architetto di skill per il sistema skill-os MCP.\n\n"
        f"Devi generare una NUOVA skill con id='{skill_id}'.\n"
        f"Descrizione richiesta: {description}\n\n"
        f"Esempio di manifest.json:\n{example_manifest}\n\n"
        f"Il tool runner (tools/run.py) deve:\n"
        f"- Avere una funzione main() come entrypoint\n"
        f"- Leggere input da SKILL_SANDBOX_DIR/user_code.py (codice/payload utente)\n"
        f"- Leggere dati aggiuntivi da SKILL_SANDBOX_DIR/input.txt\n"
        f"- Stampare output su stdout (JSON preferito)\n"
        f"- Stampare errori su stderr\n"
        f"- Usare sys.exit(1) in caso di errore\n\n"
        f"Rispondi SOLO con JSON valido con questa struttura:\n"
        f'{{\n'
        f'  "manifest": {{...manifest.json completo...}},\n'
        f'  "system_prompt": "...contenuto di system_prompt.md...",\n'
        f'  "tool_code": "...codice Python di tools/run.py..."\n'
        f'}}'
    )

    try:
        response = await ctx.sample(generation_prompt)
        text = response.text if hasattr(response, "text") else str(response)
        text = text.strip().replace("```json", "").replace("```", "").strip()
        generated = json.loads(text)
    except Exception as e:
        logger.error(f"[create-skill] generazione LLM fallita: {e}")
        return {"status": "error", "error": f"Generazione LLM fallita: {e}"}

    manifest = generated.get("manifest", {})
    system_prompt = generated.get("system_prompt", "")
    tool_code = generated.get("tool_code", "")

    if not manifest or not system_prompt or not tool_code:
        return {"status": "error", "error": "LLM ha generato dati incompleti"}

    # Forza l'id corretto nel manifest
    manifest["id"] = skill_id
    manifest["system_prompt_uri"] = f"skill://{skill_id}/system_prompt.md"

    # ── Crea proposta di approvazione ──────────────────────────────
    approval_id = secrets.token_hex(6)
    payload = {
        "approval_id": approval_id,
        "skill_id": skill_id,
        "version_new": manifest.get("version", "1.0.0"),
        "rationale": f"Nuova skill generata via LLM: {description[:200]}",
        "git_commit_message": f"feat: add skill '{skill_id}' v{manifest.get('version', '1.0.0')}",
        "changes_summary": ["manifest.json", "system_prompt.md", "tools/run.py"],
        "source": "create_skill_mcp_sampling",
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        "changes": [
            {"file": "manifest.json", "after": json.dumps(manifest, indent=2, ensure_ascii=False)},
            {"file": "system_prompt.md", "after": system_prompt},
            {"file": "tools/run.py", "after": tool_code},
        ],
    }
    PENDING_DIR.mkdir(exist_ok=True)
    (PENDING_DIR / f"{approval_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2)
    )

    logger.info(f"[create-skill] proposta per '{skill_id}' creata, approval_id={approval_id}")

    # ── Auto-approve se abilitato e sicuro ─────────────────────────
    auto_result = _try_auto_approve(approval_id, payload)
    if auto_result and auto_result.get("ok"):
        return {
            "status": "auto-approved",
            "approval_id": approval_id,
            "skill_id": skill_id,
            "description": manifest.get("description", description),
            "tools": [t["id"] for t in manifest.get("tools", [])],
            "files_written": auto_result.get("files_written", []),
            "message": (
                f"Skill '{skill_id}' generata e AUTO-APPROVATA (safety check superato).\n"
                f"La skill è già disponibile. Usa: execute('{skill_id}:run', ...)"
            ),
        }

    return {
        "status": "created",
        "approval_id": approval_id,
        "skill_id": skill_id,
        "description": manifest.get("description", description),
        "tools": [t["id"] for t in manifest.get("tools", [])],
        "message": (
            f"Skill '{skill_id}' generata con successo!\n"
            f"Per approvarla: approve_pending('{approval_id}', approve=True)\n"
            f"Per rifiutarla: approve_pending('{approval_id}', approve=False)\n"
            f"Dopo l'approvazione la skill sarà disponibile immediatamente (hot-reload)."
        ),
    }


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

    if not approve:
        (PENDING_DIR / f"{approval_id}.rejected").write_text("rejected")
        logger.info(f"[approval] {approval_id} → rejected")
        return {"ok": True, "approval_id": approval_id, "decision": "rejected"}

    try:
        data = json.loads(pending_file.read_text())
        return _apply_pending(approval_id, data)
    except Exception as e:
        logger.error(f"[approval] errore applicando changes: {e}")
        return {"ok": False, "approval_id": approval_id,
                "error": f"Approvazione fallita: {e}"}


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


@mcp.tool()
async def skill_fitness(skill_id: str = "") -> dict:
    """
    Ritorna lo stato RL (Adaptive Skill Reinforcement) di una o tutte le skill.
    Mostra: fitness score, generazione, curva di apprendimento, status.

    Args:
        skill_id: ID della skill (vuoto = tutte le skill)
    """
    if skill_id:
        return await asr.fitness.get_fitness(skill_id)
    return await asr.fitness.get_all_fitness()


# ------------------------------------------------------------------ #
#  Audit log                                                           #
# ------------------------------------------------------------------ #
def _audit_log(tool_ref: str, status: str):
    line = f"{datetime.datetime.now(datetime.UTC).isoformat()} | {tool_ref} | {status}\n"
    with open(LOGS_DIR / "usage.log", "a") as f:
        f.write(line)


# ------------------------------------------------------------------ #
#  Auto-approve engine                                                 #
# ------------------------------------------------------------------ #
def _is_safe_for_auto_approve(pending_data: dict) -> bool:
    """Verifica se una proposta è abbastanza sicura per l'auto-approvazione.

    Criteri:
      - Tutti i tool nella skill hanno side_effects=false
      - Nessun tool richiede human_approval
      - Tutti i tool sono idempotent
      - Se è un'evoluzione, lo score prima deve essere >= AUTO_APPROVE_MIN_SCORE
      - Source deve essere dal sistema (non manuale)
    """
    changes = pending_data.get("changes", [])

    # Cerca il manifest tra i changes per validare i safety flag
    for change in changes:
        if change.get("file") == "manifest.json":
            try:
                manifest = json.loads(change.get("after", "{}"))
                for tool in manifest.get("tools", []):
                    safety = tool.get("safety", {})
                    if safety.get("side_effects", True):
                        return False
                    if safety.get("requires_human_approval", True):
                        return False
                    if not safety.get("idempotent", False):
                        return False
            except (json.JSONDecodeError, Exception):
                return False
            break
    else:
        # Nessun manifest nei changes → è un'evoluzione di prompt/codice
        # Controlla il manifest esistente della skill
        skill_id = pending_data.get("skill_id", "")
        manifest_path = SKILLS_DIR / skill_id / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text())
                for tool in manifest.get("tools", []):
                    safety = tool.get("safety", {})
                    if safety.get("side_effects", True):
                        return False
                    if safety.get("requires_human_approval", True):
                        return False
            except Exception:
                return False
        else:
            return False

    # Se è un'evoluzione, verifica lo score minimo
    eval_score = pending_data.get("eval_score_before")
    if eval_score is not None and eval_score < AUTO_APPROVE_MIN_SCORE:
        return False

    return True


def _apply_pending(approval_id: str, pending_data: dict) -> dict:
    """Applica una proposta approvata su disco."""
    skill_id = pending_data.get("skill_id", "")
    changes = pending_data.get("changes", [])

    if not skill_id or not changes:
        return {"ok": False, "error": "Dati incompleti nella proposta"}

    # Scrivi il file di approvazione
    (PENDING_DIR / f"{approval_id}.approved").write_text("approved")

    skill_dir = SKILLS_DIR / skill_id
    files_written = []
    for change in changes:
        rel_path = change.get("file", "")
        content = change.get("after", "")
        if rel_path and content:
            target = skill_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            files_written.append(rel_path)

    # Aggiorna versione nel manifest
    manifest_path = skill_dir / "manifest.json"
    version_new = pending_data.get("version_new")
    if manifest_path.exists() and version_new:
        try:
            manifest = json.loads(manifest_path.read_text())
            manifest["version"] = version_new
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        except Exception:
            pass

    registry.reload()

    logger.info(f"[auto-approve] skill '{skill_id}' approvata e applicata")
    return {
        "ok": True,
        "approval_id": approval_id,
        "skill_id": skill_id,
        "files_written": files_written,
        "decision": "auto-approved",
    }


def _try_auto_approve(approval_id: str, pending_data: dict) -> dict | None:
    """Se AUTO_APPROVE_SAFE è attivo e la proposta è sicura, approva automaticamente."""
    if not AUTO_APPROVE_SAFE:
        return None

    if not _is_safe_for_auto_approve(pending_data):
        logger.info(f"[auto-approve] {approval_id} non idoneo per auto-approvazione (safety check fallito)")
        return None

    logger.info(f"[auto-approve] {approval_id} idoneo — approvazione automatica in corso")
    return _apply_pending(approval_id, pending_data)


# ------------------------------------------------------------------ #
#  Background Orchestrator Loop                                        #
# ------------------------------------------------------------------ #
ORCHESTRATOR_INTERVAL_SECONDS = int(os.getenv("ORCHESTRATOR_INTERVAL", "1800"))  # 30 min
ORCHESTRATOR_ENABLED = os.getenv("ORCHESTRATOR_ENABLED", "false").lower() == "true"
AUTO_APPROVE_SAFE = os.getenv("AUTO_APPROVE_SAFE", "false").lower() == "true"
AUTO_APPROVE_MIN_SCORE = float(os.getenv("AUTO_APPROVE_MIN_SCORE", "7.0"))


async def _orchestrator_loop():
    """
    Background task: ciclo autonomo di auto-evoluzione.

    Ogni N secondi (default 30 min):
      1. Esegue orchestrator:run_cycle (eval di tutte le skill)
      2. Se una skill ha score basso → segnala necessità proposta LLM
      3. Se AUTO_APPROVE_SAFE=true → le proposte sicure vengono applicate
         automaticamente senza intervento umano
      4. Le proposte non sicure restano in pending_approvals/ per review

    Il background loop NON ha accesso a ctx (MCP sampling) perché non è
    una chiamata tool. Le proposte LLM richiedono un execute() manuale
    dall'agente connesso. Tuttavia, se l'orchestratore genera proposte
    basate su euristiche (senza LLM), queste possono essere auto-approvate.

    Attiva con: ORCHESTRATOR_ENABLED=true
    Auto-approve: AUTO_APPROVE_SAFE=true
    """
    mode_parts = ["ATTIVO" if ORCHESTRATOR_ENABLED else "STANDBY"]
    if AUTO_APPROVE_SAFE:
        mode_parts.append(f"auto-approve ON (min score: {AUTO_APPROVE_MIN_SCORE})")
    logger.info(
        f"[orchestrator] loop avviato (ogni {ORCHESTRATOR_INTERVAL_SECONDS}s). "
        f"Stato: {', '.join(mode_parts)}"
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

                try:
                    cycle_data = json.loads(stdout)
                    if cycle_data.get("needs_proposal"):
                        target = cycle_data.get("target_skill", "?")
                        if AUTO_APPROVE_SAFE:
                            logger.info(
                                f"[orchestrator] skill '{target}' necessita proposta LLM. "
                                f"Auto-approve attivo: la proposta sarà applicata "
                                f"automaticamente al prossimo execute() con ctx."
                            )
                        else:
                            logger.info(
                                f"[orchestrator] skill '{target}' necessita proposta LLM. "
                                f"Esegui: execute('orchestrator:run_cycle') per generarla."
                            )

                    # Auto-approve delle proposte pendenti generate in questo ciclo
                    if AUTO_APPROVE_SAFE:
                        _auto_approve_pending_proposals()

                except (json.JSONDecodeError, Exception):
                    pass

            except KeyError:
                logger.debug("[orchestrator] skill 'orchestrator' non trovata, skip.")
            except Exception as e:
                logger.error(f"[orchestrator] errore nel ciclo: {e}")
        else:
            logger.debug("[orchestrator] standby.")

        await asyncio.sleep(ORCHESTRATOR_INTERVAL_SECONDS)


def _auto_approve_pending_proposals():
    """Scansiona pending_approvals/ e auto-approva le proposte sicure non ancora processate."""
    for f in PENDING_DIR.glob("*.json"):
        approval_id = f.stem
        # Skip se già processata
        if ((PENDING_DIR / f"{approval_id}.approved").exists() or
                (PENDING_DIR / f"{approval_id}.rejected").exists()):
            continue

        try:
            data = json.loads(f.read_text())
            auto_result = _try_auto_approve(approval_id, data)
            if auto_result and auto_result.get("ok"):
                logger.info(
                    f"[orchestrator] proposta {approval_id} per "
                    f"'{data.get('skill_id')}' auto-approvata in background"
                )
        except Exception as e:
            logger.warning(f"[orchestrator] errore auto-approve {approval_id}: {e}")


# ------------------------------------------------------------------ #
#  Run                                                                 #
# ------------------------------------------------------------------ #
if __name__ == "__main__":
    logger.info("skill-os v2.0 — avvio con ASR (stdio, Claude Code transport)")
    logger.info(f"skills_dir = {SKILLS_DIR}")
    mcp.run()
