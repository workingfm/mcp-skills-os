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

    assert evo_result["status"] == "error"
    assert evo_result.get("asr_info", {}).get("rolled_back") is True

    # Verify manifest is restored (no badlib)
    restored = json.loads((skills_dir / "test_skill" / "manifest.json").read_text())
    assert "badlib" not in restored["tools"][0]["runtime"]["dependencies"]


def test_evolve_skips_degraded_skill(setup):
    """Degraded skills don't attempt evolution."""
    engine, skills_dir, _ = setup
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
