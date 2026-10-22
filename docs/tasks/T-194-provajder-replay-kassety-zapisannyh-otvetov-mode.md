# T-194 — Провайдер replay: кассеты записанных ответов моделей, запись LLM_RECORD, воспроизведение потока

| Поле | Значение |
|---|---|
| Эпик | E17 Режим подстраховки демо [BRD] |
| Субагент | `SA-LLM` (LLM-слой) |
| Оценка | M (1–2 дня) |
| Волна | 2 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Честный офлайн-режим: ответы реальных моделей воспроизводятся из кассет с исходной скоростью токенов; промах → следующий провайдер (ТЗ 5.2, 5.4).

## Разделы ТЗ (docs/TZ.md)
§5.2, §5.4, §12.5

## Контракты
- `db/schema.sql: llm_cassettes`
- `api/openapi.yaml: cassettes*`
- `events/common.schema.json: llm_source`

## Зависимости
- Зависит от: [T-046](T-046-interfejs-llm-provajdera-i-strukturirovannyj-vyv.md), [T-047](T-047-gigachat-provajder-s-pulom-klyuchej-i-uchetom-to.md), [T-049](T-049-mock-provajder-pravila-shablony-determinizm.md)
- Блокирует: [T-195](T-195-menyu-demonstratora-skrytaya-knopka-statusy-prov.md), [T-196](T-196-avtomaticheskij-failover-po-tajmautu-i-oshibkam.md), [T-197](T-197-install-sh-i-compose-flagi-no-stt-stt-model-reco.md), [T-198](T-198-kassety-scenariev-8-9-i-avtotesty-na-nih-procedu.md)

## Что сделать
1. app/replay/: ключ sha256(provider, model, normalized_messages, schema) с нормализацией пробелов и динамических полей (время, id) через плейсхолдеры; запись при LLM_RECORD=1 всех вызовов (ответ, потоковые чанки с at_ms, tool calls, usage) в llm_cassettes и экспорт в data/cassettes/<scenario>.jsonl.
2. Провайдер replay в цепочке replay → gigachat → mock (настраивается): воспроизведение stream с исходными задержками (ускорение ×1/×2 в настройках); источник ответа source=replay в agent_steps и в tool_call.source.
3. Пометка stale при смене prompt_version; GET /api/cassettes, POST /api/cassettes/record; импорт кассет при сиде.
4. Автотесты сценариев используют кассеты (детерминизм без сети и токенов).

## Критерии приёмки
- [ ] Сценарий 8 на кассете воспроизводится без сети, шаги помечены replay, бейдж в UI виден.
- [ ] Промах кассеты делегирует следующему провайдеру и логируется.
- [ ] Кассеты не содержат секретов и ПДн (тест).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_replay_provider.py
./install.sh --offline && make scenario ID=qr_fee_public_review
```

## Отчёт субагента
Коммит B02. `app/replay/store.py` — `CassetteStore(data/cassettes/*.jsonl)`: ключ `sha256(provider, model, normalized_messages, schema)`, `get/record` (идемпотентно, формат совместим с таблицей `llm_cassettes`); `app/replay/provider.py` — `ReplayProvider`: попадание → ответ с исходной задержкой `usage.latency_ms` (делитель `speed`), поток — чанки `at_ms`; промах → `ProviderError('miss')` → следующий провайдер цепочки (логируется info). Запись включается `LLM_RECORD=true` (ProviderChain пишет успешные live-ответы). Тесты: запись → воспроизведение в новом процессе, промах → mock, нормализация пробелов в ключе, `test_cassettes_have_no_secrets` (Bearer/Basic/sk-or-/телефоны/16 цифр). Отклонения: кассета сценария 8 и бейдж replay в UI — после B03/B21 (нужны симулятор и промпты), запись кассет в БД `llm_cassettes` — при реализации бенчмарков.
