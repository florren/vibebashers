"""HITL не стоит за всем World; отмена не теряет единственный слот генерации."""

import asyncio

import pytest

from app.demo.roles import respond
from app.llm.base import LLMProfile
from app.llm.failover import ProviderChain
from app.llm.gigachat import generation_context, generation_slot
from app.llm.mock import MockProvider
from app.llm.scheduling import GenerationQueue, human_decision_generation


async def test_human_decisions_have_bounded_priority_and_single_generation():
    queue = GenerationQueue()
    order = []
    active = 0

    async def generate(name, human=False):
        nonlocal active
        with human_decision_generation(human):
            async with queue.slot():
                active += 1
                assert active == 1
                order.append(name)
                await asyncio.sleep(0)
                active -= 1

    async with queue.slot():
        tasks = [asyncio.create_task(generate(f"world-{i}")) for i in range(4)]
        tasks += [asyncio.create_task(generate(f"hitl-{i}", True)) for i in range(5)]
        await asyncio.sleep(0)
    await asyncio.wait_for(asyncio.gather(*tasks), 1)
    assert order == ["hitl-0", "hitl-1", "world-0", "hitl-2", "hitl-3", "world-1", "hitl-4", "world-2", "world-3"]


@pytest.mark.parametrize("human", [False, True])
@pytest.mark.parametrize("granted", [False, True])
async def test_cancelled_waiter_releases_or_removes_its_slot(human, granted):
    queue = GenerationQueue()

    async def wait():
        with human_decision_generation(human):
            async with queue.slot():
                pytest.fail("Отменённая генерация не должна начаться")

    async with queue.slot():
        task = asyncio.create_task(wait())
        await asyncio.sleep(0)
        if not granted:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    if granted:
        # release уже выдал слот, но ожидающая coroutine ещё не получила управление.
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    async with asyncio.timeout(1), queue.slot():
        pass


async def test_pers_priority_context_keeps_nested_provider_slot_and_resets():
    order = []

    async def call(name, human=False):
        with human_decision_generation(human):
            async with generation_context("GIGACHAT_API_PERS"):
                async with generation_slot("GIGACHAT_API_PERS"):
                    order.append(name)

    async with generation_slot("GIGACHAT_API_PERS"):
        normal = asyncio.create_task(call("world"))
        human = asyncio.create_task(call("hitl", True))
        await asyncio.sleep(0)
    await asyncio.wait_for(asyncio.gather(normal, human), 1)
    assert order == ["hitl", "world"]


async def test_non_pers_scope_keeps_parallel_generations():
    async with generation_context("GIGACHAT_API_CORP"):
        async with asyncio.timeout(1):
            await asyncio.create_task(_corp_call())


async def test_operator_role_overtakes_world_through_the_real_provider_chain():
    order = []

    class Capture(MockProvider):
        name = "gigachat"

        def generation_context(self):
            return generation_context("GIGACHAT_API_PERS")

        async def complete_structured(self, messages, schema, profile, *, timeout_s):
            order.append(profile.code)
            return await super().complete_structured(messages, schema, profile, timeout_s=timeout_s)

    chain = ProviderChain([Capture()], append_mock=False)

    async def call(name, role):
        return await respond(chain, LLMProfile(name, "gigachat", "test"), {"role": role}, "Согласовано")

    async with generation_slot("GIGACHAT_API_PERS"):
        tasks = [asyncio.create_task(call(f"world-{i}", "branch_manager")) for i in range(4)]
        tasks.append(asyncio.create_task(call("operator", "bank_operator")))
        await asyncio.sleep(0)
    results = await asyncio.wait_for(asyncio.gather(*tasks), 1)
    assert order == ["operator", "world-0", "world-1", "world-2", "world-3"]
    assert all(obj["decision"] == "accept" for obj, _ in results)


async def _corp_call():
    async with generation_slot("GIGACHAT_API_CORP"):
        pass
