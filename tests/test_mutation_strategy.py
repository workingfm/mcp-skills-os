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
