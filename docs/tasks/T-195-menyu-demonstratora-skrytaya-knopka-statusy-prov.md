# T-195 — Меню демонстратора: скрытая кнопка, статусы провайдеров, переключатели, запуск предзаписанных входов, QR

| Поле | Значение |
|---|---|
| Эпик | E17 Режим подстраховки демо [BRD] |
| Субагент | `SA-UI-Workspace` (рабочее место CX) |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Ctrl+Shift+R / долгое нажатие на логотип → меню с индикаторами сети и провайдеров, переключением LLM/STT, кнопками сценариев 8–9, сбросом к baseline, QR для /manager; тихий бейдж режима в футере (ТЗ 12.7).

## Разделы ТЗ (docs/TZ.md)
§12.7, §5.4, §4.6

## Контракты
- `api/openapi.yaml: demo/*`
- `events/demo/failover.schema.json`
- `events/ws/message.schema.json: demo`

## Зависимости
- Зависит от: [T-194](T-194-provajder-replay-kassety-zapisannyh-otvetov-mode.md), [T-086](T-086-layout-rabochego-mesta-cx-shapka-sim-chasy-panel.md), [T-094](T-094-vkladka-zapuski-istoriya-sravnenie-sbros-k-basel.md), [T-040](T-040-servis-zapuskov-emulyacii-sim-runs-run-id-rezhim.md)
- Блокирует: [T-203](T-203-lokalizaciya-ekranov-v1-3-feed-compliance-manage.md), [T-204](T-204-demo-skript-7-8-i-3-5-minut-readme-razdelov-zhiv.md)

## Что сделать
1. Backend: GET /api/demo/status (health провайдеров, режимы, текущий запуск, badge_ru), POST /api/demo/failover (ручное переключение, событие demo.failover), POST /api/demo/play/{scenario_id} (пост сценария 8; аудио/транскрипт сценария 9 с reset none|counters|baseline), GET /api/demo/assets.
2. Frontend: скрытое меню (хоткей, long-press), не рендерится в обычном режиме и не попадает в скриншоты README; индикаторы; кнопки; QR на /manager с адресом текущего хоста.
3. Футер: тихий бейдж «офлайн-кассета от <дата>» / «mock» / «STT: файл» на всех экранах, когда режим не live.
4. Все переключения → sim_events demo.failover и топик demo.

## Критерии приёмки
- [ ] Меню открывается только хоткеем/long-press; переключение LLM → replay отражается в следующем запуске агента и в бейдже.
- [ ] Запуск сценария 8 из меню публикует пост и проходит цепочку; сценария 9 — стартует сессию из файла.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
cd frontend && npm run test -- demo-menu
pytest backend/tests/integration/test_demo_api.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
