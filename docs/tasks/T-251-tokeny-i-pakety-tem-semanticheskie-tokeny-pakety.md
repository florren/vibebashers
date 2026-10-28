# T-251 — Токены и пакеты тем: семантические токены, пакеты brand и ops, переключатель темы, тест контраста

| Поле | Значение |
|---|---|
| Эпик | E21 Дизайн-система v2: темы, циркадный режим, «кикубари», каркас и «Обзор» [ПРОТО] |
| Субагент | `SA-UI-Design` (токены, темы, циркадный режим, режимы интерфейса [ПРОТО]) |
| Оценка | M (1–2 дня) |
| Волна | 7 |
| Слой | `L4` Фронт (владелец — см. docs/TEAM-SPLIT.md и CODEOWNERS) |
| В демо-минимуме | нет — можно отложить |
| Статус | `done` |

## Цель
Фундамент визуального языка v2 (ТЗ 26.1) без регрессий существующих экранов.

## Разделы ТЗ (docs/TZ.md)
§26.1, §12.1

## Контракты
- frontend/src/index.css
- frontend/tailwind.config.ts
- frontend/src/shared/theming/
- docs/adr/ADR-0010-theme-packs.md

## Зависимости
- Зависит от: [T-007](T-007-karkas-frontend-vite-ts-strict-tailwind-tokeny-t.md)
- Блокирует: [T-249](T-249-ekran-csi-csi-tablica-zhalob-scatter-bar-po-dolz.md), [T-252](T-252-cirkadnyj-dvizhok-6-faz-istochniki-sim-real-fixe.md), [T-253](T-253-rezhimy-tihij-kikubari-i-situacionnyj-centr-prav.md), [T-254](T-254-karkas-v2-bokovaya-navigaciya-sostoyanie-sistemy.md)

## Что сделать
1. Выделить семантические токены (`--surface-1…3`, `--ink`, `--line`, `--brand`, `--ok/--warn/--danger/--info`, `--signal-*`, `--p1…p4`, `--zone-*`, `--trace-*`, `--focus-ring`); существующие значения 12.1 становятся пакетом `brand` (светлая и тёмная).
2. Пакет `ops` («Ситуационный центр») — запасной пакет (20.7 № 68, ADR-0010): перенести значения из стилей прототипа 2.4 (oklch с запасным sRGB), моноширинные метки, тонкие рамки; светлый вариант.
3. Селектор темы в шапке (`widgets/Header.tsx`, заменяет текущий переключатель light/dark): пакет `brand|ops` × режим `light|dark|auto|circadian`, `aria-label`, i18n; состояние `ui.theme_pack`, `ui.mode`, `ui.density` (Zustand + `settings` + `localStorage`), дубль в меню демонстратора; применение через `data-pack`/`data-mode` на `<html>`.
4. Юнит-тест контраста по токенам для всех сочетаний пакет × режим (текст ≥ 4,5:1, элементы ≥ 3:1); шрифты Inter и JetBrains Mono локально.
5. Визуальная проверка существующих экранов в двух пакетах, исправление регрессий; ADR-0010 уже принят — при отклонениях дополнить.

## Критерии приёмки
- [x] Все существующие экраны корректны в `brand` без изменений вида; `ops` включается из селектора в шапке без перезагрузки.
- [x] Тест контраста зелёный, красный не используется для фона больших областей.
- [x] Выбор темы переживает перезагрузку (без «вспышки»).
- [x] `make lint && make test` зелёные; Definition of Done из AGENTS.md §8 выполнен.

## Как проверить
```bash
cd frontend && npx vitest run src/shared/theming
cd frontend && npx tsc --noEmit && make i18n-check
```

## Отчёт субагента
Частично включено в PR #66: пакеты brand/ops, ThemeSelector в шапке и демо-меню, localStorage, семантические токены, тест контраста. Исправлен порядок CSS @import и актуализированы mocks существующих UI-тестов. Карточка не закрыта: полноценный circadian по сим-времени, синхронизация settings и визуальная приёмка всех экранов в этот пакет не входят.

Приёмка следующей волны: `feat/T-251-theme-settings`. Существующая ops-палитра принята рабочей основой после уточнения пользователя «сгенерированный стиль другой нейронкой»; исходника нет, точное соответствие не подтверждается (ADR-0010 дополнен). Brand остаётся основным; семантические цвета реально используются Tailwind. Контраст ink/muted/status ≥4.5 и focus/control/primary ≥3 на трёх поверхностях, on-primary ≥4.5 проверяется из CSS: **36 сочетаний pack/mode/phase**. Декоративные zone/signal цвета сохранены; красный не становится большим фоном.

Settings/localStorage/Zustand синхронизированы, PATCH сериализован и не затирает соседние UI-поля; поздний GET не отменяет выбор пользователя. Неотправленные значения переживают reload, ошибка видима (ru/en), отправка повторяется при reconnect/mount. Плотность применяется data-density, шапка переносится и сохраняет видимость селектора, дубли selector имеют уникальные IDs. Auto реагирует на OS media changes; базовый circadian — шесть сим-фаз Europe/Moscow, без подмены часами ОС; last phase/bootstrap не дают светлой вспышки. T-252 не закрывается: real/fixed/solar/8s transition/night digest остаются ей.

Проверки Node22: frontend **68 passed**, lint/strict build зелёные (старые FastRefresh и chunk-size warnings сохранены); theming **40 passed** (контраст36 + settings/race/retry/clock4). Chromium **2 passed** fonts + themes (реальный изолированный API, сохранение, reload без вспышки, auto). Матрица **64** = 8 экранов ×2 pack ×2 mode ×2 language: 0 page errors, все theme controls видимы; выборочный визуальный просмотр скриншотов workspace/engine выполнен, `docs/screenshots/T-251/`. Полноценный pixel-diff с отсутствующим прототипом не выполнялся. `make lint test` зелёный: **426 unit / 79 integration / 22 scenarios**, skips **16/2/2**. i18n **1036** ключей, owners --allow-cross; CI — перед merge.


Проверка PR #72 после слияния PR #73: main включён без переписывания истории, конфликт Header разрешён с сохранением GlobalSearch и маршрутов /trace и /journey. Исправлена подтверждённая регрессионным тестом гонка: поздний начальный GET не отменяет выбор пользователя даже после успешного PATCH. Для text-brand добавлен отдельный --brand-foreground; фоновые брендовые цвета сохранены. Проверка контраста охватывает этот токен и реальные сгенерированные ссылки в браузере.

Свежие локальные проверки: frontend 75 passed (из них 41 theming), strict typecheck/lint/build, 7 Playwright (settings/reload/auto, четыре сочетания pack/mode с контрастом ссылок ≥4.5, fonts, четыре trace/journey ru/en × light/dark с мобильными вкладками). Снимки trace/journey пересозданы тестом после обновления шапки. make lint, contracts, OpenAPI drift, owners --allow-cross и i18n 1106 — успешно. Актуальный полный backend/CI-прогон и итог merge — в PR #72. Контракты и backend относительно main не менялись.
