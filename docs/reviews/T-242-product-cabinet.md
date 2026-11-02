# T242 — настоящий кабинет продукта

Stacked branch `codex/T-242-product-cabinet` поверх `codex/T-241-cabinet-api`.
API/DDL source не менялся в UI ветке. Включён текущий main73425c9 обычной
композицией через T241; временная foundation review base описана в T241.

## Поведение

- `/cabinet` и `/cabinet/:productLine` открывают семь `data-block` из TZ24.4: scope/роль/видимость/период/run; KPI; карта/топ5/регион; лента20 и пагинированная таблица; динамика/источники; компактный actual CSI; калькулятор в Drawer. CSI скрыт для направлений без отделений и без наблюдений; блоков никогда больше7. Legacy index/marшруты не заменены.
- Только generated API22 types, actual overview/signals/roles. Ключи cache учитывают role/binding/run/period/line/filters; WS invalidation дебаунс500ms; чужой scope не используется как placeholder. `current` явно отправляется, `all` выбирается пользователем.
- Presets — представление, не auth/RBAC. Product manager без binding не получает придуманное первое направление. Strict foreign403, каталог только разрешённый; soft `all` явный. PATCH visibility сохраняет соседние settings. Compliance default existing-type OR red_word/legal_regulatory/linked misselling, explicitfalse снимает presentation preset; overview не меняет направление.
- Global PriorityStrip/NightDigest **не монтируются** на cabinet в обеих Shell. Scoped night digest внутри существующего signals-блока читает тот же cabinet/run/period/role API, без global incident/signal queries.
- Реальная геометрия РФ/центроиды, зоны из scoped threshold API, hover/focus prefetch, Enter/Space/Escape, zoom400ms, другие регионы opacity0.35, reduced motion instant. Регион показывает реальные level/routing/channel/platform; топ5 и counts берутся из overview.
- Статичная4px red-word полоса с иконкой; не более двух предложений masked summary от API; authoritative sla_due_sim vs sim_time, тихая4h метка из settings. ID/trace ссылки сохраняют run_id. Signal Drawer read-only, старый scope закрывается немедленно.
- ECharts SVG без анимации, current CSS ink/status tokens, 30 daily saved-money gaps / 12 months synthetic+partial+quality labels / platform catalog text-only. Нет fake0: неизвестные деньги/доли — `—`, known0 сохраняется.
- CSI — реальные linked responses, branch_known/wait_known и nullable branch/average; общий поток visits не приписывается направлению. Калькулятор — локальное явное допущение по actual settings/rates, ставка направления; anonymous coverage не превращается в0 и не запускает расчёт без ввода. Денежных writes нет.
- Local Undo8s только UI filters/preset/drawer; pathname/run/line/period инвалидируют; сохранены прежние правила остальных маршрутов. Rapid reset/stale callback проверены. X-Cx-Role добавляется shared API client только выбранному nondefault preset; explicit caller casing/header приоритетнее. Body/HITL/auth не меняются.

## Проверки и actual доказательства

Final application/test source `00d6abf` (Drawer fix15856a3, normal T241 composition f1c77fe):
- full frontend **384 passed**,52files (финальный `make lint` также повторил этот набор); полный composed `make lint` green (Ruff445/mypy292, bot11/5, drift193/193), typecheck green; обе production builds (`vite build` и personal) green; i18n2015keys и generated TS без diff; tasks205 дважды без diff;
- actual production Playwright **4/4**,24.9s: ru/en × light/dark, реальные KPI/API, keyboard map/prefetch/completedopacity0.35, signal Drawer, full-viewport calculator/visible input/focus Escape, strict own/foreign403, softall, reset/Undo, mobile360 nooverflow/header≤100, fixednight/reducedmotion,7blocks и scoped digest IDs;
- palette text minimum≥4.5/control≥3 в каждой теме; infinite animations0, page errors0, page non-GET attempts0, global incidents/signals queries0, external0. Setup/restore fixture явно PATCHит только собственные settings — **не утверждается DB unchanged для всей browser фазы**;
- read-only cabinet API отдельно: финальный T24165PG/unit green,98%coverage; demo5000/2813signals,25GET каждогоscope, bank p9540.49ms/direction24.15ms,107 public/private table fingerprints unchanged, LLM/external0 и safe EXPLAIN (`T-241-demo-performance.json`). Никаких compute_incident/money writes;
-14curatedPNG просмотрены и tracked в `docs/screenshots/T-242`; exact hashes/actual guards — `T-242-browser-proof.json`.

При visual review найден и исправлен clipped fixed Drawer внутри hover-transformed
card: Drawer перемещён наружу, shared Drawer/CSS не менялись; новый unit+actual
bbox regression не допускает повторения. Снимки ждут конца fade-in, не выдают
промежуточную прозрачность за готовый экран.

## Оставшиеся gates и отдельные карточки

T241 API22/DDL18/actor_role требует human contract review; exact-head CI обязателен.
Исходный backend full gate и focused corrections/remaining phases versioned в
T241 report, не выдаются за единый финальный зелёный `make test`. Реальный GigaChat
не вызывался по заданию, его DoD proof здесь отсутствует.
T244 report всё ещё реальный guarded501, кнопка показывает server problem;
T249 полный CSI — отдельная задача, текущая компактная сводка основана на данных.
T243 полный расширенный калькулятор — отдельная карточка; формулы/premium policy
не расширялись. Статус карточки in_progress до CI/review, placeholder KPI нет.
