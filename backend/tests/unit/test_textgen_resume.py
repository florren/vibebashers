"""T-031: восстановление RNG сохраняет тексты и будущие случайные события мира."""

from __future__ import annotations

from unittest.mock import Mock

from app.sim.generators import World
from app.sim.rng import SimRng
from app.sim.textgen import TextGen


def world(rng: SimRng) -> World:
    return World(Mock(), Mock(), rng, 1)


def sample(value: World, count: int) -> list[tuple[object, float, int]]:
    result = []
    combos = value.textgen.all_combinations()
    for i in range(count):
        kind, product = combos[i % len(combos)]
        generated = value.textgen.generate(kind, product, psychotype="public_emotional")
        result.append((generated, value.rng.random(), value.rng.poisson(4)))
    return result


def test_world_construction_does_not_consume_or_fork_persisted_rng() -> None:
    rng = SimRng(412)
    before = rng.dump_state()
    current = world(rng)
    assert current.textgen.rnd is rng
    assert rng.dump_state() == before


def test_world_reconstruction_continues_exact_text_and_random_draws() -> None:
    rng = SimRng(1729)
    original = world(rng)
    sample(original, 25)
    checkpoint = rng.dump_state()
    expected = sample(original, 40)
    expected_end = rng.dump_state()
    restored_rng = SimRng(0)
    restored_rng.load_state(checkpoint)
    restored = world(restored_rng)
    assert sample(restored, 40) == expected
    assert restored_rng.dump_state() == expected_end


def test_integer_seed_api_stays_deterministic_and_independent() -> None:
    left, right = TextGen(19), TextGen(19)
    assert left.rnd is not right.rnd
    for kind, product in left.all_combinations():
        assert left.generate(kind, product) == right.generate(kind, product)
