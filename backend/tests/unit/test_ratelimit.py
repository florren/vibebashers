"""T050: streaming соблюдает существующие квоты и deadline; только synthetic providers."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.llm import failover
from app.llm.base import LLMProfile, ProviderError
from app.llm.failover import ProviderChain
from app.llm.ratelimit import RateLimiter

PROFILE = LLMProfile(code="stream-test", provider="gigachat", model="synthetic", rpm_limit=10, rpd_limit=20)
MESSAGES = [{"role": "user", "content": "synthetic"}]


class SyntheticProvider:
    def __init__(
        self, name="gigachat", chunks=("live",), *, before=None, after=None, block_before=False, block_after=False
    ):
        self.name, self.chunks, self.before, self.after = name, chunks, before, after
        self.block_before, self.block_after = block_before, block_after
        self.calls = []
        self.started = asyncio.Event()
        self.closed = False

    async def stream(self, messages, profile, *, timeout_s):
        self.calls.append((messages, profile, timeout_s))
        self.started.set()
        try:
            if self.before:
                raise self.before
            if self.block_before:
                await asyncio.Event().wait()
            for chunk in self.chunks:
                yield chunk
            if self.block_after:
                await asyncio.Event().wait()
            if self.after:
                raise self.after
        finally:
            self.closed = True


class RecordingLimiter(RateLimiter):
    def __init__(self, *, clock=None, advance=0, block=False):
        super().__init__()
        self.calls = []
        self.clock, self.advance, self.block = clock, advance, block
        self.cancelled = False

    async def acquire(self, code, rpm=None, rpd=None):
        self.calls.append((code, rpm, rpd))
        if self.clock is not None:
            self.clock.now += self.advance
        if self.block:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise


def chain(providers, limiter, timeout=1):
    return ProviderChain(providers, rate_limiter=limiter, timeouts={"default": timeout}, append_mock=False)


async def collect(value, profile=PROFILE):
    return "".join([chunk async for chunk in value.stream(MESSAGES, profile)])


async def test_stream_daily_quota_prevents_live_call_and_falls_back_to_mock():
    limiter = RateLimiter(max_wait_s=0)
    profile = replace(PROFILE, rpm_limit=None, rpd_limit=1)
    await limiter.acquire(profile.code, profile.rpm_limit, profile.rpd_limit)
    live, mock = SyntheticProvider(), SyntheticProvider("mock", ("mock",))
    assert await collect(chain([live, mock], limiter), profile) == "mock"
    assert live.calls == [] and len(mock.calls) == 1
    assert limiter.stats()[profile.code]["today"] == 1


async def test_stream_rpm_quota_prevents_live_call_without_waiting():
    limiter = RateLimiter(max_wait_s=0)
    profile = replace(PROFILE, rpm_limit=1, rpd_limit=None)
    await limiter.acquire(profile.code, profile.rpm_limit, profile.rpd_limit)
    live, mock = SyntheticProvider(), SyntheticProvider("mock", ("mock",))
    assert await collect(chain([live, mock], limiter), profile) == "mock"
    assert live.calls == []


async def test_every_live_candidate_gets_the_same_existing_profile_limits():
    limiter = RecordingLimiter()
    first = SyntheticProvider(before=ProviderError("rate_limit", "synthetic 429"))
    second, mock = SyntheticProvider("openai_compatible", ("second",)), SyntheticProvider("mock")
    assert await collect(chain([first, second, mock], limiter)) == "second"
    assert limiter.calls == [(PROFILE.code, 10, 20), (PROFILE.code, 10, 20)]
    assert first.closed and second.closed and mock.calls == []


@pytest.mark.parametrize("provider", ["mock", "replay"])
async def test_offline_profiles_never_acquire_or_invoke_live_provider(provider):
    limiter = RecordingLimiter()
    live, offline = SyntheticProvider(), SyntheticProvider(provider, ("offline",))
    assert await collect(chain([live, offline], limiter), replace(PROFILE, provider=provider)) == "offline"
    assert limiter.calls == [] and live.calls == []


@pytest.mark.parametrize("provider", ["mock", "replay"])
async def test_offline_fallback_has_no_quota_acquisition(provider):
    limiter = RecordingLimiter()
    assert await collect(chain([SyntheticProvider(provider, ("offline",))], limiter)) == "offline"
    assert limiter.calls == []


async def test_partial_stream_error_closes_source_without_new_fallback():
    limiter = RecordingLimiter()
    live = SyntheticProvider(chunks=("partial",), after=ProviderError("network", "synthetic failure"))
    mock = SyntheticProvider("mock")
    assert await collect(chain([live, mock], limiter)) == "partial"
    assert live.closed and mock.calls == [] and len(limiter.calls) == 1


async def test_timeout_before_first_chunk_closes_source_then_uses_mock():
    live, mock = SyntheticProvider(block_before=True), SyntheticProvider("mock", ("mock",))
    assert await collect(chain([live, mock], RecordingLimiter(), timeout=0.02)) == "mock"
    assert live.closed and len(mock.calls) == 1


async def test_timeout_after_first_chunk_closes_source_without_fallback():
    live = SyntheticProvider(chunks=("partial",), block_after=True)
    mock = SyntheticProvider("mock")
    assert await collect(chain([live, mock], RecordingLimiter(), timeout=0.02)) == "partial"
    assert live.closed and mock.calls == []


async def test_queue_wait_is_part_of_existing_generation_budget(monkeypatch):
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(failover, "time", SimpleNamespace(perf_counter=lambda: clock.now))
    live = SyntheticProvider()
    assert await collect(chain([live], RecordingLimiter(clock=clock, advance=4), timeout=5)) == "live"
    assert live.calls[0][2] == pytest.approx(1)


async def test_queue_exhausted_deadline_never_opens_live_stream(monkeypatch):
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(failover, "time", SimpleNamespace(perf_counter=lambda: clock.now))
    live, mock = SyntheticProvider(), SyntheticProvider("mock", ("mock",))
    assert await collect(chain([live, mock], RecordingLimiter(clock=clock, advance=6), timeout=5)) == "mock"
    assert live.calls == []


async def test_queue_wait_is_cancelled_at_deadline_then_mock_continues():
    limiter = RecordingLimiter(block=True)
    live, mock = SyntheticProvider(), SyntheticProvider("mock", ("mock",))
    assert await collect(chain([live, mock], limiter, timeout=0.02)) == "mock"
    assert limiter.cancelled and live.calls == []


async def test_external_cancellation_closes_stream_and_never_falls_back():
    live, mock = SyntheticProvider(block_before=True), SyntheticProvider("mock")
    stream = chain([live, mock], RecordingLimiter()).stream(MESSAGES, PROFILE)
    task = asyncio.create_task(anext(stream))
    await live.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await stream.aclose()
    assert live.closed and mock.calls == []


async def test_consumer_close_releases_underlying_stream_without_fallback():
    live, mock = SyntheticProvider(chunks=("partial", "unused")), SyntheticProvider("mock")
    stream = chain([live, mock], RecordingLimiter()).stream(MESSAGES, PROFILE)
    assert await anext(stream) == "partial"
    await stream.aclose()
    assert live.closed and mock.calls == []


async def test_deadline_does_not_cancel_consumer_while_generator_is_suspended():
    live, mock = SyntheticProvider(chunks=("partial", "unused")), SyntheticProvider("mock")
    stream = chain([live, mock], RecordingLimiter(), timeout=0.1).stream(MESSAGES, PROFILE)
    assert await anext(stream) == "partial"
    # asyncio.timeout вокруг yield отменил бы task именно здесь, вне генератора.
    await asyncio.sleep(0.15)
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
    assert live.closed and mock.calls == []
