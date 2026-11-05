# Меню подготовки сценариев34/35 перед фризом

База `52fd498ffe20c0a248e987b37fa3d1b6be796caf`, отдельный worktree
`codex/freeze-demo-menu-completion`. API/DDL/формулы/лимиты/HITL решения не меняются.

## Изменение

Меню12/13 сохраняет прежнюю read-only навигацию. Новые явно помеченные Mock
кнопки34/35 запускают существующий `POST /api/scenarios/{id}/run`, тело содержит
только `reset_mode=counters`, `seed=42` и label. Это настоящий native preparation action,
а не простое открытие пустого экрана. Backend по-прежнему требует effective Mock
всех ролей до эффектов; при live/replay409 отображается обычная ErrorBox,
без автопереключения профилей, retry или обхода preflight.

На202 проверяются положительный safe integer id, kind=scenario и scenario_id;
переход сохраняет returned run scope: кабинет deposits/week или CSI/month.
CSI создаёт предусмотренные existing preparation301 входов; legal input остаётся
pending HITL. Новый код не принимает human decision и не сбрасывает baseline.
Пока POST pending, блокируются повторная подготовка, provider/baseline/play
и закрытие меню. Ref защищает и от второго click до React rerender.

Dialog ограничен высотой viewport, прокручивается его содержимое; заголовок и
Close остаются видимы. Длинные новые кнопки имеют auto height и в compact density.

## Проверки

- `npm test -- --run src/test/demo-menu.test.tsx`:20 passed. Новые cases:
  ru/en×оба сценария, exact POST и returned scope, pending/double click,
 409/500 без retry/failover, malformed/foreign run не открывается.
  ErrorBox details в тесте раскрываются штатным summary; assertion видимости сохранён.
- `npm run typecheck`, `npm run build`: passed.
- `npm run lint`: passed,0errors; прежний warning react-refresh у DemoMenu store.
- Actual Chromium:16 component/CSS cases, ru/en×light/dark×320×480/1440×900×
  comfortable/compact. Dialog и Close внутри viewport, нет page overflow/clipped
  button label, mocked409 остаётся в меню. [Proof](freeze-demo-menu-34-35-proof.json).
  [Screenshots](../screenshots/demo-menu-34-35/) показывают320compact и desktop обеих тем/языков.

Browser proof использует отдельный Vite fixture с mocked business API409.
Native primary, real LLM/Telegram и новый банк не использовались. Existing native
preparation/UI проверки уже входят в предыдущие3897+168 passed, но новая кнопка
не является новым end-to-end native proof сама по себе. Полный suite/CI и review
актуального diff остаются родительским gate. Replay кассеты/acceptance34/35 и12
этим изменением не закрываются.

Откат — предыдущий frontend image/source; DDL нет. Созданные штатными операторами
runs сохраняются как история; автоматического удаления/переписывания нет.
