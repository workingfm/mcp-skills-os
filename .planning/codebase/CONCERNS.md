# Codebase Concerns

**Analysis Date:** 2026-03-20

## Tech Debt

**Hard-coded file paths in sandbox execution:**
- Issue: File paths for sandbox mounts in `executor.py` use hardcoded strings like `/sandbox/run.py` and `/sandbox/user_code.py`. If sandbox container layout changes, multiple files must be updated.
- Files: `server/executor.py` (lines 68, 76), `skills/python_exec/tools/run.py` (lines 13-14)
- Impact: Difficult to refactor sandbox setup; brittle cross-file contracts
- Fix approach: Create a constants module defining sandbox layout contract, import in both executor and sandbox script

**Global environment state in safety.py:**
- Issue: `RateLimiter` and `PendingApprovalStore` are module-scoped singletons not instantiated in `main.py`, though safety.py imports indicate they exist. However, `PendingApprovalStore` is defined but never used—approval flow is purely file-based.
- Files: `server/safety.py` (lines 30-73)
- Impact: Dead code adds confusion; inconsistency between intended (in-memory store) and actual (file-based) approval handling
- Fix approach: Remove unused `PendingApprovalStore` class or integrate it properly into main.py's execution flow

**Error handling with bare except clauses:**
- Issue: Multiple locations catch all exceptions without distinguishing error types
- Files: `server/registry.py` (line 58: `except Exception`), `skills/skill_manager/tools/eval.py` (lines 98, 123: bare `except Exception`), `skills/orchestrator/tools/run_cycle.py` (line 127: `json.JSONDecodeError` handler catches after broad `except Exception`)
- Impact: Masks programming errors and unexpected failures; makes debugging harder
- Fix approach: Catch specific exception types (FileNotFoundError, JSONDecodeError, subprocess.TimeoutExpired, etc.)

**No validation of user skill manifests:**
- Issue: `registry.py` loads manifests without validating required fields or structure beyond basic error handling. Invalid manifests will silently fail to load.
- Files: `server/registry.py` (lines 50-59)
- Impact: If a skill is added with broken manifest, it silently disappears from registry with only a log message
- Fix approach: Call `safety.validate_manifest()` (exists but unused) during registry.reload() and return warnings

**Type hints missing:**
- Issue: Python 3.11 codebase has minimal type annotations (only some function signatures use types)
- Files: Most Python files lack return type hints and parameter annotations
- Impact: IDE autocomplete limited; harder to catch type errors before runtime
- Fix approach: Add `from typing import *` and annotate all public function signatures

## Security Considerations

**Docker socket mounted in compose without restrictions:**
- Risk: Container has write access to host's Docker daemon. A compromised skill could spawn privileged containers or attack host.
- Files: `docker-compose.yml` (line 16)
- Current mitigation: Skills are meant to be trusted (author-written). But if someone adds a malicious skill, sandbox bypass is possible.
- Recommendations:
  - Add Docker API call logging/auditing
  - Consider running Docker daemon in rootless mode
  - Add resource quotas (ulimits) in sandbox `docker run` commands
  - Document security posture: "Skills must be from trusted sources"

**Arbitrary code execution in user sandbox:**
- Risk: `python_exec:run_code` executes user Python code via `exec()` with minimal restrictions. While Docker isolates, the Python execution model is unsafe.
- Files: `skills/python_exec/tools/run.py` (line 40), `server/executor.py` (lines 71-79 Docker command)
- Current mitigation: Docker container has --read-only, --network=none, 256MB memory limit, 0.5 CPU
- Recommendations:
  - Add timeout enforcement at Docker level (not just subprocess timeout)
  - Log all sandbox executions for audit trail
  - Consider running sandbox image as non-root user
  - Document: "User code executes in ephemeral Docker container with resource limits"

**API key exposed in environment variables:**
- Risk: `ANTHROPIC_API_KEY` passed as env var in docker-compose, stored unencrypted in container memory and logs
- Files: `docker-compose.yml` (line 30), `skills/skill_manager/tools/eval.py` (line 19), `skills/orchestrator/tools/run_cycle.py` (line 22)
- Current mitigation: `.env.example` documents it but `.env` is in .gitignore (good)
- Recommendations:
  - Never log ANTHROPIC_API_KEY values (currently line 113 in main.py logs code length but not API key—good)
  - Use `.env` file with docker-compose and avoid committing it
  - Consider rotating API key periodically if stored long-term
  - Document in README that API key is sensitive

**Git commits signed as generic agent without verification:**
- Risk: `git_helper.py` commits as `agent@skill-os.local` without GPG signing. An attacker with repo access could forge evolution commits.
- Files: `server/git_helper.py` (line 40), `skills/skill_manager/tools/upsert.py` (line 117)
- Current mitigation: Changes are staged for human approval before committing
- Recommendations:
  - Consider adding GPG signing to commits (requires secure key storage)
  - Document that skill evolution history should not be trusted as cryptographic proof
  - Add commit verification in audit logs

**No CORS/auth on MCP server:**
- Risk: FastMCP server on stdio has no authentication. If exposed to network transport, anyone with access can call tools.
- Files: `server/main.py` (lines 52-66)
- Current mitigation: Transport is stdio (local to Claude Code process). Not intended for network exposure.
- Recommendations:
  - Document: "skill-os MCP is for local transport only. Do not expose to network."
  - Add authentication layer if network transport is ever added

## Performance Bottlenecks

**Synchronous file I/O in approval loop:**
- Problem: `upsert.py` polls for approval decision every 5 seconds with `time.sleep()`. Block any concurrent operations.
- Files: `skills/skill_manager/tools/upsert.py` (lines 65-77)
- Cause: Blocking subprocess model; orchestrator cycle won't process while waiting for approval
- Improvement path:
  - Use async file watching (watchdog library already imported in registry.py)
  - Implement approval callback via MCP tool instead of polling

**Orchestrator runs eval synchronously:**
- Problem: `run_cycle.py` calls `subprocess.run()` for eval, blocking for up to 60 seconds. If eval is slow, orchestrator cycle delays.
- Files: `skills/orchestrator/tools/run_cycle.py` (lines 117-120)
- Cause: Not using asyncio; spawning subprocess instead of calling Python function directly
- Improvement path:
  - Import and call `eval_skill` logic directly instead of subprocess
  - Use `asyncio.create_subprocess_exec()` for parallelization

**Registry hot-reload fires on every file change:**
- Problem: `watchdog` observer calls `reload()` on ANY manifest.json, .md, or .py change. If many files change, registry locks and reloads multiple times.
- Files: `server/registry.py` (lines 22-27)
- Cause: File change events not debounced
- Improvement path:
  - Add debounce timer (200ms) to batch rapid changes
  - Only reload skills that actually changed

**LLM API calls not cached:**
- Problem: `eval.py` and `run_cycle.py` call Claude Haiku API for every eval/proposal. If same skill evaluated twice, API calls twice.
- Files: `skills/skill_manager/tools/eval.py` (lines 76-101), `skills/orchestrator/tools/run_cycle.py` (lines 145-176)
- Cause: No caching layer; API calls on every request
- Improvement path:
  - Cache eval results by skill_id + test_cases hash
  - Cache proposals for 1 hour with invalidation on manifest change

**Full skill reload on any registry change:**
- Problem: `registry.reload()` re-reads ALL manifests on ANY change. If only one manifest.json modified, all skills reload.
- Files: `server/registry.py` (lines 48-63)
- Cause: No selective loading
- Improvement path:
  - Detect which skill changed from file path
  - Reload only that skill

## Fragile Areas

**Approval decision via file existence:**
- Files: `skills/skill_manager/tools/upsert.py` (lines 65-77), `server/main.py` (lines 122-140)
- Why fragile: Approval flow depends on touching `.approved` or `.rejected` files. If file creation fails silently, approval stalls. Race condition if two processes check file simultaneously.
- Safe modification:
  - Use file locking (fcntl.flock on Unix) when reading approval status
  - Validate file contents before assuming approval
  - Add timeout cleanup (delete stale .json files after 24h)
- Test coverage: No unit tests for approval workflow

**Tool entrypoint parsing:**
- Files: `server/executor.py` (line 36), `skills/skill_manager/tools/eval.py` (line 41)
- Why fragile: Entrypoint split on `:` is hardcoded. If entrypoint format changes, no validation catches it.
  ```python
  script_rel, _fn = entrypoint.split(":")  # raises ValueError if wrong format
  ```
- Safe modification:
  - Add validation in `safety.validate_manifest()` to check entrypoint format
  - Provide helpful error message if format is wrong
- Test coverage: No tests for entrypoint parsing

**Orchestrator target selection logic:**
- Files: `skills/orchestrator/tools/run_cycle.py` (lines 77-98)
- Why fragile: If usage logs are empty, falls back to iterating skills in filesystem order (undefined). If all skills are excluded, returns None without clear handling.
- Safe modification:
  - Always return at least one skill (e.g., alphabetically first)
  - Add logging for target selection reasoning
  - Test with various log states (empty, all errors, no calls)
- Test coverage: No tests for target selection

**LLM JSON parsing in proposals:**
- Files: `skills/skill_manager/tools/eval.py` (line 96-97), `skills/orchestrator/tools/run_cycle.py` (line 173)
- Why fragile: Claude response is cleaned with regex `.replace("```json","")` but if response format changes, parsing fails silently with fallback critique
- Safe modification:
  - Use structured output (Claude API batching mode if available)
  - Validate JSON schema after parsing (required fields: rationale, new_system_prompt, etc.)
  - Add explicit error handling for malformed JSON
- Test coverage: No mock tests for LLM response handling

**Git operations without validation:**
- Files: `server/git_helper.py`, `skills/skill_manager/tools/upsert.py` (lines 115-120)
- Why fragile: Git commands (add, commit) can fail silently if `.git` directory is missing or corrupted. Errors are returned as strings but not always checked.
- Safe modification:
  - Add pre-flight check: `git status` before commit
  - Verify `.git` directory exists before any git operation
  - Wrap git operations in context manager for rollback
- Test coverage: No git operation tests

## Scaling Limits

**In-memory rate limiter not persistent:**
- Current capacity: Limits per process. If server restarts, rate limit resets.
- Limit: Multiple servers or frequent restarts bypass rate limiting.
- Files: `server/safety.py` (lines 76-99), but not actually used in production flow
- Scaling path:
  - Move rate limiting to persistent log file (like `evolution.log`)
  - Or move to database (Redis) for multi-server deployments

**Single-threaded MCP server:**
- Current capacity: FastMCP handles one request at a time (stdio transport)
- Limit: Orchestrator cycle blocks all other tool executions
- Scaling path:
  - Use async FastMCP if available
  - Spawn orchestrator as background task (already attempted with `asyncio.create_task()` in main.py but not fully async)

**Logs directory unbounded growth:**
- Current capacity: `usage.log` and `orchestrator.log` append forever with no rotation
- Limit: After 1 year, logs could be multi-GB; parsing them in `run_cycle.py` will slow
- Files: `server/main.py` (line 166), `skills/orchestrator/tools/run_cycle.py` (line 42), `skills/skill_manager/tools/upsert.py` (line 52)
- Scaling path:
  - Implement log rotation (e.g., `logging.handlers.RotatingFileHandler`)
  - Compress old logs
  - Add log cleanup in entrypoint

**Pending approvals directory unbounded growth:**
- Current capacity: Each upsert leaves `.json`, `.approved`, `.rejected` files forever
- Limit: After many iterations, cleanup becomes manual
- Files: Multiple locations write to `PENDING_DIR`
- Scaling path:
  - Add cleanup task: delete `.json` if both `.approved` and `.rejected` exist
  - Or move to database with TTL

**No database layer:**
- Current capacity: Everything is file-based (logs, pending approvals, skill manifests)
- Limit: Git history becomes primary audit log; queries are slow; concurrent access issues
- Scaling path:
  - Consider SQLite or PostgreSQL for audit log, approvals, rate limiting
  - Keep manifests in filesystem for git history, but mirror in DB for queries

## Dependencies at Risk

**fastmcp>=2.0.0:**
- Risk: Version pinning is loose (`>=2.0.0`). Breaking changes in fastmcp 3.0 could break server.
- Impact: Server startup fails; MCP transport breaks
- Migration plan:
  - Pin to major version: `fastmcp>=2.0,<3.0`
  - Add integration tests with multiple fastmcp versions
  - Set up dependency update alerts (Dependabot, Renovate)

**watchdog>=4.0.0:**
- Risk: Hot-reload depends on watchdog. If watchdog has file system bugs, registry can get stuck.
- Impact: New skills not detected; skill changes not reloaded
- Migration plan:
  - Add fallback: manual reload via MCP tool
  - Monitor watchdog issues; have plan to disable if problematic

**Python 3.11 EOL:**
- Risk: Python 3.11 reaches EOL in October 2026. Dockerfile hardcodes `python:3.11-slim`.
- Impact: Security patches stop; environment becomes unmaintained
- Migration plan:
  - Plan upgrade to 3.12 or 3.13 in Q3 2026
  - Add version abstraction: make Python version configurable in docker-compose

**git command-line dependency:**
- Risk: Dockerfile requires git binary. If git is removed from image or PATH is wrong, all git operations fail.
- Impact: Auto-evolution commits fail; rollback fails; history is lost
- Migration plan:
  - Use `GitPython` library instead of subprocess calls
  - Add git availability check in entrypoint
  - Gracefully degrade if git unavailable (log warning, disable evolution features)

## Missing Critical Features

**No approval timeout cleanup:**
- Problem: Approval requests that timeout are never deleted. `PENDING_DIR` can accumulate stale files.
- Blocks: Long-term operation requires manual cleanup
- Files: `skills/skill_manager/tools/upsert.py` (creates but never deletes timed-out approvals)
- Fix: Add cleanup task that deletes `.json` files older than 24h without `.approved` or `.rejected`

**No skill rollback from orchestrator:**
- Problem: If orchestrator proposes a bad skill improvement and it gets approved, there's no automatic rollback. Only manual git revert.
- Blocks: Self-healing automation is incomplete
- Fix: Add rollback heuristic to run_cycle: if new score < old score after 1h, propose automatic revert

**No skill testing before approval:**
- Problem: Orchestrator generates proposals based on test cases, but upsert doesn't re-run tests after applying changes. A proposal could regress.
- Blocks: Confidence in auto-evolution is low
- Fix: Before approval decision, run eval on proposed changes in a shadow skill

**No skill dependencies or inheritance:**
- Problem: Skills are independent. Can't compose skills or inherit system prompts.
- Blocks: Can't reduce duplication across similar skills
- Fix: Add `extends: <skill_id>` in manifest to inherit system prompt and tools

**No skill versioning in manifests:**
- Problem: Skill version is string (e.g., "1.0.0") but never validated as semantic. No way to express breaking changes.
- Blocks: Hard to understand evolution history
- Fix: Validate version format (semantic versioning) and add `breaking_changes: []` field to manifest

**No metrics collection:**
- Problem: No tracking of eval score over time, skill usage trends, or orchestrator effectiveness.
- Blocks: Can't measure if auto-evolution actually improves things
- Fix: Add metrics table to logs; graph score trends in JSON output

## Test Coverage Gaps

**Untested approval workflow:**
- What's not tested: `upsert.py` approval polling, file-based approval decision handling
- Files: `skills/skill_manager/tools/upsert.py` (lines 65-199)
- Risk: Race conditions in approval checking; stale approvals not cleaned up
- Priority: High (core workflow for auto-evolution)

**Untested sandbox execution:**
- What's not tested: Docker sandbox `_run_docker()`, local subprocess fallback `_run_local()`
- Files: `server/executor.py` (lines 57-96)
- Risk: Sandbox breaks silently; timeout handling doesn't work
- Priority: High (affects all user code execution)

**Untested orchestrator target selection:**
- What's not tested: Logic to pick which skill to improve (`_choose_target()`)
- Files: `skills/orchestrator/tools/run_cycle.py` (lines 77-98)
- Risk: Orchestrator always picks same skill or crashes on edge cases
- Priority: Medium (affects auto-evolution fairness)

**Untested registry hot-reload:**
- What's not tested: Watchdog observer detects changes; registry reloads correctly
- Files: `server/registry.py` (lines 18-71)
- Risk: New skills not detected; race conditions in reload
- Priority: Medium (affects developer experience)

**Untested LLM critique generation:**
- What's not tested: Claude API responses parsed correctly; fallback critique works
- Files: `skills/skill_manager/tools/eval.py` (lines 63-101), `skills/orchestrator/tools/run_cycle.py` (lines 135-176)
- Risk: JSON parsing fails; critique is garbage; no feedback to user
- Priority: Medium (affects proposal quality)

**Untested git operations:**
- What's not tested: `commit_skill_update()`, `rollback_skill()`, `get_skill_history()`
- Files: `server/git_helper.py` (lines 25-84)
- Risk: Git operations fail silently; commits never happen; history lost
- Priority: High (evolution requires git)

**Untested rate limiting:**
- What's not tested: `RateLimiter` enforces daily limits; `_check_rate_limit()` works correctly
- Files: `server/safety.py` (lines 76-99), `skills/skill_manager/tools/upsert.py` (lines 36-46)
- Risk: Rate limit bypassed; too many upserts per day
- Priority: Medium (prevents runaway auto-evolution)

---

*Concerns audit: 2026-03-20*
