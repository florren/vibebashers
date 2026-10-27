# T-106 — Живая трассировка агента

| Поле | Значение |
|---|---|
| Эпик | E8 «Под капотом» |
| Субагент | `SA-UI-Engine` («Под капотом») |
| Оценка | L (3–4 дня) |
| Волна | 4 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Экран 4а: список запусков, дерево шагов, промпт/ответ/рассуждения, инструменты, стрим токенов.

## Разделы ТЗ (docs/TZ.md)
§12.2 экран 4, §12.5 приём 1

## Контракты
- `api/openapi.yaml: agent/runs*`
- `events/ws/message.schema.json (agent, agent_tokens)`

## Зависимости
- Зависит от: [T-065](T-065-trassirovka-zapuskov-i-striming-tokenov.md), [T-007](T-007-karkas-frontend-vite-ts-strict-tailwind-tokeny-t.md), [T-008](T-008-realtime-listen-notify-websocket-hab.md)
- Блокирует: [T-107](T-107-graf-langgraph-s-podsvetkoj-uzla-i-graf-suschnos.md), [T-109](T-109-panel-ii-protiv-pravil.md), [T-110](T-110-dialog-agent-dvojnik-i-sostoyanie-klienta.md), [T-143](T-143-playwright-smouk-i-vizualnaya-regressiya.md), [T-156](T-156-polnye-slovari-ru-en-i-proverka-i18n.md), [T-201](T-201-panel-log-debug-kak-obschij-komponent-demo-ekran.md), [T-214](T-214-tiketnica-v-tickets-get-api-tickets-vkladka-tike.md), [T-226](T-226-ekran-put-obrascheniya-journey-ref-stepper-iz-8.md)

## Что сделать
1. Список запусков с фильтрами и бейджами (профиль, outcome, токены, латентность); дерево шагов с таймингами; панели «Промпт», «Ответ модели», «Рассуждения» (стрим), «Инструменты» (аргументы/результат/мс), «Политики»; JetBrains Mono; копирование.
2. Автоследование за новым запуском (переключаемое), пауза прокрутки при наведении.
3. Ссылки на сигнал/инцидент/клиента.

## Критерии приёмки
- [ ] Стрим токенов виден во время запуска на Ultra; после завершения — полная запись.
- [ ] 1 000 запусков в списке без лагов (виртуализация).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
npx playwright test e2e/engine_trace.spec.ts
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
Сделано в PR «L4: фронт» (`pages/engine/EnginePage.tsx`, `widgets/LogPanel.tsx`): список прогонов текущего прогона симуляции (или всех), по каждому — шаги: узел, статус, токены, латентность, рассуждение, вызовы инструментов (args/result), промпт и сырой ответ (раскрываются), вход/выход шага; вкладка «Живые события» — поток WS (signals/agent/incidents/hitl/notifications/tasks). Списки обновляются по WS-инвалидации. Время: ~50 мин.
