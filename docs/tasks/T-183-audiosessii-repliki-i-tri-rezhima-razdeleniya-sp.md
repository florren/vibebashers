# T-183 — Аудиосессии, реплики и три режима разделения спикеров

| Поле | Значение |
|---|---|
| Эпик | E16 Аудиомониторинг отделения и мисселлинг [BRD] |
| Субагент | `SA-Compliance` (аудиосессии, детектор мисселлинга, алерты [BRD]) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L3` Агент и контуры (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Сессия как единица анализа: источники mic/file/transcript, роли сотрудника и клиента режимами stereo/manual/auto (ТЗ 22.2–22.3).

## Разделы ТЗ (docs/TZ.md)
§22.2, §22.3, §13

## Контракты
- `db/schema.sql: audio_sessions, utterances, branches, employees`
- `api/openapi.yaml: compliance/sessions*, role, stop, utterances`
- `events/compliance/speaker_attribution.schema.json`
- `events/compliance/session_event.schema.json`

## Зависимости
- Зависит от: [T-181](T-181-sttprovider-i-vosk-vorker-s-modelyu-v-repozitori.md), [T-180](T-180-rasshirenie-zapuskov-avtosozdanie-run-kind-live.md), [T-046](T-046-interfejs-llm-provajdera-i-strukturirovannyj-vyv.md)
- Блокирует: [T-185](T-185-llm-detektor-missellinga-lightning-podtverzhdeni.md), [T-187](T-187-ekran-compliance-split-screen-transkribacii-sche.md)

## Что сделать
1. app/compliance/sessions.py: создание (ensure_live_run), источники mic (ws), file (сервер читает WAV чанками в реальном темпе через тот же STT), transcript (эталон с таймкодами, когда STT недоступен); события compliance.session_started/closed.
2. Роли: stereo — по каналу; manual — POST /role фиксирует активную роль с таймкодом, применяется к последующим финалам; auto — Lightning по схеме speaker_attribution на контексте последних реплик, < 0,7 → unknown (не анализируется); kind=speaker_attribution в agent_runs для трассировки.
3. utterances: финалы с словами/таймкодами/уверенностью; GET /utterances?since_seq для дозагрузки.
4. Сид: branches (10 ВСП в разных регионах), employees (6 на отделение, синтетические ФИО), настройка manager_chat_id.

## Критерии приёмки
- [ ] Три режима покрыты тестами на предзаписанных стерео/моно файлах; в manual переключение применяется к следующей реплике.
- [ ] Сессия закрывается по кнопке и по тишине > 90 с.
- [ ] Живое аудио не сохраняется при store_audio=false (проверка отсутствия файлов).
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
pytest backend/tests/integration/test_audio_sessions.py
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
