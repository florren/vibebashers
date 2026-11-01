# Мобильная адаптация — #148

Общая оболочка всех маршрутов и публичный чат поддерживают независимый от
симуляции выбор «Экран: Авто / Смартфон / Компьютер». Он хранится в localStorage
`cx.ui.device_mode` текущего origin; выбор на :9999 не меняет :8000. Существующие
светлая/тёмная темы, пакеты brand/ops и языки ru/en сохранены.

На смартфоне меню открывается кнопкой справа в компактной шапке. В нём находятся
переходы, устройство, темы, язык, режим жюри и прежнее управление симуляцией.
Четыре дополнительных KPI раскрываются отдельной кнопкой; поиск и фильтры —
сворачиваемым блоком. Состояние фильтров не сбрасывается. Полный текст карточек
переносится; инциденты показываются вертикально. Широкие служебные таблицы можно
прокручивать внутри блока. Финансовый реестр на телефоне представлен карточками
с суммами предотвращённых потерь, возврата и чистого эффекта.

## Проверка

- Vitest: режим auto при изменении media query, сохранение явного выбора,
  desktop viewport и возврат к viewport телефона, сохранение фильтров,
  удержание/возврат фокуса, Escape, финансовая карточка и прежняя детализация.
- Playwright `e2e/mobile.spec.ts`: 320/390/430 CSS px × ru/en × light/dark,
  32 состояния (все маршруты, десять вкладок рабочего места, девять шагов настроек),
  отсутствие горизонтального переполнения документа и ошибок JS. API-записи
  запрещены, темы подменяются только в GET /api/settings. Дополнительно —
  принудительный мобильный режим на ПК, reload, версия ПК на телефоне и landscape.
- Ручная браузерная проверка на 320 px: раскрытые фильтры Journey, drawer сигнала,
  все шаги настроек и выбранный прогон агента. Скриншоты ниже сняты с живыми
  демонстрационными данными; числа меняются при работающей симуляции.
- Команды: `npm run lint`, `npm run typecheck`, `npm test -- --run`,
  `npm run build`, отдельный strict typecheck `e2e/mobile.spec.ts`,
  `E2E_BASE_URL=http://127.0.0.1:5174 npx playwright test mobile.spec.ts`,
  `make lint test`, `python scripts/contracts_check.py`,
  `python scripts/i18n_check.py`, `python scripts/check_owners.py --base main --allow-cross`.
  Итоги запусков и CI приведены в PR.
- Дополнительный общий `npx tsc -p e2e/tsconfig.json --noEmit` воспроизводит две
  существующие ошибки и на main: implicit any в `journey-modes.spec.ts:54` и
  неразрешённый alias в `recordings.ts:1`. Новый mobile.spec.ts проходит отдельный
  strict typecheck; штатный typecheck приложения и сборка проходят.

Эмуляция использует Chromium с touch/mobile viewport. Проверки на физических
iPhone/Android и в Safari не выполнялись. API, контракты, расчёты, сценарии
обработки обращений и сохранённые данные этим изменением не меняются.

## Скриншоты — 390 × 844

Рабочее место: [ru light](../screenshots/mobile-layout-148/workspace-ru-light.png),
[ru dark](../screenshots/mobile-layout-148/workspace-ru-dark.png),
[en light](../screenshots/mobile-layout-148/workspace-en-light.png),
[en dark](../screenshots/mobile-layout-148/workspace-en-dark.png).

Journey: [ru light](../screenshots/mobile-layout-148/journey-ru-light.png),
[ru dark](../screenshots/mobile-layout-148/journey-ru-dark.png),
[en light](../screenshots/mobile-layout-148/journey-en-light.png),
[en dark](../screenshots/mobile-layout-148/journey-en-dark.png).

Finance: [ru light](../screenshots/mobile-layout-148/finance-ru-light.png),
[ru dark](../screenshots/mobile-layout-148/finance-ru-dark.png),
[en light](../screenshots/mobile-layout-148/finance-en-light.png),
[en dark](../screenshots/mobile-layout-148/finance-en-dark.png).

Дополнительно: [меню](../screenshots/mobile-layout-148/workspace-ru-dark-menu.png),
[финансовые карточки](../screenshots/mobile-layout-148/finance-ru-dark-cases.png).
