# T-182 — Захват аудио в браузере: getUserMedia, AudioWorklet, ресемплинг, клиент /ws/audio

| Поле | Значение |
|---|---|
| Эпик | E16 Аудиомониторинг отделения и мисселлинг [BRD] |
| Субагент | `SA-UI-Compliance` (экраны /compliance, /manager, голосовой ввод [BRD]) |
| Оценка | M (1–2 дня) |
| Волна | 3 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `todo` |

## Цель
Надёжный захват микрофона ноутбука и доставка PCM16 16 кГц на сервер; понятные состояния при отсутствии HTTPS/разрешения (ТЗ 5, 16.1, 22.2).

## Разделы ТЗ (docs/TZ.md)
§5, §16.1, §22.2

## Контракты
- `api/openapi.yaml: /ws/audio/{session_id}`
- `events/compliance/stt_result.schema.json`

## Зависимости
- Зависит от: [T-181](T-181-sttprovider-i-vosk-vorker-s-modelyu-v-repozitori.md), [T-007](T-007-karkas-frontend-vite-ts-strict-tailwind-tokeny-t.md)
- Блокирует: [T-187](T-187-ekran-compliance-split-screen-transkribacii-sche.md), [T-193](T-193-opcionalnye-stt-provajdery-browser-web-speech-sa.md), [T-206](T-206-nadiktovat-zhalobu-voiceinput-v-rezhime-pokaza-i.md)

## Что сделать
1. frontend/src/shared/audio/: useMicrophone (getUserMedia с echoCancellation/noiseSuppression, channelCount 1|2), AudioWorklet-процессор → ресемплинг до 16 кГц → Int16 → бинарные кадры 100 мс по WebSocket; индикатор уровня.
2. Компонент <VoiceInput> (общий для /compliance и «Надиктовать»): кнопка микрофона, уровень, частичный текст серым, финальный в поле, ошибки (нет HTTPS, нет разрешения, нет устройства) с подсказками.
3. Реконнект WebSocket без потери сессии; при недоступности STT — fallback на Web Speech API, если включён профиль browser (бейдж «внешний STT»).
4. Тесты vitest на ресемплинг и упаковку кадров; Playwright с фейковым устройством (--use-fake-device-for-media-stream) и WAV-источником.

## Критерии приёмки
- [ ] В Chrome/Edge/Firefox на localhost партиалы появляются ≤ 0,5 с от речи.
- [ ] На http://<IP> без TLS кнопка скрыта с объяснением; текстовый ввод работает.
- [ ] e2e с фейковым микрофоном зелёный.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
cd frontend && npm run test -- audio
npx playwright test e2e/voice-input.spec.ts
```

## Отчёт субагента
_Заполняется исполнителем: ветка/PR, что сделано, отклонения от карточки, затронутые контракты, скриншоты/логи, время._
