# Technology Stack

**Analysis Date:** 2026-03-20

## Languages

**Primary:**
- Python 3.11 - Core server, skill execution, all backend logic

**Secondary:**
- Shell (bash/sh) - Entrypoint script, Docker initialization
- JSON - Skill manifests, configuration, data interchange

## Runtime

**Environment:**
- Docker container (Python 3.11-slim base image)
- Entrypoint: `entrypoint.sh` bootstraps git repo and starts the server

**Package Manager:**
- pip - Python package management
- Lockfile: `requirements.txt` (minimal, only 2 core dependencies)

## Frameworks

**Core:**
- FastMCP 2.0.0+ - MCP server implementation, stdio transport for Claude Code integration
- watchdog 4.0.0+ - File system event monitoring for hot-reload of skill manifests

**Testing/Execution:**
- Docker (on production) - Sandboxed execution of user code
- Subprocess - Local execution for server-side tools (skill_manager, orchestrator)

**Build/Infrastructure:**
- docker-compose 3.9 - Orchestration of skill-os container
- Git (via git CLI) - Version control and commit automation

## Key Dependencies

**Critical:**
- fastmcp>=2.0.0 - MCP server for Claude Code integration (stdio channel)
- watchdog>=4.0.0 - Hot-reload monitoring of `/skills/*` directory

**Runtime/Execution:**
- subprocess - Async execution engine for Docker and local tools
- urllib.request - HTTP client for Anthropic API calls (no external HTTP library used)
- tempfile - Temporary directory creation for sandboxed execution
- json - JSON parsing and generation for manifests and tool I/O

## Configuration

**Environment Variables:**
- `SKILL_OS_SANDBOX` - Execution sandbox mode: "docker" (production) or "mock" (development with local subprocess)
- `ORCHESTRATOR_ENABLED` - Enable autonomous skill evolution loop: "true" or "false" (default)
- `ORCHESTRATOR_INTERVAL` - Background loop interval in seconds (default: 1800 = 30 minutes)
- `ANTHROPIC_API_KEY` - Optional Anthropic API key for LLM-powered skill evaluation and proposal generation
- `APPROVAL_TIMEOUT_SECONDS` - Timeout for human approval decisions (default: 300)

**Build Configuration:**
- `Dockerfile` - Python 3.11-slim base, installs git and requirements
- `docker-compose.yml` - Mounts project directory, Docker socket (for nested containers), configures stdio transport
- `.mcp.json` - Claude Code MCP server configuration (docker compose run)

**File Structure for Runtime:**
- `/app/logs/` - Audit logs (usage.log, orchestrator.log, evolution.log)
- `/app/pending_approvals/` - Approval request storage (JSON files + decision markers)

## Platform Requirements

**Development:**
- Docker Desktop (or Docker Engine with CLI)
- Git (for version control)
- Python 3.11+ (only for local testing without Docker)

**Production:**
- Docker Engine with socket access for nested container execution
- Git repository initialization support

## Sandbox Execution

**Docker Mode (production):**
- Image: python:3.11-slim
- Resource limits: 256MB RAM, 0.5 CPU, network disabled, read-only filesystem except tmpfs
- Timeout: 30 seconds (configurable per tool)

**Local/Mock Mode (development):**
- Subprocess execution on host
- Used for server-side tools (skill_manager, orchestrator) regardless of mode
- Forced globally when `SKILL_OS_SANDBOX=mock`

## External API Calls

**Anthropic Claude API:**
- Endpoint: `https://api.anthropic.com/v1/messages`
- Model: claude-haiku-4-5-20251001
- Used for: Skill evaluation critique and improvement proposals
- Auth: Bearer via `x-api-key` header
- Implementation: Raw urllib.request (no SDK dependency)

---

*Stack analysis: 2026-03-20*
