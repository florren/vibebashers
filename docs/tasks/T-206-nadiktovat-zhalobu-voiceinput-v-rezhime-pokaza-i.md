# T-206 — «Надиктовать жалобу»: VoiceInput в режиме показа и на лендинге, signals.origin=voice_input, шаг STT в трассировке

| Поле | Значение |
|---|---|
| Эпик | E9 Лендинг, трекинг, Telegram-бот |
| Субагент | `SA-UI-Compliance` (экраны /compliance, /manager, голосовой ввод [BRD]) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 4 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `done` |

## Цель
Гость говорит жалобу в микрофон — текст появляется в поле, правится и уходит агенту обычным сигналом с метаданными STT (ТЗ 12.2 экран 7, 11, 19 п. 25, решение 20.5 п. 17).

## Разделы ТЗ (docs/TZ.md)
§3.6, §11, §12.2 экран 7, §13, §19

## Контракты
- `api/openapi.yaml: POST /api/signals (voice_meta), POST /api/public/claim (voice_meta), VoiceMeta`
- `db/schema.sql: signals.origin, voice_meta`

## Зависимости
- Зависит от: [T-182](T-182-zahvat-audio-v-brauzere-getusermedia-audioworkle.md), [T-067](T-067-zhyuri-rezhim-ruchnoj-vvod-signala-i-sravnenie-s.md), [T-119](T-119-lending-potencialnogo-klienta-antibot-proverka-q.md)
- Блокирует: [T-269](T-269-izolirovannyj-anonimnyj-chat-9999-i-tunnel-tuna.md)

## Что сделать
1. Кнопка «Надиктовать» в модале «Ввести сообщение клиента» и на /claim: одноканальная сессия VoiceInput без ролей/детектора; партиалы в поле, финализация после паузы 1,5 с; подпись «распознано офлайн-движком, проверьте текст»; скрыта без HTTPS/микрофона.
2. Backend: origin=voice_input, voice_meta (провайдер, сырой транскрипт, уверенность, длительность, латентность, edited); первый шаг трассировки «STT: Vosk, 2,1 с, 0,86»; бейдж канала «голосовой ввод (эмуляция)» в ленте.
3. Кассета для автотеста; e2e с фейковым микрофоном.

## Критерии приёмки
- [ ] Надиктованная жалоба проходит обычный граф; в трассировке виден шаг STT.
- [ ] Без микрофона текстовый ввод работает без ошибок.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
npx playwright test e2e/voice-complaint.spec.ts
pytest backend/tests/integration/test_voice_input.py
```

## Отчёт субагента
Ветка `feat/b17-tasks-stt-env`. `frontend/src/shared/audio/VoiceInput.tsx` в режиме жюри: при доступном серверном STT пишет PCM16 и отправляет в `POST /api/stt/transcribe` (офлайн Vosk), иначе Web Speech API; текст добавляется в поле обращения.
