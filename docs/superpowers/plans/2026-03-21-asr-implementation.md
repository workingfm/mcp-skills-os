# ASR (Adaptive Skill Reinforcement) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Reinforcement Learning-based adaptive evolution to skill-os so that skills self-improve when they fail, with snapshot rollback safety.

**Architecture:** A new `server/evolution.py` module contains the ASR Engine (FitnessTracker, FailureAnalyzer, MutationStrategy, SnapshotManager). The `execute()` tool in `main.py` is extended to compute reward signals and trigger evolution on failure. A persistent `data/fitness_store.json` tracks all RL state across restarts.

**Tech Stack:** Python 3.11, FastMCP, asyncio, JSON file storage, MCP sampling for LLM-guided mutations

**Spec:** `docs/superpowers/specs/2026-03-21-asr-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `server/evolution.py` | CREATE | ASR Engine: FitnessTracker, FailureAnalyzer, MutationStrategy, SnapshotManager, ASREngine facade |
| `tests/test_fitness_tracker.py` | CREATE | Tests for reward recording, EMA calculation, status transitions |
| `tests/test_failure_analyzer.py` | CREATE | Tests for failure diagnosis taxonomy and confidence |
| `tests/test_snapshot_manager.py` | CREATE | Tests for save, rollback, cleanup |
| `tests/test_mutation_strategy.py` | CREATE | Tests for deterministic mutations |
| `tests/test_asr_engine.py` | CREATE | Integration tests for full evolve cycle |
| `tests/test_execute_asr.py` | CREATE | Tests for ASR integration in execute() |
| `server/main.py` | MODIFY | Import ASR, add reward+evolution to execute(), add skill_fitness() tool |
| `docker-compose.yml` | MODIFY | Add ASR env vars |
| `.env.example` | MODIFY | Document ASR env vars |

---

### Task 1: FitnessTracker — Data Model and Persistence

**Files:**
- Create: `server/evolution.py`
- Create: `tests/test_fitness_tracker.py`

The FitnessTracker records episodes, computes fitness via EMA, manages status transitions (evolving/stable/degraded), and persists to `data/fitness_store.json` with atomic writes and per-skill locking.

- [ ] **Step 1: Write tests for FitnessTracker core**

```python
# tests/test_fitness_tracker.py
import asyncio
import json
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def tracker(data_dir):
    from server.evolution import FitnessTracker
    return FitnessTracker(data_dir=data_dir, alpha=0.3, max_episodes=200)


def test_new_skill_starts_at_fitness_5(tracker):
    """A brand-new skill has fitness 5.0 (EMA=0 mapped to 0-10 scale)."""
    info = asyncio.run(tracker.get_fitness("new_skill"))
    assert info["fitness"] == 5.0
    assert info["generation"] == 0
    assert info["status"] == "evolving"


def test_record_positive_reward_increases_fitness(tracker):
    """Recording a +1.0 reward increases fitness above 5.0."""
    asyncio.run(tracker.record_episode("s1", "s1:run", 1.0, None, "abc"))
    info = asyncio.run(tracker.get_fitness("s1"))
    assert info["fitness"] > 5.0
    assert info["total_episodes"] == 1


def test_record_negative_reward_decreases_fitness(tracker):
    """Recording a -0.5 reward decreases fitness below 5.0."""
    asyncio.run(tracker.record_episode("s1", "s1:run", -0.5, None, "abc"))
    info = asyncio.run(tracker.get_fitness("s1"))
    assert info["fitness"] < 5.0


def test_consecutive_successes_become_stable(tracker):
    """After stability_threshold consecutive successes, status becomes 'stable'."""
    tracker.stability_threshold = 3  # lower for test
    for _ in range(3):
        asyncio.run(tracker.record_episode("s1", "s1:run", 1.0, None, f"h{_}"))
    info = asyncio.run(tracker.get_fitness("s1"))
    assert info["status"] == "stable"


def test_persistence_survives_reload(data_dir):
    """Fitness data persists to disk and survives a new FitnessTracker instance."""
    from server.evolution import FitnessTracker
    t1 = FitnessTracker(data_dir=data_dir)
    asyncio.run(t1.record_episode("s1", "s1:run", 1.0, None, "abc"))
    fitness_before = asyncio.run(t1.get_fitness("s1"))["fitness"]

    t2 = FitnessTracker(data_dir=data_dir)
    fitness_after = asyncio.run(t2.get_fitness("s1"))["fitness"]
    assert fitness_after == fitness_before


def test_episode_fifo_cap(tracker):
    """Episodes beyond max_episodes are trimmed (FIFO)."""
    tracker.max_episodes = 5
    for i in range(10):
        asyncio.run(tracker.record_episode("s1", "s1:run", 1.0, None, f"h{i}"))
    info = asyncio.run(tracker.get_fitness("s1"))
    assert len(info["episodes"]) == 5


def test_record_mutation(tracker):
    """Recording a mutation increments generation and updates fitness_curve."""
    asyncio.run(tracker.record_episode("s1", "s1:run", -0.5, "some error", "abc"))
    asyncio.run(tracker.record_mutation(
        "s1", "ep_001", "missing_dependency",
        ["manifest.json: added pandas"], "applied"
    ))
    info = asyncio.run(tracker.get_fitness("s1"))
    assert info["generation"] == 1
    assert info["total_mutations"] == 1
    assert len(info["fitness_curve"]) == 2  # gen 0 + gen 1


def test_record_rollback_increments_counter(tracker):
    """Recording a rollback increments total_rollbacks and consecutive_rollbacks."""
    asyncio.run(tracker.record_episode("s1", "s1:run", -0.5, "err", "abc"))
    asyncio.run(tracker.record_rollback("s1"))
    info = asyncio.run(tracker.get_fitness("s1"))
    assert info["total_rollbacks"] == 1


def test_three_consecutive_rollbacks_marks_degraded(tracker):
    """Three consecutive rollbacks set status to 'degraded'."""
    tracker.degraded_after_rollbacks = 3
    for _ in range(3):
        asyncio.run(tracker.record_rollback("s1"))
    info = asyncio.run(tracker.get_fitness("s1"))
    assert info["status"] == "degraded"


def test_input_dedup_detection(tracker):
    """Same input_hash on second failure is detected as duplicate."""
    asyncio.run(tracker.record_episode("s1", "s1:run", -0.5, "err", "same_hash"))
    assert asyncio.run(tracker.is_duplicate_failure("s1", "same_hash")) is True
    assert asyncio.run(tracker.is_duplicate_failure("s1", "different")) is False


def test_can_evolve_respects_daily_limit(tracker):
    """can_evolve returns False after max_mutations_per_day mutations."""
    tracker.max_mutations_per_day = 2
    asyncio.run(tracker.record_mutation("s1", "ep1", "d1", ["c1"], "applied"))
    asyncio.run(tracker.record_mutation("s1", "ep2", "d2", ["c2"], "applied"))
    assert asyncio.run(tracker.can_evolve("s1")) is False


def test_can_evolve_respects_cooldown(tracker):
    """can_evolve returns False if last mutation is within cooldown period."""
    tracker.cooldown_seconds = 9999  # very long cooldown
    asyncio.run(tracker.record_mutation("s1", "ep1", "d1", ["c1"], "applied"))
    assert asyncio.run(tracker.can_evolve("s1")) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/elettrofranky/python-projects/skill-os-docker && python -m pytest tests/test_fitness_tracker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.evolution'`

- [ ] **Step 3: Implement FitnessTracker**

Create `server/evolution.py` with the FitnessTracker class. This is the first class in the file — other components will be added in subsequent tasks.

```python
# server/evolution.py
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
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
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
                "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
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
            today = datetime.datetime.now(datetime.UTC).date().isoformat()
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
                    datetime.datetime.now(datetime.UTC) - last_ts
                ).total_seconds()
                if elapsed < self.cooldown_seconds:
                    return False

            return True

    async def get_all_fitness(self) -> dict:
        result = {}
        for skill_id in list(self._store.keys()):
            result[skill_id] = await self.get_fitness(skill_id)
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/elettrofranky/python-projects/skill-os-docker && python -m pytest tests/test_fitness_tracker.py -v`
Expected: All 14 tests PASS

- [ ] **Step 5: Commit**

```bash
git add server/evolution.py tests/test_fitness_tracker.py
git commit -m "feat(asr): add FitnessTracker with EMA, persistence, and status transitions"
```

---

### Task 2: FailureAnalyzer — Diagnosis Taxonomy

**Files:**
- Modify: `server/evolution.py`
- Create: `tests/test_failure_analyzer.py`

The FailureAnalyzer classifies execution failures into a taxonomy (CODE_ERROR, COVERAGE_GAP, ENVIRONMENT, PROMPT_MISMATCH) using heuristic pattern matching. LLM-assisted diagnosis is handled separately in Task 5.

- [ ] **Step 1: Write tests for heuristic diagnosis**

```python
# tests/test_failure_analyzer.py
import pytest
from server.evolution import FailureAnalyzer, Diagnosis


@pytest.fixture
def analyzer():
    return FailureAnalyzer()


def test_diagnose_module_not_found(analyzer):
    result = {"stderr": "ModuleNotFoundError: No module named 'pandas'", "exit_code": 1}
    d = analyzer.diagnose(result, "s1:run", "", "")
    assert d.category == "ENVIRONMENT"
    assert d.subcategory == "missing_dependency"
    assert "pandas" in d.detail
    assert d.confidence >= 0.9
    assert "manifest.json" in d.target_files


def test_diagnose_import_error(analyzer):
    result = {"stderr": "ImportError: cannot import name 'foo' from 'bar'", "exit_code": 1}
    d = analyzer.diagnose(result, "s1:run", "", "")
    assert d.category == "CODE_ERROR"
    assert d.subcategory == "import_error"


def test_diagnose_syntax_error(analyzer):
    result = {"stderr": "SyntaxError: invalid syntax (run.py, line 10)", "exit_code": 1}
    d = analyzer.diagnose(result, "s1:run", "", "")
    assert d.category == "CODE_ERROR"
    assert d.subcategory == "syntax_error"
    assert "tools/run.py" in d.target_files
    assert d.confidence >= 0.9


def test_diagnose_type_error(analyzer):
    result = {"stderr": "TypeError: unsupported operand type(s)", "exit_code": 1}
    d = analyzer.diagnose(result, "s1:run", "", "")
    assert d.category == "CODE_ERROR"
    assert d.subcategory == "type_error"


def test_diagnose_timeout(analyzer):
    result = {"stderr": "Timeout (30s superato)", "exit_code": -1}
    d = analyzer.diagnose(result, "s1:run", "", "")
    assert d.category == "ENVIRONMENT"
    assert d.subcategory == "timeout"
    assert "manifest.json" in d.target_files


def test_diagnose_memory(analyzer):
    result = {"stderr": "MemoryError", "exit_code": 1}
    d = analyzer.diagnose(result, "s1:run", "", "")
    assert d.category == "ENVIRONMENT"
    assert d.subcategory == "memory_limit"


def test_diagnose_name_error(analyzer):
    result = {"stderr": "NameError: name 'undefined_var' is not defined", "exit_code": 1}
    d = analyzer.diagnose(result, "s1:run", "", "")
    assert d.category == "CODE_ERROR"
    assert d.subcategory == "runtime_exception"


def test_diagnose_unknown_error_low_confidence(analyzer):
    result = {"stderr": "something completely unknown happened", "exit_code": 1}
    d = analyzer.diagnose(result, "s1:run", "", "")
    assert d.confidence < 0.6
    assert d.subcategory == "unknown"


def test_diagnose_key_error(analyzer):
    result = {"stderr": "KeyError: 'missing_key'", "exit_code": 1}
    d = analyzer.diagnose(result, "s1:run", "", "")
    assert d.category == "CODE_ERROR"
    assert d.subcategory == "runtime_exception"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_failure_analyzer.py -v`
Expected: FAIL — `ImportError: cannot import name 'FailureAnalyzer'`

- [ ] **Step 3: Implement FailureAnalyzer**

Append to `server/evolution.py`:

```python
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
        import re
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_failure_analyzer.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add server/evolution.py tests/test_failure_analyzer.py
git commit -m "feat(asr): add FailureAnalyzer with heuristic diagnosis taxonomy"
```

---

### Task 3: SnapshotManager — Save and Rollback

**Files:**
- Modify: `server/evolution.py`
- Create: `tests/test_snapshot_manager.py`

The SnapshotManager copies skill directories before mutation and restores them on rollback. Snapshots live under `data/snapshots/<skill_id>/gen_<N>/`.

- [ ] **Step 1: Write tests for SnapshotManager**

```python
# tests/test_snapshot_manager.py
import json
import pytest
from pathlib import Path
from server.evolution import SnapshotManager


@pytest.fixture
def dirs(tmp_path):
    skills_dir = tmp_path / "skills"
    data_dir = tmp_path / "data"
    skill_dir = skills_dir / "test_skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "manifest.json").write_text('{"id": "test_skill", "version": "1.0.0"}')
    (skill_dir / "system_prompt.md").write_text("# Test prompt")
    tools_dir = skill_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "run.py").write_text("def main(): print('v1')")
    return skills_dir, data_dir


@pytest.fixture
def manager(dirs):
    skills_dir, data_dir = dirs
    return SnapshotManager(skills_dir=skills_dir, data_dir=data_dir)


def test_save_creates_snapshot(manager, dirs):
    skills_dir, data_dir = dirs
    path = manager.save("test_skill", generation=1)
    assert Path(path).exists()
    assert (Path(path) / "manifest.json").exists()
    assert (Path(path) / "system_prompt.md").exists()
    assert (Path(path) / "tools" / "run.py").exists()


def test_rollback_restores_files(manager, dirs):
    skills_dir, data_dir = dirs
    # Save gen 1
    manager.save("test_skill", generation=1)

    # Modify the skill (simulate mutation)
    skill_dir = skills_dir / "test_skill"
    (skill_dir / "tools" / "run.py").write_text("def main(): print('v2 MUTATED')")

    # Verify mutation happened
    assert "MUTATED" in (skill_dir / "tools" / "run.py").read_text()

    # Rollback to gen 1
    manager.rollback("test_skill", generation=1)

    # Verify restore
    content = (skill_dir / "tools" / "run.py").read_text()
    assert "v1" in content
    assert "MUTATED" not in content


def test_rollback_nonexistent_generation_raises(manager):
    with pytest.raises(FileNotFoundError):
        manager.rollback("test_skill", generation=99)


def test_cleanup_keeps_last_n(manager, dirs):
    for gen in range(1, 8):
        manager.save("test_skill", generation=gen)

    manager.cleanup("test_skill", keep_last=3)

    snapshots_dir = dirs[1] / "snapshots" / "test_skill"
    remaining = sorted(snapshots_dir.iterdir())
    assert len(remaining) == 3
    # Should keep the latest 3
    assert remaining[-1].name == "gen_7"


def test_save_copies_all_files_deeply(manager, dirs):
    skills_dir, _ = dirs
    # Add a nested file
    nested = skills_dir / "test_skill" / "tools" / "utils"
    nested.mkdir(parents=True)
    (nested / "helper.py").write_text("# helper")

    path = manager.save("test_skill", generation=2)
    assert (Path(path) / "tools" / "utils" / "helper.py").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_snapshot_manager.py -v`
Expected: FAIL — `ImportError: cannot import name 'SnapshotManager'`

- [ ] **Step 3: Implement SnapshotManager**

Append to `server/evolution.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_snapshot_manager.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add server/evolution.py tests/test_snapshot_manager.py
git commit -m "feat(asr): add SnapshotManager with save, rollback, and cleanup"
```

---

### Task 4: MutationStrategy — Deterministic Mutations

**Files:**
- Modify: `server/evolution.py`
- Create: `tests/test_mutation_strategy.py`

The MutationStrategy applies deterministic mutations for known patterns (missing_dependency, timeout) and generates LLM-guided mutations for complex failures. This task implements only the deterministic path. LLM path is added in Task 5.

- [ ] **Step 1: Write tests for deterministic mutations**

```python
# tests/test_mutation_strategy.py
import json
import pytest
from pathlib import Path
from server.evolution import MutationStrategy, Diagnosis


@pytest.fixture
def skill_dir(tmp_path):
    d = tmp_path / "skills" / "test_skill"
    d.mkdir(parents=True)
    manifest = {
        "id": "test_skill",
        "version": "1.0.0",
        "tools": [{
            "id": "run",
            "entrypoint": "tools/run.py:main",
            "execution": {"timeout_seconds": 30, "sandbox": "docker"},
            "runtime": {"language": "python", "version": "3.11", "dependencies": []},
            "safety": {"side_effects": False, "idempotent": True},
        }]
    }
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (d / "system_prompt.md").write_text("# Test skill\nDoes things.")
    tools = d / "tools"
    tools.mkdir()
    (tools / "run.py").write_text("def main(): pass")
    return d


@pytest.fixture
def strategy():
    return MutationStrategy()


def test_missing_dependency_adds_to_manifest(strategy, skill_dir):
    diag = Diagnosis(
        category="ENVIRONMENT",
        subcategory="missing_dependency",
        target_files=["manifest.json"],
        detail="Aggiungere 'pandas' alle dependencies",
        confidence=0.95,
    )
    changes = strategy.mutate_deterministic(diag, skill_dir)
    assert changes is not None
    assert len(changes) == 1
    assert changes[0]["file"] == "manifest.json"

    # Verify pandas was added
    new_manifest = json.loads(changes[0]["content"])
    deps = new_manifest["tools"][0]["runtime"]["dependencies"]
    assert "pandas" in deps


def test_timeout_increases_value(strategy, skill_dir):
    diag = Diagnosis(
        category="ENVIRONMENT",
        subcategory="timeout",
        target_files=["manifest.json"],
        detail="Timeout (30s superato)",
        confidence=0.95,
    )
    changes = strategy.mutate_deterministic(diag, skill_dir)
    assert changes is not None
    new_manifest = json.loads(changes[0]["content"])
    new_timeout = new_manifest["tools"][0]["execution"]["timeout_seconds"]
    assert new_timeout == 45  # 30 * 1.5


def test_timeout_caps_at_120(strategy, skill_dir):
    # Set timeout to 100
    manifest = json.loads((skill_dir / "manifest.json").read_text())
    manifest["tools"][0]["execution"]["timeout_seconds"] = 100
    (skill_dir / "manifest.json").write_text(json.dumps(manifest))

    diag = Diagnosis(
        category="ENVIRONMENT", subcategory="timeout",
        target_files=["manifest.json"], detail="Timeout", confidence=0.95,
    )
    changes = strategy.mutate_deterministic(diag, skill_dir)
    new_manifest = json.loads(changes[0]["content"])
    assert new_manifest["tools"][0]["execution"]["timeout_seconds"] == 120


def test_non_deterministic_returns_none(strategy, skill_dir):
    diag = Diagnosis(
        category="CODE_ERROR", subcategory="runtime_exception",
        target_files=["tools/run.py"], detail="KeyError", confidence=0.8,
    )
    changes = strategy.mutate_deterministic(diag, skill_dir)
    assert changes is None


def test_apply_writes_files_to_disk(strategy, skill_dir):
    changes = [{"file": "manifest.json", "content": '{"updated": true}'}]
    strategy.apply(changes, skill_dir)
    assert json.loads((skill_dir / "manifest.json").read_text()) == {"updated": True}


def test_validate_valid_python(strategy):
    assert strategy.validate_file("def foo(): return 1", "run.py") is True


def test_validate_invalid_python(strategy):
    assert strategy.validate_file("def foo(:", "run.py") is False


def test_validate_valid_json(strategy):
    assert strategy.validate_file('{"a": 1}', "manifest.json") is True


def test_validate_invalid_json(strategy):
    assert strategy.validate_file('{bad json', "manifest.json") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mutation_strategy.py -v`
Expected: FAIL — `ImportError: cannot import name 'MutationStrategy'`

- [ ] **Step 3: Implement MutationStrategy**

Append to `server/evolution.py`:

```python
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
    ) -> list[dict]:
        import re
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_mutation_strategy.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add server/evolution.py tests/test_mutation_strategy.py
git commit -m "feat(asr): add MutationStrategy with deterministic and LLM mutation paths"
```

---

### Task 5: ASREngine Facade — Full Evolution Cycle

**Files:**
- Modify: `server/evolution.py`
- Create: `tests/test_asr_engine.py`

The ASREngine is the facade that orchestrates the full cycle: reward signal -> diagnosis -> snapshot -> mutation -> retry -> rollback. It ties together all four components.

- [ ] **Step 1: Write tests for the full evolution cycle**

```python
# tests/test_asr_engine.py
import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from server.evolution import ASREngine


@pytest.fixture
def setup(tmp_path):
    skills_dir = tmp_path / "skills"
    data_dir = tmp_path / "data"
    skill_dir = skills_dir / "test_skill"
    skill_dir.mkdir(parents=True)
    manifest = {
        "id": "test_skill", "version": "1.0.0",
        "system_prompt_uri": "skill://test_skill/system_prompt.md",
        "tools": [{
            "id": "run", "entrypoint": "tools/run.py:main",
            "execution": {"tier": "server", "sandbox": "docker", "timeout_seconds": 30},
            "safety": {"side_effects": False, "requires_human_approval": False, "idempotent": True},
            "runtime": {"language": "python", "version": "3.11", "dependencies": []},
        }]
    }
    (skill_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (skill_dir / "system_prompt.md").write_text("# Test")
    (skill_dir / "tools").mkdir()
    (skill_dir / "tools" / "run.py").write_text("def main(): pass")

    engine = ASREngine(
        skills_dir=skills_dir,
        data_dir=data_dir,
        registry=MagicMock(),
    )
    engine.fitness.cooldown_seconds = 0  # no cooldown in tests
    return engine, skills_dir, data_dir


def test_compute_reward_success(setup):
    engine, _, _ = setup
    assert engine.compute_reward({"status": "ok", "exit_code": 0}) == 1.0


def test_compute_reward_error(setup):
    engine, _, _ = setup
    assert engine.compute_reward({"status": "error", "exit_code": 1}) == -0.5


def test_compute_reward_timeout(setup):
    engine, _, _ = setup
    assert engine.compute_reward({"status": "error", "exit_code": -1}) == -1.0


def test_can_evolve_sandbox_docker(setup):
    engine, skills_dir, _ = setup
    tool = json.loads((skills_dir / "test_skill" / "manifest.json").read_text())["tools"][0]
    assert engine.can_evolve_sandbox(tool) is True


def test_cannot_evolve_sandbox_none(setup):
    engine, skills_dir, _ = setup
    manifest = json.loads((skills_dir / "test_skill" / "manifest.json").read_text())
    manifest["tools"][0]["execution"]["sandbox"] = "none"
    (skills_dir / "test_skill" / "manifest.json").write_text(json.dumps(manifest))
    tool = manifest["tools"][0]
    assert engine.can_evolve_sandbox(tool) is False


def test_evolve_deterministic_missing_dep(setup):
    """Full cycle: missing dependency triggers deterministic mutation."""
    engine, skills_dir, _ = setup
    result = {
        "status": "error", "exit_code": 1,
        "stdout": "", "stderr": "ModuleNotFoundError: No module named 'numpy'"
    }
    tool = json.loads((skills_dir / "test_skill" / "manifest.json").read_text())["tools"][0]
    tool["_skill_root"] = skills_dir / "test_skill"

    # Mock executor to succeed on retry
    mock_executor = AsyncMock()
    mock_executor.run.return_value = {
        "status": "ok", "exit_code": 0, "stdout": "ok", "stderr": ""
    }

    evo_result = asyncio.run(engine.evolve(
        skill_id="test_skill", tool_id="run", tool=tool,
        result=result, code="import numpy", input_data="",
        executor=mock_executor, ctx=None,
    ))

    assert evo_result["status"] == "ok"
    assert evo_result.get("asr_info", {}).get("evolved") is True

    # Verify numpy was added to manifest
    updated = json.loads((skills_dir / "test_skill" / "manifest.json").read_text())
    assert "numpy" in updated["tools"][0]["runtime"]["dependencies"]


def test_evolve_rollback_on_retry_failure(setup):
    """If retry fails too, rollback to snapshot."""
    engine, skills_dir, _ = setup
    result = {
        "status": "error", "exit_code": 1,
        "stdout": "", "stderr": "ModuleNotFoundError: No module named 'badlib'"
    }
    tool = json.loads((skills_dir / "test_skill" / "manifest.json").read_text())["tools"][0]
    tool["_skill_root"] = skills_dir / "test_skill"

    # Mock executor to ALSO fail on retry
    mock_executor = AsyncMock()
    mock_executor.run.return_value = {
        "status": "error", "exit_code": 1,
        "stdout": "", "stderr": "Still broken"
    }

    evo_result = asyncio.run(engine.evolve(
        skill_id="test_skill", tool_id="run", tool=tool,
        result=result, code="", input_data="",
        executor=mock_executor, ctx=None,
    ))

    # Should return original error, not the retry error
    assert evo_result["status"] == "error"
    assert evo_result.get("asr_info", {}).get("rolled_back") is True

    # Verify manifest is restored (no badlib)
    restored = json.loads((skills_dir / "test_skill" / "manifest.json").read_text())
    assert "badlib" not in restored["tools"][0]["runtime"]["dependencies"]


def test_evolve_skips_degraded_skill(setup):
    """Degraded skills don't attempt evolution."""
    engine, skills_dir, _ = setup
    # Mark as degraded
    for _ in range(3):
        asyncio.run(engine.fitness.record_rollback("test_skill"))

    result = {"status": "error", "exit_code": 1, "stdout": "", "stderr": "err"}
    tool = json.loads((skills_dir / "test_skill" / "manifest.json").read_text())["tools"][0]
    tool["_skill_root"] = skills_dir / "test_skill"

    evo_result = asyncio.run(engine.evolve(
        skill_id="test_skill", tool_id="run", tool=tool,
        result=result, code="", input_data="",
        executor=AsyncMock(), ctx=None,
    ))

    assert "degraded" in evo_result.get("asr_info", {}).get("skip_reason", "")


def test_evolve_skips_low_confidence(setup):
    """Diagnosis with confidence < 0.6 skips mutation."""
    engine, skills_dir, _ = setup
    result = {
        "status": "error", "exit_code": 1,
        "stdout": "", "stderr": "some completely unknown error xyz"
    }
    tool = json.loads((skills_dir / "test_skill" / "manifest.json").read_text())["tools"][0]
    tool["_skill_root"] = skills_dir / "test_skill"

    evo_result = asyncio.run(engine.evolve(
        skill_id="test_skill", tool_id="run", tool=tool,
        result=result, code="", input_data="",
        executor=AsyncMock(), ctx=None,
    ))

    assert evo_result.get("asr_info", {}).get("skip_reason") == "low_confidence"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_asr_engine.py -v`
Expected: FAIL — `ImportError: cannot import name 'ASREngine'`

- [ ] **Step 3: Implement ASREngine**

Append to `server/evolution.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_asr_engine.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Run all ASR tests together**

Run: `python -m pytest tests/test_fitness_tracker.py tests/test_failure_analyzer.py tests/test_snapshot_manager.py tests/test_mutation_strategy.py tests/test_asr_engine.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add server/evolution.py tests/test_asr_engine.py
git commit -m "feat(asr): add ASREngine facade with full evolution cycle"
```

---

### Task 6: Integrate ASR into main.py

**Files:**
- Modify: `server/main.py`
- Create: `tests/test_execute_asr.py`

Wire the ASREngine into `execute()` and add the `skill_fitness()` tool.

- [ ] **Step 1: Write integration test**

```python
# tests/test_execute_asr.py
"""
Integration tests verifying ASR is wired into execute() correctly.
These test the reward signal computation and ASR info in results,
not the full evolution cycle (covered in test_asr_engine.py).
"""
import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch


def test_compute_reward_in_execute_success():
    """Successful execution produces reward +1.0 in asr_info."""
    from server.evolution import ASREngine
    engine = ASREngine(
        skills_dir=Path("/tmp/s"), data_dir=Path("/tmp/d"),
        registry=MagicMock(),
    )
    assert engine.compute_reward({"status": "ok", "exit_code": 0}) == 1.0


def test_compute_reward_in_execute_error():
    """Failed execution produces reward -0.5 in asr_info."""
    from server.evolution import ASREngine
    engine = ASREngine(
        skills_dir=Path("/tmp/s"), data_dir=Path("/tmp/d"),
        registry=MagicMock(),
    )
    assert engine.compute_reward({"status": "error", "exit_code": 1}) == -0.5
```

- [ ] **Step 2: Run test to verify it passes** (these test already-implemented code)

Run: `python -m pytest tests/test_execute_asr.py -v`
Expected: PASS

- [ ] **Step 3: Modify main.py — add ASR imports and initialization**

At the top of `server/main.py`, after the existing imports, add:

```python
from evolution import ASREngine, ASR_ENABLED
```

After the `registry` and `executor` initialization (~line 53), add:

```python
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
```

- [ ] **Step 4: Modify execute() to integrate ASR**

In `server/main.py`, modify the `execute()` function. After `result = await executor.run(...)` (line 151) and before the LLM enrichment block (line 155), insert the ASR cycle:

```python
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
```

- [ ] **Step 5: Add skill_fitness() tool**

After the `list_pending_approvals()` tool in `server/main.py`, add:

```python
@mcp.tool()
def skill_fitness(skill_id: str = "") -> dict:
    """
    Ritorna lo stato RL (Adaptive Skill Reinforcement) di una o tutte le skill.
    Mostra: fitness score, generazione, curva di apprendimento, status.

    Args:
        skill_id: ID della skill (vuoto = tutte le skill)
    """
    import asyncio
    if skill_id:
        return asyncio.run(asr.fitness.get_fitness(skill_id))
    return asyncio.run(asr.fitness.get_all_fitness())
```

- [ ] **Step 6: Run all tests**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add server/main.py tests/test_execute_asr.py
git commit -m "feat(asr): integrate ASR engine into execute() and add skill_fitness tool"
```

---

### Task 7: Update Configuration Files

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

- [ ] **Step 1: Add ASR env vars to docker-compose.yml**

After the `APPROVAL_TIMEOUT_SECONDS` line in `docker-compose.yml`, add:

```yaml
      # ASR — Adaptive Skill Reinforcement
      ASR_ENABLED: ${ASR_ENABLED:-true}
      ASR_MAX_RETRIES: ${ASR_MAX_RETRIES:-1}
      ASR_MAX_MUTATIONS_PER_DAY: ${ASR_MAX_MUTATIONS_PER_DAY:-5}
      ASR_STABILITY_THRESHOLD: ${ASR_STABILITY_THRESHOLD:-10}
      ASR_DEGRADED_AFTER_ROLLBACKS: ${ASR_DEGRADED_AFTER_ROLLBACKS:-3}
      ASR_FITNESS_ALPHA: ${ASR_FITNESS_ALPHA:-0.3}
      ASR_MAX_EPISODES: ${ASR_MAX_EPISODES:-200}
      ASR_MAX_SNAPSHOTS: ${ASR_MAX_SNAPSHOTS:-20}
      ASR_COOLDOWN_SECONDS: ${ASR_COOLDOWN_SECONDS:-300}
```

- [ ] **Step 2: Update docker-compose image tag**

Change `image: skill-os:1.3` to `image: skill-os:2.0`

- [ ] **Step 3: Add ASR section to .env.example**

Append after the existing content:

```bash

# ASR — Adaptive Skill Reinforcement
ASR_ENABLED=true                  # Attiva/disattiva evoluzione adattiva
ASR_MAX_RETRIES=1                 # Max retry per episodio (1 mutazione + 1 retry)
ASR_MAX_MUTATIONS_PER_DAY=5       # Max mutazioni giornaliere per skill
ASR_STABILITY_THRESHOLD=10        # Successi consecutivi per status "stable"
ASR_DEGRADED_AFTER_ROLLBACKS=3    # Rollback consecutivi per status "degraded"
ASR_FITNESS_ALPHA=0.3             # Peso nuovo episodio nel calcolo fitness
ASR_MAX_EPISODES=200              # Max episodi nel fitness store
ASR_MAX_SNAPSHOTS=20              # Max snapshot per skill
ASR_COOLDOWN_SECONDS=300          # Cooldown tra mutazioni sulla stessa skill (5 min)
```

- [ ] **Step 4: Add data/ to .gitignore**

Append to `.gitignore`:

```
# ASR runtime data (fitness store and snapshots)
data/
```

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml .env.example .gitignore
git commit -m "feat(asr): add ASR configuration to docker-compose and env template"
```

---

### Task 8: Update MCP Server Instructions and Version

**Files:**
- Modify: `server/main.py` (instructions string and version references)

- [ ] **Step 1: Update MCP instructions in main.py**

Replace the `instructions` parameter in the `FastMCP()` constructor with:

```python
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
```

- [ ] **Step 2: Update version reference in startup log**

Change line 716 from:
```python
    logger.info("skill-os v1.3 — avvio (stdio, Claude Code transport)")
```
to:
```python
    logger.info("skill-os v2.0 — avvio con ASR (stdio, Claude Code transport)")
```

- [ ] **Step 3: Update module docstring**

Change line 2 from `skill-os v1.3` to `skill-os v2.0` and add ASR mention.

- [ ] **Step 4: Commit**

```bash
git add server/main.py
git commit -m "feat(asr): update MCP instructions, version to 2.0, add ASR documentation"
```

---

### Task 9: Final Integration Verification

**Files:** None new — verification only.

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Verify the MCP server starts**

Run: `cd /Users/elettrofranky/python-projects/skill-os-docker && python server/main.py 2>&1 | head -5`
Expected: Startup log shows "skill-os v2.0" with no import errors

- [ ] **Step 3: Verify data directory structure**

Run: `ls -la data/` (should exist after first run or be created by mkdir in main.py)

- [ ] **Step 4: Final commit with version bump**

```bash
git add -A
git commit -m "feat: skill-os v2.0 — ASR (Adaptive Skill Reinforcement)

Reinforcement Learning applied to MCP skill evolution. Skills
self-improve when they fail through adaptive mutations with
snapshot-based rollback safety. Zero API keys required.

New features:
- FitnessTracker with EMA scoring and persistence
- FailureAnalyzer with heuristic + LLM diagnosis
- MutationStrategy with deterministic and LLM-guided paths
- SnapshotManager with generation-based rollback
- skill_fitness() tool for observing evolution curves
- Full test coverage across all ASR components"
```
