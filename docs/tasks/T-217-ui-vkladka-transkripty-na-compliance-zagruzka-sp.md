# T-217 — UI: вкладка «Транскрипты» на /compliance (загрузка, список, отчёт с подсветкой семейств), раздел «Отчёты по транскриптам» на /manager

| Поле | Значение |
|---|---|
| Эпик | E18 Приём транскриптов, роутер-инструменты, «красные фразы», зоны карты [ДТЗ] |
| Субагент | `SA-UI-Compliance` (экраны /compliance, /manager, голосовой ввод [BRD]) |
| Оценка | M (1–2 дня) |
| Волна | 4 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Демонстратор перетаскивает файл и через секунды видит отчёт с цитатами и рекомендациями; руководитель видит алерт и отчёт на своём устройстве (ДТЗ FR-4.3, ТЗ 12.2 экран 11).

## Разделы ТЗ (docs/TZ.md)
§12.2, §22.8, §22.9, §19

## Контракты
- `api/openapi.yaml: /api/ingest/transcripts*, /api/compliance/transcripts/{id}/report|send, TranscriptDetail, TranscriptReport`

## Зависимости
- Зависит от: [T-216](T-216-paketnyj-analiz-transkripta-pacing-batch-transcr.md), [T-187](T-187-ekran-compliance-split-screen-transkribacii-sche.md), [T-188](T-188-ekran-manager-emulyator-plansheta-i-smart-chasov.md)
- Блокирует: [T-220](T-220-scenarii-10-transkript-roznichnogo-dialoga-i-11.md)

## Что сделать
1. features/compliance/transcripts: drag-and-drop (JSON/TXT, несколько файлов), список с статусами и счётчиком находок, деталь: реплики с подсветкой по семействам (мисселлинг — красный, грубость — бордовый, скрипт — янтарный, неверная информация — фиолетовый с «верно: …»), сводка по категориям, шкала этапов скрипта, рекомендации, план отработки, кнопки «Отправить руководителю», «Скачать Markdown».
2. /manager: раздел «Отчёты по транскриптам» рядом с лентой алертов; алерт immediate показывает цитату + рекомендацию; ack → HITL.
3. Статусы по WS (ingest, compliance); пустые состояния и ошибки формата с подсказкой формата TXT.
4. i18n ключи; e2e с файлом сценария 10.

## Критерии приёмки
- [ ] Файл scenario10_retail.txt → отчёт на экране ≤ 10 с, подсветка трёх находок.
- [ ] Руководитель видит карточку отчёта и алерт с рекомендацией.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
npx playwright test e2e/transcripts.spec.ts
```

## Отчёт субагента
- Вкладки транскриптов реализованы в составе `/compliance` (см. T-187): список, статусы received/analyzing/done/failed, число находок, отчёт и реплики. Хуки `useTranscripts/useTranscript/useTranscriptReport/useUploadTranscripts/useImportTranscripts` в `shared/api/hooks.ts`; WS topics `compliance`, `ingest` инвалидируют запросы.
