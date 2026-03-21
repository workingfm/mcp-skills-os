from __future__ import annotations

"""
ASR — Adaptive Skill Reinforcement Engine.

Reinforcement Learning applicato all'evoluzione di skill MCP.
Le skill si evolvono automaticamente quando falliscono,
convergendo verso la perfezione attraverso pressione d'uso reale.
"""
import asyncio
import datetime
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("skill-os.asr")

# ------------------------------------------------------------------ #
#  Configuration (read from env at import time)                       #
# ------------------------------------------------------------------ #
ASR_ENABLED = os.getenv("ASR_ENABLED", "true").lower() == "true"
ASR_MAX_RETRIES = int(os.getenv("ASR_MAX_RETRIES", "1"))
ASR_MAX_MUTATIONS_PER_DAY = int(os.getenv("ASR_MAX_MUTATIONS_PER_DAY", "5"))
ASR_STABILITY_THRESHOLD = int(os.getenv("ASR_STABILITY_THRESHOLD", "10"))
ASR_DEGRADED_AFTER_ROLLBACKS = int(os.getenv("ASR_DEGRADED_AFTER_ROLLBACKS", "3"))
ASR_FITNESS_ALPHA = float(os.getenv("ASR_FITNESS_ALPHA", "0.3"))
ASR_MAX_EPISODES = int(os.getenv("ASR_MAX_EPISODES", "200"))
ASR_MAX_SNAPSHOTS = int(os.getenv("ASR_MAX_SNAPSHOTS", "20"))
ASR_COOLDOWN_SECONDS = int(os.getenv("ASR_COOLDOWN_SECONDS", "300"))


# ------------------------------------------------------------------ #
#  Diagnosis data class                                               #
# ------------------------------------------------------------------ #
@dataclass
class Diagnosis:
    category: str          # CODE_ERROR, COVERAGE_GAP, ENVIRONMENT, PROMPT_MISMATCH
    subcategory: str       # syntax_error, missing_dependency, etc.
    target_files: list[str] = field(default_factory=list)
    detail: str = ""
    confidence: float = 0.0


# ------------------------------------------------------------------ #
#  FitnessTracker                                                     #
# ------------------------------------------------------------------ #
class FitnessTracker:
    """Records episodes, computes fitness via EMA, manages status transitions.

    Fitness scale: 0-10 (mapped from EMA range [-1, +1]).
    A new skill starts at fitness 5.0 (EMA = 0).
    """

    def __init__(
        self,
        data_dir: Path | str = "data",
        alpha: float = ASR_FITNESS_ALPHA,
        max_episodes: int = ASR_MAX_EPISODES,
        stability_threshold: int = ASR_STABILITY_THRESHOLD,
        degraded_after_rollbacks: int = ASR_DEGRADED_AFTER_ROLLBACKS,
        max_mutations_per_day: int = ASR_MAX_MUTATIONS_PER_DAY,
        cooldown_seconds: int = ASR_COOLDOWN_SECONDS,
    ):
        self.data_dir = Path(data_dir)
        self.alpha = alpha
        self.max_episodes = max_episodes
        self.stability_threshold = stability_threshold
        self.degraded_after_rollbacks = degraded_after_rollbacks
        self.max_mutations_per_day = max_mutations_per_day
        self.cooldown_seconds = cooldown_seconds

        self._store_path = self.data_dir / "fitness_store.json"
        self._locks: dict[str, asyncio.Lock] = {}
        self._store: dict = self._load_store()

    def _load_store(self) -> dict:
        if self._store_path.exists():
            try:
                return json.loads(self._store_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, Exception):
                logger.warning("[asr] fitness_store.json corrotto, ricreo")
        return {}

    def _get_lock(self, skill_id: str) -> asyncio.Lock:
        if skill_id not in self._locks:
            self._locks[skill_id] = asyncio.Lock()
        return self._locks[skill_id]

    async def _save_store(self):
        """Atomic write: write to temp file + rename."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(self.data_dir), suffix=".tmp"
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(self._store, f, ensure_ascii=False, indent=2)
            os.rename(tmp_path, str(self._store_path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _default_skill_data(self) -> dict:
        return {
            "fitness": 5.0,
            "ema": 0.0,
            "generation": 0,
            "status": "evolving",
            "consecutive_successes": 0,
            "consecutive_rollbacks": 0,
            "total_episodes": 0,
            "total_mutations": 0,
            "total_rollbacks": 0,
            "episodes": [],
            "mutations": [],
            "snapshots": [],
            "fitness_curve": [5.0],
        }

    def _ensure_skill(self, skill_id: str) -> dict:
        if skill_id not in self._store:
            self._store[skill_id] = self._default_skill_data()
        return self._store[skill_id]

    async def get_fitness(self, skill_id: str) -> dict:
        async with self._get_lock(skill_id):
            data = self._ensure_skill(skill_id)
            return {
                "skill_id": skill_id,
                "fitness": round(data["fitness"], 2),
                "generation": data["generation"],
                "status": data["status"],
                "consecutive_successes": data["consecutive_successes"],
                "total_episodes": data["total_episodes"],
                "total_mutations": data["total_mutations"],
                "total_rollbacks": data["total_rollbacks"],
                "fitness_curve": data["fitness_curve"],
                "episodes": data["episodes"],
                "mutations": data["mutations"],
                "last_mutation": (
                    data["mutations"][-1]["changes"][0]
                    if data["mutations"] else None
                ),
                "message": self._status_message(data),
            }

    def _status_message(self, data: dict) -> str:
        s = data["status"]
        if s == "stable":
            return "Skill stabile - nessuna evoluzione necessaria"
        if s == "degraded":
            return (
                f"Skill degraded dopo {data['total_rollbacks']} rollback. "
                f"Serve intervento manuale."
            )
        return f"Skill in evoluzione (gen {data['generation']}, fitness {data['fitness']:.1f})"

    async def record_episode(
        self,
        skill_id: str,
        tool_ref: str,
        reward: float,
        error: str | None,
        input_hash: str,
    ) -> dict:
        async with self._get_lock(skill_id):
            data = self._ensure_skill(skill_id)
            episode_id = f"ep_{secrets.token_hex(4)}"
            episode = {
                "id": episode_id,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "tool_ref": tool_ref,
                "reward": reward,
                "generation": data["generation"],
                "input_hash": input_hash,
                "error": error,
            }
            data["episodes"].append(episode)
            data["total_episodes"] += 1

            # EMA update
            data["ema"] = self.alpha * reward + (1 - self.alpha) * data["ema"]
            data["fitness"] = (data["ema"] + 1.0) * 5.0

            # Consecutive successes tracking
            if reward >= 0:
                data["consecutive_successes"] += 1
                data["consecutive_rollbacks"] = 0
                if (
                    data["consecutive_successes"] >= self.stability_threshold
                    and data["status"] != "degraded"
                ):
                    data["status"] = "stable"
            else:
                data["consecutive_successes"] = 0
                if data["status"] == "stable":
                    data["status"] = "evolving"

            # FIFO trim
            if len(data["episodes"]) > self.max_episodes:
                data["episodes"] = data["episodes"][-self.max_episodes:]

            await self._save_store()
            return episode

    async def record_mutation(
        self,
        skill_id: str,
        trigger_episode: str,
        diagnosis: str,
        changes: list[str],
        status: str,
    ) -> dict:
        async with self._get_lock(skill_id):
            data = self._ensure_skill(skill_id)
            mutation_id = f"mut_{secrets.token_hex(4)}"
            fitness_before = data["fitness"]
            gen_before = data["generation"]
            data["generation"] += 1
            data["total_mutations"] += 1
            data["consecutive_rollbacks"] = 0

            mutation = {
                "id": mutation_id,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "trigger_episode": trigger_episode,
                "diagnosis": diagnosis,
                "changes": changes,
                "generation_before": gen_before,
                "generation_after": data["generation"],
                "fitness_before": round(fitness_before, 2),
                "fitness_after": round(data["fitness"], 2),
                "status": status,
            }
            data["mutations"].append(mutation)
            data["fitness_curve"].append(round(data["fitness"], 2))

            await self._save_store()
            return mutation

    async def record_rollback(self, skill_id: str):
        async with self._get_lock(skill_id):
            data = self._ensure_skill(skill_id)
            data["total_rollbacks"] += 1
            data["consecutive_rollbacks"] = data.get("consecutive_rollbacks", 0) + 1
            if data["consecutive_rollbacks"] >= self.degraded_after_rollbacks:
                data["status"] = "degraded"
                logger.warning(
                    f"[asr] skill '{skill_id}' marcata DEGRADED "
                    f"dopo {data['consecutive_rollbacks']} rollback consecutivi"
                )
            await self._save_store()

    async def is_duplicate_failure(self, skill_id: str, input_hash: str) -> bool:
        async with self._get_lock(skill_id):
            data = self._ensure_skill(skill_id)
            for ep in reversed(data["episodes"]):
                if ep["input_hash"] == input_hash and ep.get("error"):
                    return True
            return False

    async def can_evolve(self, skill_id: str) -> bool:
        async with self._get_lock(skill_id):
            data = self._ensure_skill(skill_id)
            if data["status"] == "degraded":
                return False

            # Daily mutation limit
            today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
            today_mutations = sum(
                1 for m in data["mutations"]
                if m["timestamp"].startswith(today)
            )
            if today_mutations >= self.max_mutations_per_day:
                return False

            # Cooldown check
            if data["mutations"]:
                last_ts = datetime.datetime.fromisoformat(
                    data["mutations"][-1]["timestamp"]
                )
                elapsed = (
                    datetime.datetime.now(datetime.timezone.utc) - last_ts
                ).total_seconds()
                if elapsed < self.cooldown_seconds:
                    return False

            return True

    async def get_all_fitness(self) -> dict:
        result = {}
        for skill_id in list(self._store.keys()):
            result[skill_id] = await self.get_fitness(skill_id)
        return result


# ------------------------------------------------------------------ #
#  FailureAnalyzer                                                    #
# ------------------------------------------------------------------ #
class FailureAnalyzer:
    """Classifies execution failures into a taxonomy using pattern matching.

    Two levels:
    - Heuristic: regex on stderr for known patterns (instant, zero LLM cost)
    - LLM-assisted: via MCP sampling for ambiguous errors (handled externally)

    Returns Diagnosis with confidence. If confidence < 0.6, no mutation is attempted.
    """

    # (pattern, category, subcategory, target_files, confidence)
    _PATTERNS: list[tuple[str, str, str, list[str], float]] = [
        (r"ModuleNotFoundError: No module named '(\w+)'",
         "ENVIRONMENT", "missing_dependency", ["manifest.json"], 0.95),
        (r"SyntaxError:",
         "CODE_ERROR", "syntax_error", ["tools/run.py"], 0.90),
        (r"TypeError:",
         "CODE_ERROR", "type_error", ["tools/run.py"], 0.85),
        (r"ImportError:",
         "CODE_ERROR", "import_error", ["tools/run.py"], 0.85),
        (r"Timeout \(",
         "ENVIRONMENT", "timeout", ["manifest.json"], 0.95),
        (r"MemoryError",
         "ENVIRONMENT", "memory_limit", ["manifest.json"], 0.90),
    ]

    # Catch-all runtime errors
    _RUNTIME_ERRORS = [
        "NameError:", "KeyError:", "ValueError:", "IndexError:",
        "AttributeError:", "ZeroDivisionError:", "FileNotFoundError:",
        "RuntimeError:", "AssertionError:", "OSError:",
    ]

    def diagnose(
        self,
        result: dict,
        tool_ref: str,
        code: str,
        input_data: str,
    ) -> Diagnosis:
        stderr = result.get("stderr", "")

        # Try specific patterns first
        for pattern, cat, subcat, targets, conf in self._PATTERNS:
            match = re.search(pattern, stderr)
            if match:
                detail = stderr
                # Extract module name for missing_dependency
                if subcat == "missing_dependency" and match.groups():
                    detail = f"Aggiungere '{match.group(1)}' alle dependencies"
                return Diagnosis(
                    category=cat,
                    subcategory=subcat,
                    target_files=list(targets),
                    detail=detail,
                    confidence=conf,
                )

        # Try generic runtime errors
        for err_type in self._RUNTIME_ERRORS:
            if err_type in stderr:
                return Diagnosis(
                    category="CODE_ERROR",
                    subcategory="runtime_exception",
                    target_files=["tools/run.py"],
                    detail=stderr,
                    confidence=0.75,
                )

        # Unknown error — low confidence, no mutation
        return Diagnosis(
            category="CODE_ERROR",
            subcategory="unknown",
            target_files=["tools/run.py"],
            detail=stderr,
            confidence=0.3,
        )


# ------------------------------------------------------------------ #
#  SnapshotManager                                                    #
# ------------------------------------------------------------------ #
class SnapshotManager:
    """Saves and restores skill directories for rollback safety.

    Snapshots are stored under data/snapshots/<skill_id>/gen_<N>/.
    """

    def __init__(
        self,
        skills_dir: Path | str,
        data_dir: Path | str,
        max_snapshots: int = ASR_MAX_SNAPSHOTS,
    ):
        self.skills_dir = Path(skills_dir)
        self.data_dir = Path(data_dir)
        self.max_snapshots = max_snapshots

    def _snapshot_dir(self, skill_id: str, generation: int) -> Path:
        return self.data_dir / "snapshots" / skill_id / f"gen_{generation}"

    def save(self, skill_id: str, generation: int) -> str:
        """Copy skills/<skill_id>/ to data/snapshots/<skill_id>/gen_<N>/.

        Returns the snapshot path.
        """
        src = self.skills_dir / skill_id
        if not src.exists():
            raise FileNotFoundError(f"Skill directory not found: {src}")

        dst = self._snapshot_dir(skill_id, generation)
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        logger.info(f"[asr] snapshot saved: {skill_id} gen_{generation}")
        return str(dst)

    def rollback(self, skill_id: str, generation: int) -> None:
        """Restore data/snapshots/<skill_id>/gen_<N>/ back to skills/<skill_id>/.

        Overwrites current skill files with the snapshot.
        """
        src = self._snapshot_dir(skill_id, generation)
        if not src.exists():
            raise FileNotFoundError(
                f"Snapshot not found: {skill_id} gen_{generation}"
            )

        dst = self.skills_dir / skill_id
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        logger.info(f"[asr] rollback: {skill_id} -> gen_{generation}")

    def cleanup(self, skill_id: str, keep_last: int | None = None) -> None:
        """Remove old snapshots, keeping the latest N."""
        keep = keep_last or self.max_snapshots
        snapshots_dir = self.data_dir / "snapshots" / skill_id
        if not snapshots_dir.exists():
            return

        gens = sorted(snapshots_dir.iterdir(), key=lambda p: p.name)
        to_remove = gens[:-keep] if len(gens) > keep else []
        for d in to_remove:
            shutil.rmtree(d)
            logger.debug(f"[asr] cleanup snapshot: {d.name}")


# ------------------------------------------------------------------ #
#  MutationStrategy                                                   #
# ------------------------------------------------------------------ #
class MutationStrategy:
    """Decides what to mutate based on diagnosis and generates the mutation.

    Two paths:
    - Deterministic: known patterns with predictable fixes (zero LLM cost)
    - LLM-guided: complex failures requiring reasoning (via MCP sampling)
    """

    def mutate_deterministic(
        self, diagnosis: Diagnosis, skill_dir: Path
    ) -> list[dict] | None:
        """Try a deterministic fix. Returns list of {file, content} or None if LLM needed."""

        if diagnosis.subcategory == "missing_dependency":
            return self._fix_missing_dependency(diagnosis, skill_dir)
        if diagnosis.subcategory == "timeout":
            return self._fix_timeout(skill_dir)
        return None

    def _fix_missing_dependency(
        self, diagnosis: Diagnosis, skill_dir: Path
    ) -> list[dict] | None:
        # Extract module name from detail
        match = re.search(r"'(\w+)'", diagnosis.detail)
        module = match.group(1) if match else ""
        if not module:
            return None

        manifest_path = skill_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for tool in manifest.get("tools", []):
            deps = tool.get("runtime", {}).get("dependencies", [])
            if module not in deps:
                deps.append(module)
                tool.setdefault("runtime", {})["dependencies"] = deps

        return [{"file": "manifest.json",
                 "content": json.dumps(manifest, indent=2, ensure_ascii=False)}]

    def _fix_timeout(self, skill_dir: Path) -> list[dict]:
        manifest_path = skill_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for tool in manifest.get("tools", []):
            current = tool.get("execution", {}).get("timeout_seconds", 30)
            new_timeout = min(int(current * 1.5), 120)
            tool.setdefault("execution", {})["timeout_seconds"] = new_timeout

        return [{"file": "manifest.json",
                 "content": json.dumps(manifest, indent=2, ensure_ascii=False)}]

    async def mutate_llm(
        self,
        diagnosis: Diagnosis,
        skill_dir: Path,
        result: dict,
        code: str,
        previous_mutations: list[dict],
        ctx,
    ) -> list[dict] | None:
        """Generate a fix via LLM (MCP sampling). Returns list of {file, content} or None."""
        if ctx is None:
            return None

        # Read the target file(s)
        target_file = diagnosis.target_files[0] if diagnosis.target_files else "tools/run.py"
        target_path = skill_dir / target_file
        current_content = ""
        if target_path.exists():
            current_content = target_path.read_text(encoding="utf-8")

        # Read system prompt for context
        prompt_path = skill_dir / "system_prompt.md"
        system_prompt = ""
        if prompt_path.exists():
            system_prompt = prompt_path.read_text(encoding="utf-8")

        # Build mutation summary of previous attempts
        prev_summary = "Nessuna mutazione precedente."
        if previous_mutations:
            prev_lines = []
            for m in previous_mutations[-5:]:  # last 5
                prev_lines.append(
                    f"- [{m['diagnosis']}] {', '.join(m['changes'])} -> {m['status']}"
                )
            prev_summary = "\n".join(prev_lines)

        mutation_prompt = (
            f"Sei un esperto di evoluzione adattiva di skill MCP.\n\n"
            f"SKILL: {skill_dir.name}\n"
            f"DIAGNOSI: {diagnosis.category} / {diagnosis.subcategory}\n"
            f"CONFIDENCE: {diagnosis.confidence}\n\n"
            f"ERRORE ORIGINALE:\n{result.get('stderr', '')}\n\n"
            f"INPUT CHE HA CAUSATO IL FALLIMENTO:\n{code[:2000]}\n\n"
            f"SYSTEM PROMPT DELLA SKILL:\n{system_prompt[:1000]}\n\n"
            f"FILE CORRENTE DA MUTARE ({target_file}):\n{current_content}\n\n"
            f"STORIA MUTAZIONI PRECEDENTI (evita di ripetere fix fallite):\n"
            f"{prev_summary}\n\n"
            f"Genera la versione corretta del file. La mutazione deve:\n"
            f"1. Risolvere QUESTO specifico fallimento\n"
            f"2. NON rompere i casi che gia' funzionano\n"
            f"3. Essere minimale — cambia solo cio' che serve\n\n"
            f'Rispondi SOLO con JSON valido:\n'
            f'{{"file": "{target_file}", "content": "<contenuto_completo_del_file>", '
            f'"rationale": "<cosa hai cambiato e perche>"}}'
        )

        try:
            response = await ctx.sample(mutation_prompt)
            text = response.text if hasattr(response, "text") else str(response)
            text = text.strip().replace("```json", "").replace("```", "").strip()
            parsed = json.loads(text)

            file_name = parsed.get("file", target_file)
            content = parsed.get("content", "")
            if not content:
                return None

            if not self.validate_file(content, file_name):
                logger.warning(f"[asr] LLM mutation produced invalid file: {file_name}")
                return None

            return [{"file": file_name, "content": content,
                     "rationale": parsed.get("rationale", "")}]
        except Exception as e:
            logger.warning(f"[asr] LLM mutation failed: {e}")
            return None

    def apply(self, changes: list[dict], skill_dir: Path) -> list[str]:
        """Write mutation changes to disk. Returns list of written file paths."""
        written = []
        for change in changes:
            target = skill_dir / change["file"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(change["content"], encoding="utf-8")
            written.append(change["file"])
        return written

    def validate_file(self, content: str, filename: str) -> bool:
        """Validate that generated content is syntactically correct."""
        if filename.endswith(".json"):
            try:
                json.loads(content)
                return True
            except json.JSONDecodeError:
                return False
        if filename.endswith(".py"):
            try:
                compile(content, filename, "exec")
                return True
            except SyntaxError:
                return False
        return True  # .md and other files pass validation


# ------------------------------------------------------------------ #
#  ASREngine — Facade                                                 #
# ------------------------------------------------------------------ #
class ASREngine:
    """Orchestrates the full ASR cycle: reward -> diagnose -> snapshot -> mutate -> retry -> rollback.

    This is the single entry point used by main.py.
    """

    def __init__(
        self,
        skills_dir: Path | str,
        data_dir: Path | str,
        registry,
    ):
        self.skills_dir = Path(skills_dir)
        self.data_dir = Path(data_dir)
        self.registry = registry

        self.fitness = FitnessTracker(data_dir=self.data_dir)
        self.analyzer = FailureAnalyzer()
        self.mutator = MutationStrategy()
        self.snapshots = SnapshotManager(
            skills_dir=self.skills_dir, data_dir=self.data_dir
        )

    def compute_reward(self, result: dict) -> float:
        """Map execution result to reward signal."""
        if result.get("exit_code") == 0:
            return 1.0
        if result.get("exit_code") == -1:  # timeout/crash
            return -1.0
        return -0.5

    def can_evolve_sandbox(self, tool: dict) -> bool:
        """Only sandbox=docker skills can be auto-mutated."""
        sandbox = tool.get("execution", {}).get("sandbox", "none")
        return sandbox == "docker"

    def input_hash(self, code: str, input_data: str = "") -> str:
        return hashlib.sha256(f"{code}|{input_data}".encode()).hexdigest()[:12]

    async def evolve(
        self,
        skill_id: str,
        tool_id: str,
        tool: dict,
        result: dict,
        code: str,
        input_data: str,
        executor,
        ctx=None,
    ) -> dict:
        """Full evolution cycle. Returns the final result dict with asr_info."""
        asr_info = {"evolved": False, "rolled_back": False}
        skill_dir = self.skills_dir / skill_id

        # Gate: sandbox check
        if not self.can_evolve_sandbox(tool):
            asr_info["sandbox_blocked"] = True
            asr_info["skip_reason"] = "sandbox_not_docker"
            result["asr_info"] = asr_info
            return result

        # Gate: degraded check
        if not await self.fitness.can_evolve(skill_id):
            status = (await self.fitness.get_fitness(skill_id))["status"]
            asr_info["skip_reason"] = "degraded" if status == "degraded" else "rate_limited"
            result["asr_info"] = asr_info
            return result

        # Gate: input deduplication
        ih = self.input_hash(code, input_data)
        if await self.fitness.is_duplicate_failure(skill_id, ih):
            asr_info["skip_reason"] = "duplicate_input"
            result["asr_info"] = asr_info
            return result

        # Phase 1: Diagnose
        diagnosis = self.analyzer.diagnose(result, f"{skill_id}:{tool_id}", code, input_data)
        asr_info["diagnosis"] = f"{diagnosis.category}/{diagnosis.subcategory}"
        asr_info["confidence"] = diagnosis.confidence

        if diagnosis.confidence < 0.6:
            asr_info["skip_reason"] = "low_confidence"
            result["asr_info"] = asr_info
            return result

        logger.info(
            f"[asr] evolving '{skill_id}': {diagnosis.category}/{diagnosis.subcategory} "
            f"(confidence={diagnosis.confidence})"
        )

        # Phase 2: Snapshot
        gen = (await self.fitness.get_fitness(skill_id))["generation"]
        self.snapshots.save(skill_id, gen)

        # Phase 3: Mutate
        # Try deterministic first, then LLM
        changes = self.mutator.mutate_deterministic(diagnosis, skill_dir)
        mutation_type = "deterministic"

        if changes is None and ctx is not None:
            fitness_data = await self.fitness.get_fitness(skill_id)
            changes = await self.mutator.mutate_llm(
                diagnosis, skill_dir, result, code,
                fitness_data.get("mutations", []), ctx,
            )
            mutation_type = "llm"

        if changes is None:
            asr_info["skip_reason"] = "no_mutation_available"
            result["asr_info"] = asr_info
            return result

        # Validate before applying
        for change in changes:
            if not self.mutator.validate_file(change["content"], change["file"]):
                asr_info["skip_reason"] = "invalid_mutation"
                result["asr_info"] = asr_info
                return result

        # Apply mutation
        self.mutator.apply(changes, skill_dir)
        self.registry.reload()

        # Phase 4: Retry
        updated_tool = self.registry.get_tool(skill_id, tool_id)
        retry_result = await executor.run(
            skill_id, tool_id, updated_tool, code, input_data
        )
        retry_reward = self.compute_reward(retry_result)

        if retry_reward > self.compute_reward(result):
            # Mutation worked!
            change_descs = [
                f"{c['file']}: {c.get('rationale', 'updated')}" for c in changes
            ]
            episode_id = (await self.fitness.get_fitness(skill_id))["episodes"][-1]["id"] \
                if (await self.fitness.get_fitness(skill_id))["episodes"] else "ep_init"
            await self.fitness.record_mutation(
                skill_id, episode_id, diagnosis.subcategory,
                change_descs, "applied",
            )
            self.snapshots.cleanup(skill_id)

            asr_info["evolved"] = True
            asr_info["mutation_type"] = mutation_type
            asr_info["changes"] = change_descs
            asr_info["generation"] = (await self.fitness.get_fitness(skill_id))["generation"]
            retry_result["asr_info"] = asr_info
            return retry_result
        else:
            # Rollback
            self.snapshots.rollback(skill_id, gen)
            self.registry.reload()
            await self.fitness.record_rollback(skill_id)

            asr_info["rolled_back"] = True
            asr_info["rollback_generation"] = gen
            result["asr_info"] = asr_info
            return result
