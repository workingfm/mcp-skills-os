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
    manager.save("test_skill", generation=1)
    skill_dir = skills_dir / "test_skill"
    (skill_dir / "tools" / "run.py").write_text("def main(): print('v2 MUTATED')")
    assert "MUTATED" in (skill_dir / "tools" / "run.py").read_text()
    manager.rollback("test_skill", generation=1)
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
    assert remaining[-1].name == "gen_7"


def test_save_copies_all_files_deeply(manager, dirs):
    skills_dir, _ = dirs
    nested = skills_dir / "test_skill" / "tools" / "utils"
    nested.mkdir(parents=True)
    (nested / "helper.py").write_text("# helper")
    path = manager.save("test_skill", generation=2)
    assert (Path(path) / "tools" / "utils" / "helper.py").exists()
