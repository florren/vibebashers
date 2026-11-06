# Cached restart после сетевого сбоя

`install.sh --restart` — отдельный ранний режим. Он пропускает изменение `.env`, build/pull, Vosk, seed, reset, Tuna и создание контейнеров. Комбинации с установочными флагами отклоняются до действий. `--reset` сохраняет прежний смысл удаления данных после build preflight.

Host helper использует native Compose discovery и до первого изменения проверяет по одному штатному postgres/backend/personal и их точные локальные image IDs. One-off контейнеры не перезапускаются. Нет контейнера/образа — нет автоматической установки или destructive fallback. Сохраняется установленная версия image IDs; новые изменения engine/agent требуют отдельного обновления образа.

Работающий PostgreSQL не останавливается; остановленный запускается тем же ID. Его штатный Docker healthcheck проверяется до apps, бюджет120s. Backend/personal перезапускаются существующими IDs с grace120s. Далее проверяются оба локальных health endpoints с бюджетом120s каждый, без HTTP proxy/DNS: числовые loopback-адреса и bounded curl. Контейнеры/volumes не пересоздаются и не удаляются. При ошибке после начала рестарта возможна частичная готовность процессов; она сообщается явно, fallback к reset/seed отсутствует.

Команда не отправляет simulation Start/Resume, не создаёт run и не пишет историю/RNG. Состояние `interrupted` требует явного Resume через прежние guards. Восстановление работающих процессов после возврата сети описано в [общем review](network-recovery-review.md).

Ошибки preflight build полностью сохраняются в tempfile `0600`. Вывод содержит только путь и явную команду `bash ./install.sh --restart` для существующего стенда. Содержимое логов и `.env` на консоль не переносится.

## Проверки

Targeted15PASS, вместе с installer neighbors66PASS7.03s: cached restart при недоступных build/pull, отсутствие seed/down/new containers/env writes, missing service/image до действий, preserved one-offs, exclusive flags, PG neverhealthy до app restart, HTTP failures/timeouts bounded и приватный build log с невыведенным synthetic secret. Ruff, strict mypy двух scripts и bash syntax PASS.

Native orchestration V5 PASS на собственных cached images: настоящий Docker/PG и явно синтетические HTTP stand-ins во внутреннем Docker network без внешнего маршрута. Проверяются IDs/images/PG StartedAt и synthetic storage sentinel; это не подмена проверки настоящего банковского startup. Подтверждены unchanged PG ID/StartedAt, app IDs/image IDs и synthetic run/history/RNG storage; apps действительно restarted, build/pull/down/seed0 и .env не создан. Все fixture containers остановлены; после архивации удалены только12own ephemeral containers и1unused own network, volumes/images/primary0. Один подтверждённый internal network зарезервирован для combinedQA. Ранние harnessFAIL (internal publishedports, неполные manualCompose labels, subnet pool, initdb readiness race) сохранены и не объявляются успешными. Полные gates и exact source публикуются в PR.

## Откат и ограничения

Откат кода не меняет БД. Даже без внешней сети нужны исправный Docker, имеющиеся образы/контейнеры и доступность локальных сервисов. Команда не исправляет повреждение хранилища или недоступность внешнего LLM. Нормальные application startup/recovery effects сохраняются.
