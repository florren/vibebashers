# Подтверждённое завершение микрофонной встречи

При native Vosk WebSocket последняя `final.session` ещё содержит `status=live`.
Сервер затем присылает `closed` с сохранённым отчётом; UI показывал отчёт, но
оставлял badge «идёт». Исправление обновляет только статус локальной проекции
`sess`, сохраняя счётчики. Принимается `closed` текущего socket и его session_id.
Разрыв транспорта и `error` не считаются подтверждённым завершением встречи.
Backend, audio I/O, правила детектора, ledger и публичный контракт не меняются.

## Проверки

- До исправления: 4 regression failures, 2 passes. После: 6 новых + 3 соседних
  component tests проходят. Покрыты ru/en, сохранение счётчиков, disconnect/error,
  чужая сессия и запоздалый event старого socket после начала новой встречи.
- Полный frontend: 589 tests проходят; ESLint, TypeScript и production build проходят.
- Actual production bundle в isolated full Chrome: ru/en × light/dark — 4/4.
  В каждой проверке real getUserMedia/AudioWorklet получает фиксированный WAV,
  PCM16 идёт по настоящему `/ws/audio/{id}` в offline Vosk. Проверены последовательные
  utterances, последняя live final, затем matching closed/report, closed badge и
  независимый GET session=closed; tracks остановлены.
- Отдельно ru/light 320px: closed badge и счётчик помещаются, document/body не шире
  viewport, кнопка начала встречи получает focus. Существующее частичное обрезание
  controls заголовка сессии на 320px не исправлялось и не считается полным mobile QA.
- Own Docker network internal; 0 external requests, browser SpeechRecognition calls,
  page errors, LLM wire attempts; все 6 сохранённых сессий без хранения аудио.
  Использованы только свои синтетические данные; primary не изменялся.

Evidence и hashes production assets: `live-meeting-closed-status-coverage.json`.
Приватные screenshots/logs находятся в `.runtime/freeze-live-meeting-*` вне Git.
Физический микрофон, сетевой STT и внешняя доставка этой проверкой не покрываются.

Откат: вернуть UI handler и удалить новый regression test; DB изменений нет.

Скриншоты настоящего offline Vosk UI после server closed (synthetic bank/WAV):
[ru/light](../screenshots/live-meeting/closed-ru-light.png),
[ru/dark](../screenshots/live-meeting/closed-ru-dark.png),
[en/light](../screenshots/live-meeting/closed-en-light.png),
[en/dark](../screenshots/live-meeting/closed-en-dark.png),
[Close при320px](../screenshots/live-meeting/closed-en-dark-320.png).
Физический микрофон этими WAV-проверками не подтверждается.
