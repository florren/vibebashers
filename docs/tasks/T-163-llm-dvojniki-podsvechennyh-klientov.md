# T-163 — LLM-двойники «подсвеченных» клиентов

| Поле | Значение |
|---|---|
| Эпик | E14 Поведение клиентов и калькулятор «Факт» |
| Субагент | `SA-Behavior` (поведение клиентов) |
| Оценка | L (3–4 дня) |
| Волна | 3 |
| Слой | `L2` Симулятор и данные (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `review` |

## Цель
Живые тексты жалоб и реакций на лёгкой модели для сценариев, HITL, VIP и выборки; остальные — параметрически.

## Разделы ТЗ (docs/TZ.md)
§4.5, §12.5, §5.2

## Контракты
- `events/agent/client_twin_reaction.schema.json`
- `db/schema.sql: client_reactions, agent_runs (kind=client_twin)`

## Зависимости
- Зависит от: [T-161](T-161-parametricheskaya-model-sostoyanij-klienta.md), [T-046](T-046-interfejs-llm-provajdera-i-strukturirovannyj-vyv.md), [T-049](T-049-mock-provajder-pravila-shablony-determinizm.md), [T-065](T-065-trassirovka-zapuskov-i-striming-tokenov.md)
- Блокирует: [T-110](T-110-dialog-agent-dvojnik-i-sostoyanie-klienta.md), [T-167](T-167-statisticheskie-testy-modeli-povedeniya.md)

## Что сделать
1. prompts/v1/twin.md: роль клиента с психотипом/сегментом/продуктом, что он видел (уведомления, ответы), фактическое состояние проблемы с его точки зрения; запрет на знание внутренних данных; структурированный ответ по схеме.
2. Выбор подсвеченных: сценарии, HITL, vip/ultra_vip, случайная выборка ≤ settings.twins.daily_limit; профиль роли twin (GigaChat-3-Pro по умолчанию, mock в офлайне).
3. Реакция → client_reactions, при asks_again/escalates → новый сигнал (signal.repeat) с текстом двойника; satisfaction влияет на care_score; запуски kind=client_twin в трассировке с отдельным учётом токенов.

## Критерии приёмки
- [ ] В сценарии 1 двойник VIP отвечает текстом на уведомления; тексты валидны по схеме и правдоподобны (ревью 10).
- [ ] Расход токенов двойников ≤ 15 % от общего на демо.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_twins.py
```

## Отчёт субагента
Ветка `codex/llm-role-routing-tls`, 28.10.2026. Подключены общий выбор main/fast/twin и горячее применение мастера; main Ultra, fast Lightning, twin Pro. Новый TwinService реагирует на новые уведомления после завершения агента, сохраняет отдельные agent_runs/steps и client_reactions; ответы-уточнения проходят normalizer. Ограничены число вызовов, прогноз токенов, выходной ответ, размер/время ожидания очереди; повторный id не вызывает LLM снова. Только клиентский видимый контекст, без внутреннего дела инцидента.

TLS обязателен, встроены root/sub CA с gu-st.ru и опциональный GIGACHAT_CA_BUNDLE_FILE. Живые проверки трёх моделей с валидными схемами и без fallback прошли; безопасный отчёт — docs/llm-routing-live-2026-10-28.json. До PR выполнены targeted-тесты и покрытие нового кода 89%; полный make test и CI проверяются перед merge, итог фиксируется в PR. Контракты не менялись, cross-layer согласован пользователем.

Ограничения: оценочный токенный бюджет, одно наблюдение latency на модель. Требования ревью десяти реакций, статистического расхода ≤15% на полном демо, генерации начальных жалоб и полного параметрического автомата этой задачей не закрываются; карточка не помечена done.
