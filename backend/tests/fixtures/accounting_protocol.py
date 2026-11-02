"""Fake operational storage for protocol tests; never imported by production code."""

from contextlib import asynccontextmanager


class ProtocolTicket:
    async def observe(self, prompt, completion, *, total_tokens=None, final=False):
        pass


class ProtocolScope:
    @asynccontextmanager
    async def inference(self):
        yield ProtocolTicket()


class ProtocolAccounting:
    durable = False

    @asynccontextmanager
    async def key_scope(self, profile, facts, *, timeout_s, check_budget=True):
        yield ProtocolScope()
