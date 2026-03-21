"""
Safety — validazione pre-esecuzione dei tool.

Il manifest dichiara il contratto di sicurezza:
  {
    "safety": {
      "side_effects": false,
      "requires_human_approval": false,
      "idempotent": true,
      "rate_limit": { "max_per_day": 3 }
    }
  }

NOTA: requires_human_approval non blocca più qui.
      Il flusso di approvazione è gestito in main.py
      tramite file-based approval (pending_approvals/).
"""
import logging
import time
from collections import defaultdict

logger = logging.getLogger("skill-os.safety")


class SafetyViolation(Exception):
    """Sollevata quando un tool non può essere eseguito."""
    pass


class RateLimiter:
    """Rate limiting in-memory con rolling window giornaliera."""

    def __init__(self):
        self._counts: dict[str, list[float]] = defaultdict(list)

    def check(self, tool: dict) -> None:
        safety = tool.get("safety", {})
        rate_limit = safety.get("rate_limit", {})
        max_per_day = rate_limit.get("max_per_day")
        if not max_per_day:
            return

        tool_id = tool.get("id", "unknown")
        now = time.time()
        self._counts[tool_id] = [t for t in self._counts[tool_id] if t > now - 86400]

        if len(self._counts[tool_id]) >= max_per_day:
            raise SafetyViolation(
                f"Rate limit superato per '{tool_id}': "
                f"max {max_per_day}/giorno. "
                f"Eseguite oggi: {len(self._counts[tool_id])}."
            )
        self._counts[tool_id].append(now)


def check_execution(tool: dict) -> bool:
    """
    Valida il tool. Ritorna True se richiede approvazione umana.
    Solleva SafetyViolation per violazioni bloccanti.
    """
    execution = tool.get("execution", {})
    tier = execution.get("tier", "server")
    if tier not in ("server", "client"):
        raise SafetyViolation(f"execution.tier non valido: '{tier}'.")

    safety = tool.get("safety", {})
    if safety.get("side_effects", False):
        if execution.get("sandbox", "none") == "none":
            logger.warning(f"[safety] ⚠️  '{tool.get('id')}': side_effects=true ma sandbox=none.")

    return safety.get("requires_human_approval", False)


def validate_manifest(manifest: dict) -> list[str]:
    warnings = []
    for f in ["id", "version", "description"]:
        if f not in manifest:
            warnings.append(f"Campo mancante nel manifest: '{f}'")
    for tool in manifest.get("tools", []):
        if "entrypoint" not in tool:
            warnings.append(f"Tool '{tool.get('id','?')}' non ha 'entrypoint'.")
    return warnings
