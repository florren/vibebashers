# T-086 — Layout рабочего места CX: шапка, сим-часы, панель управления, KPI

| Поле | Значение |
|---|---|
| Эпик | E7 Рабочее место CX |
| Субагент | `SA-UI-Workspace` (рабочее место CX) |
| Оценка | M (1–2 дня) |
| Волна | 2 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Каркас экрана 2 из ТЗ 12.2 по мотивам прототипа: верхняя панель, вкладки, боковая панель, статус симуляции.

## Разделы ТЗ (docs/TZ.md)
§12.2 экран 2, §12.1, §12.3

## Контракты
- `api/openapi.yaml: sim/*, metrics/dashboard`

## Зависимости
- Зависит от: [T-040](T-040-servis-zapuskov-emulyacii-sim-runs-run-id-rezhim.md), [T-007](T-007-karkas-frontend-vite-ts-strict-tailwind-tokeny-t.md), [T-008](T-008-realtime-listen-notify-websocket-hab.md), [T-031](T-031-simclock-sim-state-i-upravlenie-simulyaciej.md)
- Блокирует: [T-079](T-079-ui-ocheredi-hitl-i-kartochki-resheniya.md), [T-080](T-080-ui-zadach-i-podarkov.md), [T-087](T-087-lenta-signalov.md), [T-088](T-088-teplovaya-karta-rf-s-drill-down-do-gorodov.md), [T-089](T-089-doska-i-tablica-incidentov-s-indikatorami-sla.md), [T-091](T-091-klient-360.md), [T-092](T-092-vkladki-otlozhennye-komandy-uvedomleniya.md), [T-093](T-093-dashbord-kpi-i-blok-ekonomiki.md), [T-094](T-094-vkladka-zapuski-istoriya-sravnenie-sbros-k-basel.md), [T-122](T-122-qr-kod-bota-zhyuri-rezhim-i-instrukcii-dlya-fina.md), [T-143](T-143-playwright-smouk-i-vizualnaya-regressiya.md), [T-156](T-156-polnye-slovari-ru-en-i-proverka-i18n.md), [T-195](T-195-menyu-demonstratora-skrytaya-knopka-statusy-prov.md)

## Что сделать
1. Кнопки Старт/Пауза/Стоп/Возобновить/Скорость; пилюля сим-времени показывает метку и статус текущего запуска; селектор «Запуск» (current/all/прошлые) в глобальном сторе Zustand (runStore) — его значение используют все экраны как параметр run_id. Подтверждение перед Стоп.
2. Шапка: сим-часы и день, фаза (циркадная тема), кнопки Старт/Пауза/Шаг/Сброс дня, пресеты скорости, переключатели темы/языка/роли (X-Role), индикатор LLM-профиля и остатка токенов.
3. KPI-полоса из /api/metrics/dashboard с живым обновлением.
4. Вкладки: Сигналы, Карта, Инциденты, Требует решения, Отложенные, Задачи, Команды, Уведомления, Дашборд; маршруты с сохранением фильтров в URL.
5. Кнопка «Сценарии» с запуском демо-сценариев и «Жюри-режим».

## Критерии приёмки
- [ ] Переключение вкладок без перезагрузки данных (кэш TanStack).
- [ ] Панель управления отражает состояние симуляции ≤ 1 с.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
npx playwright test e2e/workspace.spec.ts
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
