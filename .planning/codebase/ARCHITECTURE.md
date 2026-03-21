# Architecture

**Analysis Date:** 2026-03-20

## Pattern Overview

**Overall:** Modular Skill-Based MCP Server with Auto-Evolution Pipeline

skill-os implements a **skill registry pattern** where discrete, versioned tools (skills) are published to Claude via Model Context Protocol (MCP). The system supports autonomous improvement through a feedback loop: usage logs → skill evaluation → LLM-generated proposals → human approval → git-tracked updates.

**Key Characteristics:**
- **Plugin-based skill discovery**: Skills auto-discovered from `/skills/*/manifest.json` with hot-reload via watchdog
- **Sandboxed execution**: Tools run in Docker containers (user code) or subprocess (server-side tools) with resource limits
- **Human-in-the-loop approval**: Critical operations (skill updates) require explicit approval before execution
- **Git-tracked evolution**: Every skill update auto-commits with provenance, enabling rollback
- **MCP-based transport**: Stdio-based MCP protocol for seamless Claude Code integration

## Layers

**MCP Server (FastMCP):**
- Purpose: Expose tool interface to Claude via Model Context Protocol (stdio transport)
- Location: `server/main.py`
- Contains: Tool definitions (list_skills, get_prompt, execute, approve_pending, list_pending_approvals), background orchestrator loop
- Depends on: SkillRegistry, Executor, SafetyValidator
- Used by: Claude Code client (external)

**Skill Registry:**
- Purpose: Discover and index all skill manifests; provide lazy-loaded system prompts and tool definitions
- Location: `server/registry.py`
- Contains: SkillRegistry class (manifest parsing, hot-reload watcher), skill indexing
- Depends on: watchdog filesystem observer
- Used by: MCP Server, Executor (to resolve skill paths and definitions)

**Executor (Sandbox Manager):**
- Purpose: Execute tool code in isolated sandboxes with configurable isolation strategy
- Location: `server/executor.py`
- Contains: Docker container spawning, subprocess fallback, resource limits (256MB RAM, 0.5 CPUs), timeout handling
- Depends on: docker CLI, asyncio subprocess API
- Used by: MCP Server (to run tools), Orchestrator (to run eval and upsert)

**Safety & Approval System:**
- Purpose: Pre-execution validation, rate limiting, human approval workflow
- Location: `server/safety.py`
- Contains: SafetyViolation exception, RateLimiter (rolling window), approval flow state machine
- Depends on: Tool manifest safety declarations
- Used by: MCP Server (execute endpoint)

**Skill Management & Evolution:**
- Purpose: Evaluate skill quality and generate improvement proposals
- Location: `skills/skill_manager/`
- Contains:
  - `tools/eval.py`: Test harness with heuristic or LLM-powered scoring (0-10 scale)
  - `tools/upsert.py`: Applies approved changes (manifest, prompts, files) to skills, commits to git
  - `system_prompt.md`: Instructions for skill evaluation and update strategies
- Depends on: Executor (to test skills), git CLI, Anthropic API (optional)
- Used by: Orchestrator, Claude user (manual eval/upsert)

**Orchestrator (Auto-Evolution Agent):**
- Purpose: Autonomous improvement loop—analyzes logs, selects target skill, evaluates, proposes updates
- Location: `skills/orchestrator/`
- Contains:
  - `tools/run_cycle.py`: Log analysis, skill selection heuristic, eval invocation, proposal generation
  - `system_prompt.md`: Instructions for autonomous decision-making
- Depends on: skill_manager (eval), LLM (Claude Haiku for proposals), executor
- Used by: Background scheduler in main.py (every 30 min if enabled)

**Core Skill (Code Execution):**
- Purpose: Execute arbitrary Python code in sandbox as a platform service
- Location: `skills/python_exec/`
- Contains: `tools/run.py` (exec() in isolated namespace with user code mounting)
- Depends on: Docker for sandbox, stdlib exec()
- Used by: Claude user directly, skill_manager (for eval)

## Data Flow

**User Tool Execution Flow:**

1. Claude calls `execute('skill_id:tool_id', code, input_data)` via MCP
2. `main.py:execute()` parses tool_ref, retrieves tool definition from registry
3. Safety check: `check_execution(tool)` validates manifest safety constraints (rate limits, approval requirements)
4. If approval required: store in pending_approvals/, return pending_approval status
5. If approved/not-required: `executor.run()` selects sandbox strategy:
   - Docker: Mount user code, run in isolated container (python:3.11-slim, 256MB RAM, no network)
   - Subprocess: Run locally with SKILL_ROOT env var set (for server-side tools)
6. Capture stdout/stderr, return {status, stdout, stderr, exit_code}
7. Audit log written to `logs/usage.log`

**Skill Improvement Cycle (Manual):**

1. User calls `execute('skill_manager:eval_skill', code='{"skill_id":"X"}')`
2. eval.py runs default test cases for skill X in sandbox
3. Heuristic score (% passed) or LLM critique returned: score 0-10, test_results, recommendations
4. User reviews critique, calls `execute('skill_manager:upsert_skill', code='{...patch...}')`
5. upsert.py writes JSON to `pending_approvals/<id>.json`, returns approval_id
6. User calls `approve_pending(approval_id, approve=True)`
7. main.py creates .approved marker file
8. upsert.py detects marker, applies file changes, commits to git, logs to `logs/evolution.log`

**Autonomous Improvement (Background Loop):**

1. Every 30min (if ORCHESTRATOR_ENABLED=true), orchestrator:run_cycle executes
2. Parse `logs/usage.log` → aggregate skill usage stats (calls, error rate) for last 24h
3. Choose target skill: prioritize high-error-rate, exclude skill_manager and orchestrator itself
4. Check rate limit: max 3 upserts/skill/day
5. Call eval.py via subprocess → get eval_result with score and critique
6. If score < 8.5 and ANTHROPIC_API_KEY set: Call Claude Haiku with eval_result + current system_prompt
7. Haiku generates proposal JSON: rationale, new_system_prompt, git_commit_message
8. Write proposal to `pending_approvals/<id>.json`
9. Log cycle metadata to `logs/orchestrator.log`
10. No automatic application—proposal awaits human approval via approve_pending()

**State Management:**

- **In-Memory**: SkillRegistry._skills (skill index), RateLimiter._counts (execution counts)
- **Disk-based**:
  - `/skills/*/manifest.json`: Source of truth for skill definitions
  - `/skills/*/system_prompt.md`: Lazy-loaded LLM instructions
  - `/skills/*/tools/*.py`: Tool implementations
  - `/logs/usage.log`: TSV audit trail (timestamp | tool_ref | status)
  - `/logs/orchestrator.log`: JSON lines of auto-improvement cycles
  - `/logs/evolution.log`: Changes applied to skills (score before/after, git SHA)
  - `/pending_approvals/*.json`: Pending proposals + status markers (.approved, .rejected)
  - Git history: Full skill change tracking via commits (AI-evolution vX.Y messages)

## Key Abstractions

**Skill Manifest (Declarative Contract):**
- Purpose: Define skill identity, tools, safety constraints, runtime requirements
- Examples: `skills/python_exec/manifest.json`, `skills/skill_manager/manifest.json`
- Pattern: JSON schema with fixed fields: id, version, description, system_prompt_uri, tools[]
  - Each tool specifies: id, entrypoint (script:function), execution (sandbox, timeout), safety (side_effects, requires_human_approval, rate_limit), runtime (language, version, dependencies)

**Tool Reference (Routing Key):**
- Format: `skill_id:tool_id` (e.g., `python_exec:run_code`)
- Parsed in main.py execute() and used to resolve tool definitions and entrypoints
- Pattern: Colon-separated string for CLI-friendly references

**Sandbox Execution Strategy (Enum-like):**
- `docker`: Isolated container, no network, memory/CPU limits (default for user code)
- `none`: Subprocess on host (for skill_manager, orchestrator—they need file system access)
- `host`: Alias for `none`
- `mock`: Override via SKILL_OS_SANDBOX env var for local dev (forces subprocess)

**Approval Workflow (State Machine):**
- State: pending → approved/rejected/timeout
- Stored as: approval_<id>.json (request payload) + optional .approved/.rejected marker files
- Timeout: 300s default (APPROVAL_TIMEOUT_SECONDS)
- Pattern: Async file-based signaling (executor polls for marker files)

## Entry Points

**MCP Server Startup:**
- Location: `server/main.py` (if __name__ == "__main__")
- Triggers: `docker compose run skill-os` or direct Python invocation
- Responsibilities: Initialize FastMCP, load registry, start background orchestrator loop, expose tools to Claude

**CLI Tool Invocation:**
- MCP Tool: `execute(tool_ref, code, input_data)`
- Triggers: User calls from Claude Code
- Responsibilities: Dispatch to executor with sandbox strategy, capture output, audit

**Background Orchestrator Cycle:**
- Location: `skills/orchestrator/tools/run_cycle.py:main()`
- Triggers: asyncio.create_task(_orchestrator_loop) every 30min if ORCHESTRATOR_ENABLED=true
- Responsibilities: Analyze logs, select target, evaluate, propose, write pending approval

## Error Handling

**Strategy:** Fail-safe with detailed error messages

**Patterns:**

1. **Tool Resolution Errors**: If tool_ref invalid or skill/tool not found → return {status: "error", stderr: "Tool not found"}

2. **Sandbox Execution Errors**:
   - Timeout (>30s): {status: "error", exit_code: -1, stderr: "Timeout (30s) exceeded"}
   - Docker not found: {status: "error", exit_code: 127, stderr: "Docker not found — use SKILL_OS_SANDBOX=mock"}
   - Script not found: {status: "error", exit_code: 1, stderr: "Entrypoint not found: <path>"}

3. **Safety Violations**: Check_execution() raises SafetyViolation → caught in execute() → {status: "blocked", stderr: "[SAFETY] <violation reason>"}

4. **Rate Limit Exceeded**: RateLimiter.check() raises SafetyViolation → {status: "blocked", stderr: "Rate limit exceeded..."}

5. **Manifest Errors**: Malformed JSON, missing fields → logged at registry.reload(), skill skipped in index

6. **Approval Timeout**: upsert.py polls for .approved for 300s, falls back to "timeout" decision → no changes applied

## Cross-Cutting Concerns

**Logging:**
- Approach: Python logging to stderr (does not interfere with MCP stdio protocol)
- Per-module loggers: "skill-os", "skill-os.registry", "skill-os.executor", "skill-os.git", "skill-os.safety"
- Structured audit logs: TSV (usage.log) and JSON (orchestrator.log, evolution.log)

**Validation:**
- Manifest schema: Required fields (id, version, description, tools[].entrypoint) checked at registry.reload()
- Tool references: "skill_id:tool_id" format enforced in execute() before lookup
- Input data: User code and input_data written as files, not passed as arguments (safe against command injection)

**Authentication & Authorization:**
- No built-in auth (deployed in Claude Code which handles auth)
- Approval system acts as "permission gate" for side-effect operations
- Rate limits enforce per-tool quotas (manifest-declared)

**State Isolation:**
- Each tool execution has isolated tmpdir (user_code.py, input.txt mounted read-only)
- Docker sandbox: --read-only filesystem, no network, 256MB RAM, 0.5 CPUs
- Subprocess sandbox: env vars set (SKILL_SANDBOX_DIR, SKILL_ROOT) to limit access

---

*Architecture analysis: 2026-03-20*
