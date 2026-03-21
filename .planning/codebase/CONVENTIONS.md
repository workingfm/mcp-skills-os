# Coding Conventions

**Analysis Date:** 2026-03-20

## Naming Patterns

**Files:**
- Lowercase with underscores: `main.py`, `registry.py`, `executor.py`, `git_helper.py`
- Tools/scripts: `run.py`, `eval.py`, `upsert.py`, `run_cycle.py` (single word or underscore-separated)
- No file extensions in imports (native Python)

**Functions:**
- camelCase for private helpers prefixed with underscore: `_run_git()`, `_run_docker()`, `_exec()`, `_run_local()`, `_run_eval()`, `_parse_usage_log()`
- snake_case for public functions: `list_skills()`, `get_prompt()`, `execute()`, `approve_pending()`, `check_execution()`, `validate_manifest()`, `commit_skill_update()`, `rollback_skill()`, `get_skill_history()`
- Single underscore prefix indicates module-private scope (not class private)

**Variables:**
- snake_case throughout: `skill_id`, `tool_ref`, `approval_id`, `exit_code`, `exec_globals`, `user_code`, `skill_root`
- ALL_CAPS for module-level constants: `REPO_ROOT`, `SKILLS_DIR`, `LOGS_DIR`, `PENDING_DIR`, `SANDBOX_MODE`, `SCORE_THRESHOLD`, `MAX_UPSERTS_PER_DAY`, `APPROVAL_TIMEOUT_SECONDS`, `EXCLUDE_SKILLS`, `ANTHROPIC_API_KEY`, `DEFAULT_TEST_CASES`
- Descriptive names: `approval_payload`, `pending_file`, `decision_file`, `modified_files`, `test_results`

**Types:**
- PascalCase for classes: `SkillRegistry`, `Executor`, `SafetyViolation`, `PendingApprovalStore`, `RateLimiter`, `_SkillReloadHandler`, `FastMCP`
- Private classes prefixed with underscore: `_SkillReloadHandler`

## Code Style

**Formatting:**
- No explicit linter/formatter detected (pylint, black, etc.)
- 4-space indentation used consistently
- Line length varies but generally around 100-120 characters
- Blank lines used to separate logical sections within functions
- Comment blocks use `# ` for single-line and triple-quoted strings for docstrings

**Linting:**
- No formal linting config found (no `.pylintrc`, `.flake8`, or `setup.cfg`)
- Code follows PEP 8 general patterns (snake_case, class naming)

## Import Organization

**Order:**
1. Standard library imports (asyncio, json, logging, os, sys, datetime, time, subprocess, threading, tempfile, traceback, hashlib, urllib.request)
2. Third-party imports (fastmcp, watchdog, pathlib)
3. Local imports (relative module imports like `from registry import SkillRegistry`)

**Pattern observed in `main.py`:**
```python
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # Local path injection

from fastmcp import FastMCP
from registry import SkillRegistry
from executor import Executor
from safety import SafetyViolation, check_execution
```

**Imports within functions:**
- Deferred imports allowed for conditional logic: `import datetime` (inside `_audit_log()` in `main.py`)
- Libraries imported late if needed only in specific code paths: `import urllib.request` (inside `_llm_critique()` in `eval.py`)
- Late imports reduce startup overhead in heavily-used modules

**Path Aliases:**
- No path aliases detected (no `@` syntax, no `jsconfig.json` or similar)
- Absolute imports from repo root via `sys.path.insert(0, ...)`

## Error Handling

**Patterns:**
- Try/except for expected failures: file not found, JSON decode errors, subprocess timeouts
- Specific exception catching: `except (FileNotFoundError, KeyError)`, `except asyncio.TimeoutError`, `except subprocess.TimeoutExpired`, `except json.JSONDecodeError`
- Generic catch-all as fallback: `except Exception as e` used when recovery is needed without detailed handling
- Silent pass on non-critical errors: `except Exception: pass` (e.g., process kill in `executor.py` line 118)
- Custom exceptions for domain logic: `SafetyViolation` raised by safety validation layer

**Return values on error:**
- Functions return dict with status field: `{"status": "error", "stdout": "", "exit_code": 1, "stderr": "..."}` (see `executor.py`)
- Status field values: `"ok"`, `"error"`, `"blocked"`, `"pending_approval"`, `"cancelled"`
- No exception propagation to caller in `execute()` MCP tool — all errors caught and returned as dict

**Error messages:**
- Descriptive and contextual: `f"[SAFETY] {e}"`, `f"Tool '{tool_id}' non trovato in skill '{skill_id}'"`
- Prefixed with context tags: `[SAFETY]`, `[ERROR]`, `[git]`, `[registry]`, `[executor]`, `[safety]`, `[approval]`, `[orchestrator]`

## Logging

**Framework:** `logging` module (standard library)

**Setup pattern (main.py):**
```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("skill-os")
logger.info("Message")
```

**Module-level loggers:**
- One logger per module: `logging.getLogger("skill-os.registry")`, `logging.getLogger("skill-os.executor")`, `logging.getLogger("skill-os.safety")`
- Namespace convention: `skill-os.<module_name>`

**Logging patterns:**
- INFO level for lifecycle events: `logger.info(f"[registry] caricata skill '{skill_id}' (v{version})")`
- DEBUG level for verbose events: `logger.debug("[orchestrator] standby.")`
- WARNING level for non-blocking issues: `logger.warning(f"[safety] ⚠️  '{tool.get('id')}': side_effects=true ma sandbox=none.")`
- ERROR level for failures: `logger.error(f"[orchestrator] errore nel ciclo: {e}")`
- Contextual tags in message: `[registry]`, `[executor]`, `[safety]`, `[git]`, `[approval]`
- Avoid logging secrets: no API keys, no sensitive data in log messages

**Audit logging:**
- Separate append-only log file: `/logs/usage.log` (format: `timestamp | tool_ref | status\n`)
- Evolution log: `/logs/evolution.log` (format: `timestamp | skill_id | score_before | score_after | action | git_sha\n`)
- Orchestrator log: `/logs/orchestrator.log` (format: JSON per line)

## Comments

**When to Comment:**
- Module docstrings (triple-quoted) for every `.py` file, explaining purpose and high-level flow
- Inline comments for non-obvious logic or workarounds
- ASCII section headers for logical groupings: `# ------------------------------------------------------------------ #  Comment`
- Italian language used throughout (matching docstrings and log messages)

**JSDoc/TSDoc:**
- Standard Python docstrings (triple quotes) for all public functions and classes
- Format: Brief description first line, then detailed explanation if needed
- Example from `registry.py`:
  ```python
  def list_skills(self) -> dict:
      """
      Ritorna il catalogo pubblico di tutte le skill
      (senza path interni).
      """
  ```
- Example with return value: from `safety.py`:
  ```python
  def check_execution(tool: dict) -> bool:
      """
      Valida il tool. Ritorna True se richiede approvazione umana.
      Solleva SafetyViolation per violazioni bloccanti.
      """
  ```

**Comments on logic:**
- Strategic comments before complex sections: see `executor.py` line 46 "Scegli modalità: mock globale, oppure sandbox dal manifest"
- Comments explain the "why", not the "what": `# Timeout (`timeout`s superato)` explains the timeout context
- Avoid obvious comments: no need to comment `skill_id = params.get("skill_id")`

## Function Design

**Size:**
- Functions range from 5 lines (helpers like `_run_git()`) to 100+ lines (orchestration logic in `run_cycle.py`)
- Longer functions are multi-step workflows with clear step comments
- No strict line limit observed, but complex functions broken into private helpers

**Parameters:**
- Positional parameters for required args: `def run(self, skill_id: str, tool_id: str, tool: dict, code: str, input_data: str = "")`
- Type hints used consistently: all function parameters and returns have type annotations
- Optional parameters with default values: `input_data: str = ""`, `timeout: int = 30`, `approve: bool = True`
- Dict parameters for flexible payloads: functions accept `dict` and extract specific keys (see `eval.py` accepting `tool: dict`)

**Return Values:**
- Functions return dict for complex results: `{"status": "ok", "stdout": "...", "exit_code": 0}`
- Functions return specific types when simple: `list_skills() -> dict`, `get_prompt(skill_id: str) -> str`, `check_execution(tool: dict) -> bool`
- Tuple returns for multiple related values: `_run_git() -> tuple[int, str, str]` (returncode, stdout, stderr), `_choose_target() -> tuple[str, str] | tuple[None, None]`
- None returns for optional results: `_generate_proposal(...) -> dict | None`

## Module Design

**Exports:**
- No explicit `__all__` declarations observed
- Public functions and classes are module-level (no underscore prefix): `SkillRegistry`, `Executor`, `SafetyViolation`, `list_skills()`, `execute()`
- Private functions prefixed with underscore: `_run_git()`, `_audit_log()`, `_parse_usage_log()`
- Private classes prefixed with underscore: `_SkillReloadHandler`

**Barrel Files:**
- Not used in this codebase
- Each module imported individually: `from registry import SkillRegistry` (not `from server import *`)

**Module responsibilities:**
- `main.py`: MCP server entry point, tool definitions, orchestrator background loop
- `registry.py`: Skill discovery and hot-reload via watchdog
- `executor.py`: Sandbox execution (Docker or local subprocess)
- `safety.py`: Pre-execution validation, rate limiting, approval workflows
- `git_helper.py`: Git operations (commit, rollback, history)
- `skills/**/tools/*.py`: Tool implementations (eval.py, upsert.py, run.py, run_cycle.py)

**Loose coupling:**
- Modules interact through simple dict/tuple contracts (no tight inheritance)
- Central registry (`SkillRegistry`) acts as discovery layer — executors don't hard-code skill locations
- Tool execution is decoupled from tool definition via subprocess/Docker

---

*Convention analysis: 2026-03-20*
