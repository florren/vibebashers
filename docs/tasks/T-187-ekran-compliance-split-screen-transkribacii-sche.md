# T-187 — Экран /compliance: split-screen транскрибации, счётчик, профиль менеджера, панель Log

| Поле | Значение |
|---|---|
| Эпик | E16 Аудиомониторинг отделения и мисселлинг [BRD] |
| Субагент | `SA-UI-Compliance` (экраны /compliance, /manager, голосовой ввод [BRD]) |
| Оценка | L (3–4 дня) |
| Волна | 4 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Экран мониторинга по BRD 3.2: лента диалога с красной подсветкой триггеров слева, счётчик 0/3 → ALERT и профиль сотрудника справа, задержки и панель Log (ТЗ 12.2 экран 9).

## Разделы ТЗ (docs/TZ.md)
§12.1, §12.2 экран 9, §12.6, §22.7

## Контракты
- `api/openapi.yaml: compliance/*`
- `events/ws/message.schema.json: compliance, stt`
- `events/compliance/*.schema.json`

## Зависимости
- Зависит от: [T-182](T-182-zahvat-audio-v-brauzere-getusermedia-audioworkle.md), [T-183](T-183-audiosessii-repliki-i-tri-rezhima-razdeleniya-sp.md), [T-186](T-186-schetchik-narushenij-mashina-sostoyanij-sessii-a.md), [T-201](T-201-panel-log-debug-kak-obschij-komponent-demo-ekran.md)
- Блокирует: [T-203](T-203-lokalizaciya-ekranov-v1-3-feed-compliance-manage.md), [T-217](T-217-ui-vkladka-transkripty-na-compliance-zagruzka-sp.md)

## Что сделать
1. features/compliance: шапка (микрофон/уровень, источник, режим ролей, старт/стоп, выбор отделения/стола/сотрудника/клиента/продукта сделки); слева — чат с пузырями «Сотрудник»/«Клиент», партиалы серым, триггеры красным с чипом категории и %; справа — счётчик крупно с заливкой, профиль менеджера, таймер, задержки STT/детектора.
2. Порог: заливка экрана красным, звуковой сигнал (файл в репозитории), баннер ALERT; осознанное исключение из принципа «не кричать» (ТЗ 12.1).
3. Горячие клавиши: пробел — переключение роли (manual), Esc — стоп; состояние по WebSocket compliance/stt с дозагрузкой since_seq.
4. Панель Log: строка каждого триггера с JSON verdict и уверенностью, вызовы LLM с латентностью.
5. Playwright: сценарий 9 из транскрипта → 3/3 ALERT ≤ 3 с после третьей фразы.

## Критерии приёмки
- [ ] Скриншоты обеих тем и состояний 0/3, 2/3, ALERT в PR.
- [ ] Задержка от финала третьей фразы до реакции счётчика ≤ 3 с на кассете (e2e-замер).
- [ ] Контраст текста на красном фоне ≥ 4.5:1.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
cd frontend && npm run test -- compliance
npx playwright test e2e/compliance.spec.ts
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
