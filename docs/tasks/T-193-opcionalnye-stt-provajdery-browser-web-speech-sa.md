# T-193 — Опциональные STT-провайдеры: browser (Web Speech), SaluteSpeech, OpenAI-совместимый аудио-сервер

| Поле | Значение |
|---|---|
| Эпик | E16 Аудиомониторинг отделения и мисселлинг [BRD] |
| Субагент | `SA-STT` (распознавание речи [BRD]) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 5 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `todo` |

## Цель
Профили STT за той же абстракцией для корпоративного контура и экспериментов; выключены по умолчанию (ТЗ 5.3).

## Разделы ТЗ (docs/TZ.md)
§5.1, §5.3

## Контракты
- `api/openapi.yaml: stt/providers`
- `events/common.schema.json: stt_provider`

## Зависимости
- Зависит от: [T-181](T-181-sttprovider-i-vosk-vorker-s-modelyu-v-repozitori.md), [T-182](T-182-zahvat-audio-v-brauzere-getusermedia-audioworkle.md)
- Блокирует: —

## Что сделать
1. browser: распознавание на клиенте (SpeechRecognition ru-RU, interimResults), результаты как готовые реплики в сессию; бейдж «внешний STT».
2. salutespeech: gRPC v2 потоковое, до 2 каналов; включается только при наличии учётных данных юрлица (Freemium физлиц закрыт с 15.07.2026); документация ограничения в настройках.
3. openai_compatible_audio: псевдо-поток чанками 2–3 с на /v1/audio/transcriptions; пометка «не для демо».
4. Таблица возможностей провайдеров в GET /api/stt/providers и в docs/LICENSES.md.

## Критерии приёмки
- [ ] Каждый провайдер проходит POST /api/stt/test при наличии доступа и корректно сообщает недоступность без него.
- [ ] По умолчанию активен только vosk.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/unit/test_stt_providers.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
