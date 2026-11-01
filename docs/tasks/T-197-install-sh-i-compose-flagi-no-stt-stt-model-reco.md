# T-197 — install.sh и compose: флаги --no-stt, --stt-model, --record-cassettes, расширенный --offline, предупреждение про HTTPS

| Поле | Значение |
|---|---|
| Эпик | E17 Режим подстраховки демо [BRD] |
| Субагент | `SA-Infra` (инфраструктура, установка, realtime) |
| Оценка | S (≤ 0,5 дня) |
| Волна | 3 |
| Слой | `L1` Базис (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | да |
| Статус | `in_progress` |

## Цель
Установка одной командой с учётом STT и кассет; офлайн-режим выбирает replay → mock и vosk; предупреждение, если UI доступен только по http с нешаблонного хоста (ТЗ 16.1–16.2).

## Разделы ТЗ (docs/TZ.md)
§16.1, §16.2, §5.4

## Контракты
- AGENTS.md §4
- docs/TZ.md 16.2

## Зависимости
- Зависит от: [T-003](T-003-install-sh-ustanovka-odnoj-komandoj.md), [T-181](T-181-sttprovider-i-vosk-vorker-s-modelyu-v-repozitori.md), [T-194](T-194-provajder-replay-kassety-zapisannyh-otvetov-mode.md)
- Блокирует: —

## Что сделать
1. Флаги: --no-stt (не запускать воркер), --stt-model small|large (large: скачивание vosk-model-ru-0.42 с sha256, прогресс, ретраи), --record-cassettes (LLM_RECORD=1), --offline → LLM_PROFILE=replay,mock; STT_PROVIDER=vosk; бот выключен.
2. Проверка контекста микрофона: если APP_PUBLIC_URL не https и не localhost — предупреждение на русском с инструкцией (Caddy/TLS или localhost).
3. compose: ресурсы backend +1 ядро/+0,5 ГБ при STT; volume для data/models; Makefile цели cassettes-record, demo-offline, stt-bench.
4. README: раздел «Демо без интернета» и «Микрофон и HTTPS».

## Критерии приёмки
- [ ] ./install.sh --offline поднимает стек без сети и проигрывает сценарии 8–9 из меню демонстратора.
- [ ] ./install.sh --stt-model large скачивает модель один раз и переиспользует кэш.
- [ ] Предупреждение про HTTPS выводится и исчезает при корректном URL.
- [ ] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
./install.sh --offline --reset
./install.sh --no-stt --profile lite
```

## Отчёт субагента
Ревизия 01.11.2026, ветка `codex/cli-workflow-completion`: заглушки Makefile заменены рабочими командами `demo-offline` и `stt-bench`. `demo-offline` вызывает существующий `./install.sh --offline` без reset. Регрессионный dry-run проверяет реальные команды и отсутствие reset. Переустановка рабочего стенда и загрузка large-модели не выполнялись; все критерии T-197 не объявляются закрытыми. Контракты не менялись.
