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
    for i in range(3):
        asyncio.run(tracker.record_episode("s1", "s1:run", 1.0, None, f"h{i}"))
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
