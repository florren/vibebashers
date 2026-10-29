"""Сравнение fast и fast→main на детерминированной выборке, без запуска агента и записи кассет.

В одноразовом Compose-контейнере: python /reports/harness.py, результат /reports/results.json.
Смонтируйте backend/app исследуемой ветки в /app/app:ro; зависимости берутся из образа стенда.
"""

import asyncio
import json
import time
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from app.agent.nodes import regex_hints
from app.agent.prompts import load
from app.config import get_settings
from app.contracts.registry import deref, validate
from app.db.session import psycopg_dsn
from app.llm.base import ProviderError
from app.llm.failover import ProviderChain, build_chain
from app.llm.roles import select


def cases():
    chosen = [{"id": "SIG-080097-text", "channel": "chat", "text": "Не могу оплатить покупку дебетовой картой: терминал отклоняет платёж, хотя деньги на счёте есть. Помогите разобраться.", "gold": {}}]
    seen = {}
    for line in Path('/data/bench/sentiment_v1.jsonl').read_text().splitlines():
        item = json.loads(line)
        label = item['gold']['sentiment']
        if seen.get(label, 0) < 2:
            chosen.append(item)
            seen[label] = seen.get(label, 0) + 1
    selected = set()
    for line in Path('/data/bench/hidden_negativity_v1.jsonl').read_text().splitlines():
        item = json.loads(line)
        label = tuple(item['gold'].get('markers') or ['none'])
        if label not in selected and len(selected) < 5:
            chosen.append(item)
            selected.add(label)
    return chosen


async def main():
    settings = get_settings()
    settings.llm_record = False
    chain = build_chain(settings)
    async with await psycopg.AsyncConnection.connect(psycopg_dsn(), row_factory=dict_row) as conn:
        await conn.execute('SET TRANSACTION READ ONLY')
        rows = list(await (await conn.execute('SELECT * FROM llm_profiles ORDER BY id')).fetchall())
        setup = await (await conn.execute("SELECT value FROM settings WHERE key='setup_payload'")).fetchone()
    roles = select(settings, rows, (setup['value'].get('llm') or {}))
    provider = next(p for p in chain.providers if p.name == roles['fast'].provider)
    baseline = ProviderChain([provider], append_mock=False)
    # Один провайдер, fallback из его настроенной роли main; нет подмены на внешнюю модель.
    candidate = ProviderChain([provider])
    output = {'profiles': {role: {'code': p.code, 'provider': p.provider, 'model': p.model} for role, p in roles.items()}, 'results': []}
    dataset = cases()
    try:
        for mode, runner in [('fast', baseline), ('fast_main', candidate)]:
            for item in dataset:
                text = item['text']
                prompt = load('system').body + '\n\n' + load('normalize').render(
                    hints=json.dumps(regex_hints(text), ensure_ascii=False), channel=item['channel'], text=text
                )
                start = time.perf_counter()
                row = {'mode': mode, 'case': item['id'], 'gold': item['gold']}
                try:
                    options = {'fallback_profile': roles['main']} if mode == 'fast_main' else {}
                    result = await runner.complete_structured(
                        [{'role': 'system', 'content': prompt}, {'role': 'user', 'content': text}],
                        deref('agent/normalization'), roles['fast'], context='fast_path', **options,
                    )
                    row.update(provider=result.provider, model=result.usage.model, output=result.obj,
                               valid=not validate(result.obj, 'agent/normalization'), usage=result.usage.as_dict(),
                               attempts=[{'provider': a.provider, 'model': a.model, 'ok': a.ok, 'error': a.error} for a in result.attempts])
                except ProviderError as error:
                    row.update(provider=None, valid=False, error_kind=error.kind)
                    if error.usage:
                        row['usage'] = error.usage.as_dict()
                row['latency_ms'] = round((time.perf_counter() - start) * 1000)
                output['results'].append(row)
                Path('/reports/results.json').write_text(json.dumps(output, ensure_ascii=False, indent=2))
                print(json.dumps({k: row.get(k) for k in ('mode', 'case', 'provider', 'model', 'valid', 'error_kind', 'latency_ms')}, ensure_ascii=False), flush=True)
    finally:
        for p in chain.providers:
            close = getattr(p, 'aclose', None)
            if close:
                await close()


asyncio.run(main())
