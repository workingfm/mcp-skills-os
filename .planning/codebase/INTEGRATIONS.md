# External Integrations

**Analysis Date:** 2026-03-20

## APIs & External Services

**Anthropic Claude API:**
- Service: LLM-powered skill evaluation and improvement proposal generation
  - Endpoint: `https://api.anthropic.com/v1/messages`
  - Model: claude-haiku-4-5-20251001
  - Auth: API key via `x-api-key` header
  - Env var: `ANTHROPIC_API_KEY`
  - Uses: `urllib.request` (no SDK)

**Used in:**
- `skills/skill_manager/tools/eval.py:_llm_critique()` - Generates structured critique of skill test results (lines 63-101)
- `skills/orchestrator/tools/run_cycle.py:_generate_proposal()` - Generates improvement proposals for system prompts (lines 135-176)

## Data Storage

**Databases:**
- None - No persistent database backend

**File Storage:**
- Local filesystem only
- Locations:
  - `/app/skills/` - Skill definitions (manifests, prompts, tools)
  - `/app/logs/` - Audit logs (usage.log, orchestrator.log, evolution.log)
  - `/app/pending_approvals/` - Approval request tracking (JSON + decision markers)
  - Git repository (skill-os-docker/) for version control

**Caching:**
- In-memory registry in `SkillRegistry` class (`server/registry.py`)
- Thread-safe dictionary of loaded skill manifests
- Hot-reload via watchdog file system events (no cache invalidation needed)

## Authentication & Identity

**Auth Provider:**
- None for user-facing API
- MCP protocol: stdio-based (no authentication, embedded in Docker container)
- Anthropic API key: environment variable only (no session/token management)

**Git Identity:**
- Fixed identity: `skill-os-agent <agent@skill-os.local>` for automatic commits
- No user credentials stored or managed

## Monitoring & Observability

**Error Tracking:**
- None - No external error tracking service

**Logs:**
- Approach: File-based logging to `/app/logs/` directory
- Formats:
  - `usage.log` - Audit trail: timestamp | tool_ref | status (lines 163-167 in `server/main.py`)
  - `orchestrator.log` - JSON-formatted orchestration cycle events (lines 215-219 in `skills/orchestrator/tools/run_cycle.py`)
  - `evolution.log` - Evolution/upgrade tracking (referenced in `run_cycle.py` for rate limiting)
- Logger: Python `logging` module to stderr (doesn't interfere with stdio MCP transport)

## CI/CD & Deployment

**Hosting:**
- Docker container (self-contained, portable)
- Execution context: Claude Code IDE (via MCP protocol)
- Container orchestration: docker-compose

**CI Pipeline:**
- None configured - Manual deployment via `docker compose build`

## Environment Configuration

**Required env vars:**
- None mandatory (all have sensible defaults)

**Optional but important:**
- `ANTHROPIC_API_KEY` - Required for LLM-powered evaluation and proposal generation
  - Without it: System falls back to heuristic scoring (pass/fail ratio)
  - Source: `.env` file (or command line export)

**Secrets location:**
- `.env` file (should be in `.gitignore`)
- `.env.example` provided as template
- No other secret storage mechanism

## Webhooks & Callbacks

**Incoming:**
- None - MCP protocol handles request/response via stdio

**Outgoing:**
- None - No webhook callbacks to external services

## MCP Protocol Integration

**Protocol:**
- Model Context Protocol (MCP)
- Transport: stdio (stdin/stdout)
- Configuration: `.mcp.json` defines server launch via `docker compose run`

**Server Location:**
- `server/main.py` - FastMCP server entry point
- Exposed tools:
  - `list_skills()` - Discover available skills
  - `get_prompt(skill_id)` - Lazy-load skill system prompts
  - `execute(tool_ref, code, input_data)` - Execute tools in sandbox
  - `approve_pending(approval_id, approve)` - Human approval of upserts
  - `list_pending_approvals()` - List pending decisions

## Container Execution

**Nested Docker (when SKILL_OS_SANDBOX=docker):**
- Parent: skill-os container (Python 3.11)
- Child: Ephemeral python:3.11-slim containers for user code
- Communication: Docker socket mount at `/var/run/docker.sock`
- Resource isolation: Memory (256MB), CPU (0.5), network (disabled), filesystem (read-only except tmpfs)

## Git Integration

**Version Control:**
- Repository: Local git repo at project root
- No remote configuration (user manages git push separately)

**Automatic Commits:**
- Triggered by: `skills/skill_manager/tools/upsert.py` after approval
- Committer identity: skill-os-agent <agent@skill-os.local>
- Commit message format: `AI-evolution v{version} - {reason}` (for upgrades) or `AI-rollback {skill_id} → {sha}` (for rollbacks)
- Implementation: `server/git_helper.py` (wrapper around git CLI)

---

*Integration audit: 2026-03-20*
